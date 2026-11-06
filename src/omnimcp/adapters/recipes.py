"""Deterministic, inspectable recipes; no additional LLM or API calls."""

from __future__ import annotations


def register(r):
    # Semantic aliases retain the same parameter model and resource/privilege contracts.
    for alias, target, fixed in [
        *[
            (f"service.{op}", "service.change", {"operation": op})
            for op in ("start", "stop", "restart", "reload", "enable", "disable")
        ],
        *[
            (f"package.{op}", "package.change", {"operation": op})
            for op in ("install", "remove", "upgrade")
        ],
        ("build.run", "command.exec", {}),
        ("test.run", "command.exec", {}),
        ("server.start", "pty.start", {}),
    ]:
        original = r.get(target)
        params = {
            name: (field.annotation, ... if field.is_required() else field.default)
            for name, field in original.model.model_fields.items()
            if name not in fixed
        }

        if alias in {"package.install", "package.remove"}:
            params["names"] = (list[str], ...)

        def direct(ctx, action=original, bound=fixed, **kwargs):
            return action.handler(ctx, **action.validate({**kwargs, **bound}))

        def resources(p, action=original, bound=fixed):
            return (
                action.resources({**p, **bound}) if callable(action.resources) else action.resources
            )

        r.add(
            alias,
            direct,
            params=params,
            description=original.description,
            readonly=original.readonly,
            dependencies=original.dependencies,
            available=original.available,
            privilege=original.privilege,
            verification=original.verification,
            undo=original.undo,
            idempotent=original.idempotent,
            resources=resources,
        )

    def run(ctx, steps):
        return ctx.engine.workflow(ctx, steps, 86400)

    def diagnose_slow(ctx):
        """Collect system, process and disk measurements in one deterministic job."""
        return run(
            ctx,
            [
                {"id": "system", "action": "system.snapshot"},
                {"id": "processes", "action": "process.list"},
                {"id": "storage", "action": "storage.list"},
            ],
        )

    def diagnose_service(ctx, unit: str, scope: str = "user"):
        """Read a service's real state and recent journal in one job."""
        return run(
            ctx,
            [
                {
                    "id": "state",
                    "action": "service.status",
                    "params": {"unit": unit, "scope": scope},
                },
                {"id": "logs", "action": "log.read", "params": {"unit": unit, "scope": scope}},
            ],
        )

    def install_launch(ctx, names: list[str], command: str):
        """Install explicit repository packages, then launch an explicit desktop command."""
        return run(
            ctx,
            [
                {"id": "install", "action": "package.install", "params": {"names": names}},
                {"id": "launch", "action": "desktop.launch", "params": {"command": command}},
            ],
        )

    def config_reload(
        ctx,
        path: str,
        text: str,
        expected_revision: str,
        reload_argv: list[str],
        verify_argv: list[str],
    ):
        """Revision-check config, retain undo, reload and verify with explicit commands."""
        return run(
            ctx,
            [
                {
                    "id": "config",
                    "action": "config.update",
                    "params": {
                        "path": path,
                        "text": text,
                        "expected_revision": expected_revision,
                        "reload_argv": reload_argv,
                        "verify_argv": verify_argv,
                    },
                }
            ],
        )

    def backup_verify(ctx, paths: list[str]):
        """Create a backup and check repository integrity metadata."""
        return run(ctx, [{"id": "backup", "action": "backup.create", "params": {"paths": paths}}])

    for name, fn in [
        ("diagnose_slow", diagnose_slow),
        ("diagnose_service", diagnose_service),
        ("install_launch", install_launch),
        ("config_reload", config_reload),
        ("backup_verify", backup_verify),
    ]:
        r.add(
            "recipe." + name,
            fn,
            verification="Every nested action status is checked; stops on failure.",
        )
