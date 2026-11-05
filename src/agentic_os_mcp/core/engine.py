"""Shared dispatch for socket, MCP and CLI. Jobs survive bridge disconnection."""

from __future__ import annotations

import contextlib
import copy
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, Union, get_args, get_origin, is_typeddict

from pydantic import AliasChoices, AliasPath, BaseModel, TypeAdapter, ValidationError
from pydantic_core import PydanticUndefined

from .execution import Context, flag
from .protocol import validate
from .registry import Fault, Registry
from .state import Store

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def lookup(value: Any, path: str):
    for part in path.split(".") if path else []:
        try:
            value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise Fault("invalid_reference", f"Cannot resolve result path: {path}") from exc
    return value


def resolve(value, results):
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return lookup(results, value["$ref"])
        return {k: resolve(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, results) for v in value]
    return value


def _contains_ref(value: Any) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_contains_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_ref(item) for item in value)
    return False


def _validate_static(annotation, value, metadata=()):
    """Validate static pieces of a value while leaving result references unresolved."""
    if isinstance(value, dict) and set(value) == {"$ref"}:
        return
    if not _contains_ref(value):
        schema = Annotated[annotation, *metadata] if metadata else annotation
        TypeAdapter(schema).validate_python(value, strict=True)
        return

    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        _validate_static(args[0], value, (*args[1:], *metadata))
        return
    if origin in (list,):
        container = Annotated[list[Any], *metadata] if metadata else list[Any]
        TypeAdapter(container).validate_python(value, strict=True)
        item_type = args[0] if args else Any
        for item in value:
            _validate_static(item_type, item)
        return
    if origin in (dict,):
        key_type, item_type = args if len(args) == 2 else (Any, Any)
        container = Annotated[dict[key_type, Any], *metadata] if metadata else dict[key_type, Any]
        TypeAdapter(container).validate_python(value, strict=True)
        for key, item in value.items():
            TypeAdapter(key_type).validate_python(key, strict=True)
            _validate_static(item_type, item)
        return
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if not isinstance(value, dict):
            raise ValueError("Expected an object.")
        fields = annotation.model_fields
        config = annotation.model_config
        used_keys = set()
        field_values = {}
        for name, field in fields.items():
            found = _model_field_input(name, field, value, config)
            if found is None:
                if field.is_required():
                    raise ValueError(f"Missing required field: {name}.")
                continue
            input_key, item = found
            used_keys.add(input_key)
            field_values[name] = (field, item)
        unknown = set(value) - used_keys
        if unknown and config.get("extra", "ignore") == "forbid":
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}.")
        for field, item in field_values.values():
            _validate_static(field.annotation, item, field.metadata)
        return
    if isinstance(annotation, type) and is_typeddict(annotation):
        if not isinstance(value, dict):
            raise ValueError("Expected an object.")
        fields = annotation.__annotations__
        missing = annotation.__required_keys__ - value.keys()
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(sorted(missing))}.")
        unknown = value.keys() - fields.keys()
        if unknown:
            raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}.")
        for name, item in value.items():
            _validate_static(fields[name], item)
        return
    if origin in (Union, types.UnionType):
        candidates = [arg for arg in args if arg is not type(None)]
        for candidate in candidates:
            try:
                _validate_static(candidate, value, metadata)
                return
            except (ValidationError, TypeError, ValueError):
                pass
        raise ValueError("Static fields do not match any allowed type.")
    # For an unresolved reference inside an otherwise opaque type, defer its value
    # check until execution. Static descendants are validated for common containers
    # and typed models above.
    if annotation is Any:
        return
    raise ValueError("Cannot validate static fields for this parameter type.")


def _model_field_input(name, field, value, config):
    aliases = []
    validation_alias = field.validation_alias
    if isinstance(validation_alias, AliasChoices):
        aliases.extend(validation_alias.choices)
    elif validation_alias is not None:
        aliases.append(validation_alias)
    elif field.alias:
        aliases.append(field.alias)
    for alias in aliases:
        found = _alias_value(value, alias)
        if found is not None:
            return found
    if name in value and (config.get("populate_by_name") or config.get("validate_by_name")):
        return name, value[name]
    if not aliases and name in value:
        return name, value[name]
    return None


def _alias_value(value, alias):
    if isinstance(alias, str):
        return (alias, value[alias]) if alias in value else None
    if not isinstance(alias, AliasPath) or not alias.path or not isinstance(alias.path[0], str):
        return None
    current = alias.search_dict_for_path(value)
    if current is PydanticUndefined:
        return None
    return alias.path[0], current


def _validate_action_params(action, params):
    if not _contains_ref(params):
        action.validate(params)
        return
    if isinstance(params, dict) and set(params) == {"$ref"}:
        return
    if not isinstance(params, dict):
        action.validate(params)
        return
    fields = action.model.model_fields
    try:
        config = action.model.model_config
        used_keys = set()
        field_values = []
        for name, field in fields.items():
            found = _model_field_input(name, field, params, config)
            if found is None:
                if field.is_required():
                    raise ValueError(f"Missing required parameter: {name}.")
                continue
            input_key, value = found
            used_keys.add(input_key)
            field_values.append((field, value))
        unknown = set(params) - used_keys
        if unknown and config.get("extra", "ignore") == "forbid":
            raise ValueError(f"Unknown parameter fields: {', '.join(sorted(unknown))}.")
        for field, value in field_values:
            _validate_static(field.annotation, value, field.metadata)
    except (ValidationError, TypeError, ValueError) as exc:
        raise Fault("invalid_params", str(exc)) from exc


class Engine:
    def __init__(self, registry: Registry, store: Store):
        self.registry, self.store = registry, store
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="os-job")
        self.lock = threading.RLock()
        self.resources: dict[str, threading.Lock] = {}
        self.contexts: dict[str, Context] = {}
        self.foreground: dict[int, Context] = {}
        self.stopping = False
        self.readonly = flag("AGENTIC_OS_READONLY")
        self.dryrun = flag("AGENTIC_OS_DRYRUN")

    def close(self):
        with self.lock:
            self.stopping = True
            for ctx in [*self.contexts.values(), *self.foreground.values()]:
                ctx.cancelled.set()
        self.pool.shutdown(wait=True, cancel_futures=False)
        while True:
            with self.lock:
                if not self.foreground:
                    break
            time.sleep(0.02)
        for hook in getattr(self.registry, "close_hooks", []):
            hook()

    def execute(self, name: str, params: dict, ctx: Context, readonly=False):
        action = self.registry.get(name)
        args = action.validate(params)
        if (self.readonly or readonly) and not action.readonly:
            raise Fault("permission_required", "Read-only access cannot run this action.")
        available = action.availability()
        if available["status"] != "available":
            raise Fault(available["status"], "Capability is unavailable.", availability=available)
        if self.dryrun and not action.readonly:
            return {"status": "dry_run", "action": name, "delivered": False}
        keys = action.resources(args) if callable(action.resources) else action.resources
        if action.privilege != "user":
            keys = (*keys, "gui-authentication")
        with self.lock:
            locks = [self.resources.setdefault(k, threading.Lock()) for k in sorted(set(keys))]
        with contextlib.ExitStack() as stack:
            for lock in locks:
                while not lock.acquire(timeout=0.1):
                    ctx.check()
                stack.callback(lock.release)
            ctx.check()
            started = time.monotonic()
            try:
                result = action.handler(ctx, **args)
                self.store.event(
                    "action",
                    {
                        "action": name,
                        "job_id": ctx.job_id,
                        "status": result.get("status", "ok") if isinstance(result, dict) else "ok",
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    },
                )
                return result
            except Fault:
                raise
            except PermissionError as exc:
                raise Fault("permission_required", str(exc)) from exc
            except FileNotFoundError as exc:
                raise Fault("not_found", str(exc)) from exc
            except Exception as exc:
                raise Fault("backend_error", str(exc)) from exc

    def submit(self, name, runner, *, auth_retry=False):
        ref = self.store.create_job(name)
        ctx = Context(self.store, job_id=ref, auth_retry=auth_retry, engine=self)
        with self.lock:
            self.contexts[ref] = ctx

        def run():
            try:
                ctx.check()
                self.store.update_job(ref, "running")
                result = runner(ctx)
                status = result.get("status", "ok") if isinstance(result, dict) else "ok"
                state = (
                    "cancelled"
                    if status == "cancelled"
                    else ("succeeded" if status in {"ok", "dry_run"} else "failed")
                )
            except Fault as exc:
                result, state = exc.result(), "cancelled" if exc.code == "cancelled" else "failed"
            except Exception as exc:
                result, state = {"status": "backend_error", "message": str(exc)}, "failed"
            self.store.update_job(ref, state, self.store.bound(result))
            with self.lock:
                self.contexts.pop(ref, None)

        self.pool.submit(run)
        return {"status": "queued", "job_id": ref}

    def validate_workflow(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 256:
            raise Fault("invalid_params", "A workflow needs 1..256 steps.")
        ids = set()
        for step in steps:
            if not isinstance(step, dict) or not {"id", "action"} <= step.keys():
                raise Fault("invalid_params", "Every step needs id, action and optional params.")
            if set(step) - {"id", "action", "params", "when", "assert", "retry", "wait"}:
                raise Fault("invalid_params", "Unknown workflow step fields.")
            if (
                not isinstance(step["id"], str)
                or not step["id"].isidentifier()
                or step["id"] in ids
            ):
                raise Fault("invalid_params", "Step IDs must be unique identifiers.")
            previous = set(ids)
            ids.add(step["id"])
            action = self.registry.get(step["action"])
            def check_refs(value, allowed=previous):
                if isinstance(value, dict):
                    if "$ref" in value:
                        if (
                            set(value) != {"$ref"}
                            or not isinstance(value["$ref"], str)
                            or value["$ref"].split(".")[0] not in allowed
                        ):
                            raise Fault(
                                "invalid_reference", "References must point to earlier steps."
                            )
                    else:
                        for item in value.values():
                            check_refs(item, allowed)
                elif isinstance(value, list):
                    for item in value:
                        check_refs(item, allowed)

            check_refs(step.get("params", {}))
            _validate_action_params(action, step.get("params", {}))
            retries = step.get("retry", 0)
            if type(retries) is not int or not 0 <= retries <= 3:
                raise Fault("invalid_params", "retry must be an integer from 0 to 3.")
            if retries and not action.idempotent:
                raise Fault("invalid_params", "Retries require an idempotent capability.")
            if step.get("wait") and not action.readonly:
                raise Fault("invalid_params", "Wait polling can only repeat observations.")
            for key in ("when", "assert", "wait"):
                if key in step:
                    cond = step[key]
                    allowed = (
                        {"path", "equals", "timeout_s", "interval_s"}
                        if key == "wait"
                        else {"path", "equals"}
                    )
                    if (
                        not isinstance(cond, dict)
                        or not {"path", "equals"} <= cond.keys()
                        or set(cond) - allowed
                        or not isinstance(cond["path"], str)
                    ):
                        raise Fault("invalid_params", f"Invalid {key} condition.")
            if "wait" in step:
                wait = step["wait"]
                if (
                    not 0.05 <= wait.get("interval_s", 0.2) <= 60
                    or not 0 < wait.get("timeout_s", 30) <= 86400
                ):
                    raise Fault("invalid_params", "Invalid polling interval/timeout.")
            if "when" in step:
                root = step["when"]["path"].split(".")[0]
                if root not in previous:
                    raise Fault("invalid_reference", "when.path must point to an earlier step.")
            for key in ("when", "assert", "wait"):
                if key in step:
                    allowed = previous | ({step["id"]} if key == "assert" else set())
                    check_refs(step[key]["equals"], allowed)

    def workflow(self, ctx: Context, steps: list[dict], timeout_s: float):
        self.validate_workflow(steps)
        results = {}
        started = time.monotonic()
        ctx.deadline = min(ctx.deadline, started + timeout_s)
        for step in steps:
            ctx.check()
            if time.monotonic() - started >= timeout_s:
                return {"status": "timeout", "steps": results}
            condition = step.get("when")
            if condition and lookup(results, condition["path"]) != resolve(
                condition["equals"], results
            ):
                results[step["id"]] = {"status": "skipped"}
                continue
            ctx.progress({"step": step["id"], "completed": len(results), "total": len(steps)})
            wait = step.get("wait", {})
            deadline = min(started + timeout_s, time.monotonic() + wait.get("timeout_s", 30))
            attempts = 0
            while True:
                try:
                    result = self.execute(
                        step["action"], resolve(step.get("params", {}), results), ctx
                    )
                except Fault as exc:
                    result = exc.result()
                status = result.get("status", "ok") if isinstance(result, dict) else "ok"
                # Auth cancellation, permission refusals and stale data are never auto-retried.
                if status in {"backend_error", "failed", "timeout"} and attempts < step.get(
                    "retry", 0
                ):
                    attempts += 1
                    ctx.sleep(0.2)
                    continue
                if status != "ok":
                    results[step["id"]] = result
                    return {"status": status, "stopped_at": step["id"], "steps": results}
                if not wait or lookup(result, wait["path"]) == resolve(wait["equals"], results):
                    break
                if time.monotonic() >= deadline:
                    results[step["id"]] = result
                    return {"status": "timeout", "stopped_at": step["id"], "steps": results}
                ctx.sleep(wait.get("interval_s", 0.2))
            results[step["id"]] = result
            assertion = step.get("assert")
            if assertion and lookup(result, assertion["path"]) != resolve(
                assertion["equals"], results
            ):
                return {"status": "verification_failed", "stopped_at": step["id"], "steps": results}
        return {"status": "ok", "steps": results}

    def request(self, request: dict):
        """Worker RPC envelope. All failures are typed, bounded results."""
        try:
            result = self._request(validate(request))
        except Fault as exc:
            result = exc.result()
        except (TypeError, ValueError, KeyError) as exc:
            result = {"status": "invalid_params", "message": str(exc)}
        except Exception as exc:
            result = {"status": "backend_error", "message": str(exc)}
        return self.store.bound(result)

    def _request(self, req):
        if self.stopping:
            raise Fault("worker_unavailable", "Worker is stopping.")
        op = req["op"]
        readonly = self.readonly or req.get("readonly", False)
        if op == "discover":
            return self.registry.discover(
                req.get("query", ""),
                req.get("action", ""),
                page(req, "offset", 0, 0, 10**9),
                page(req, "limit", 30, 1, 100),
                readonly,
            )
        if op in {"observe", "act"}:
            name, params = req["action"], req.get("params", {})
            action = self.registry.get(name)
            action.validate(params)  # fail before queuing
            availability = action.availability()
            if availability["status"] != "available":
                raise Fault(
                    availability["status"], "Capability is unavailable.", availability=availability
                )
            if op == "observe" and not action.readonly:
                raise Fault("permission_required", "observe only accepts read-only capabilities.")
            if readonly and not action.readonly:
                raise Fault("permission_required", "This request is read-only.")
            if op == "act" and req.get("background", True):
                return self.submit(
                    name,
                    lambda ctx: self.execute(name, params, ctx, readonly),
                    auth_retry=req.get("auth_retry", False),
                )
            ctx = Context(self.store, engine=self, auth_retry=req.get("auth_retry", False))
            with self.lock:
                self.foreground[id(ctx)] = ctx
            try:
                result = self.execute(name, params, ctx, readonly)
            finally:
                with self.lock:
                    self.foreground.pop(id(ctx), None)
            if op == "observe":
                result = project(result, req)
            return result
        if op == "workflow":
            if readonly:
                raise Fault("permission_required", "Workflows require acting access.")
            steps = copy.deepcopy(req["steps"])
            self.validate_workflow(steps)
            timeout = req.get("timeout_s", 3600)
            if not 0 < timeout <= 86400:
                raise Fault("invalid_params", "timeout_s must be within (0,86400].")
            return self.submit("workflow", lambda ctx: self.workflow(ctx, steps, timeout))
        if op == "job":
            ref = req.get("job_id", "")
            if req.get("cancel", False):
                if not ref:
                    raise Fault("invalid_params", "Cancellation needs a job_id.")
                if readonly:
                    raise Fault("permission_required", "Read-only access cannot cancel jobs.")
                with self.lock:
                    ctx = self.contexts.get(ref)
                    if ctx:
                        ctx.cancelled.set()
                result = self.store.job(ref)
                return {
                    "status": "cancellation_requested" if ctx else result["status"],
                    "job_id": ref,
                }
            return self.store.job(
                ref, page(req, "offset", 0, 0, 10**9), page(req, "limit", 30, 1, 100)
            )
        if op == "events":
            return self.store.events(
                page(req, "since", 0, 0, 10**15),
                page(req, "limit", 50, 1, 100),
                req.get("kind", ""),
            )
        if op == "artifact":
            return self.store.read(
                req["ref"],
                page(req, "offset", 0, 0, 2**63 - 1),
                page(req, "length", 8192, 1, 8192),
                req.get("binary", False),
            )
        raise Fault("unsupported", f"Unknown operation: {op}")


def page(req, name, default, low, high):
    value = req.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise Fault("invalid_params", f"{name} must be an integer in {low}..{high}.")
    return value


def project(value, req):
    fields = req.get("fields", [])
    if isinstance(value, list):
        # Filter before pagination. Equality filters only; no expression execution.
        filters = req.get("filter", {})
        rows = [r for r in value if all(lookup(r, k) == v for k, v in filters.items())]
        offset, limit = page(req, "offset", 0, 0, 10**9), page(req, "limit", 30, 1, 100)
        return {
            "items": [
                {f: lookup(r, f) for f in fields} if fields else r
                for r in rows[offset : offset + limit]
            ],
            "total": len(rows),
            "next": offset + limit if offset + limit < len(rows) else None,
        }
    return {f: lookup(value, f) for f in fields} if fields else value
