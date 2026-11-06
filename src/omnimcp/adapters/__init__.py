"""Native adapters register explicit, typed capability contracts."""


def build_registry():
    from omnimcp.core.registry import Registry

    from . import (
        admin,
        apps,
        codex,
        desktop,
        files,
        native,
        opencode,
        processes,
        recipes,
        shell,
        system,
    )

    registry = Registry()
    registry.close_hooks = []
    for adapter in (files, processes, system, native, desktop, shell, admin, apps, opencode, codex):
        adapter.register(registry)
    from .browser import register

    register(registry)
    recipes.register(registry)
    return registry
