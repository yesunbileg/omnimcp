"""Single-user daemon. Bridges disconnect independently of background jobs."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import importlib.metadata
import json
import os
import signal
import socket
import struct

from agentic_os_mcp.adapters import build_registry

from .client import MAX_REQUEST, socket_path
from .engine import Engine
from .state import Store, encode


async def serve():
    os.umask(0o077)
    store = Store()
    worker_lock = (store.root / "worker.lock").open("a")
    try:
        fcntl.flock(worker_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another worker owns this state directory.") from None
    registry = build_registry()
    for plugin in importlib.metadata.entry_points(group="agentic_os_mcp.adapters"):
        plugin.load()(registry)
    engine = Engine(registry, store)
    store.recover()
    path = socket_path()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.parent.stat().st_uid != os.getuid():
        raise SystemExit("Socket directory belongs to another user.")
    if path.exists():
        # The state lock alone cannot protect an overridden socket owned by a different worker.
        with socket.socket(socket.AF_UNIX) as probe:
            try:
                probe.connect(str(path))
            except OSError:
                path.unlink()
            else:
                raise SystemExit("Worker socket is already in use.")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    async def connection(reader, writer):
        try:
            peer = writer.get_extra_info("socket")
            _, uid, _ = struct.unpack(
                "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if uid != os.getuid():
                return
            raw = await asyncio.wait_for(reader.readline(), timeout=10)
            if len(raw) > MAX_REQUEST or not raw.endswith(b"\n"):
                response = {
                    "status": "invalid_params",
                    "message": "Request too large or incomplete.",
                }
            else:
                try:
                    request = json.loads(raw)
                    if not isinstance(request, dict):
                        raise ValueError("Request must be an object.")
                    response = await asyncio.to_thread(engine.request, request)
                except ValueError as exc:
                    response = {"status": "invalid_params", "message": str(exc)}
            writer.write(encode(response).encode() + b"\n")
            await writer.drain()
        except (TimeoutError, ValueError, ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_unix_server(connection, path=str(path), limit=MAX_REQUEST + 1)
    os.chmod(path, 0o600)
    store.event("worker", {"status": "ready", "pid": os.getpid()})
    try:
        async with server:
            await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        # Mark stopped jobs interrupted on graceful shutdown too; changes are never replayed.
        await asyncio.to_thread(engine.close)
        path.unlink(missing_ok=True)
        store.event("worker", {"status": "stopped"})
        store.close()
        worker_lock.close()


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
