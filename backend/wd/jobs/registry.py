"""Job handler registry (Phase 0, frozen contract — TASKS §I).

Handlers are registered with the :func:`register` decorator::

    @register("generate_content")
    def handle(ctx: JobContext, jobs: list[Job]) -> None: ...

Decorators only run on import, so :func:`load_handlers` imports the fixed :data:`HANDLER_MODULES`
tuple; it tolerates a *missing module* (``ModuleNotFoundError`` for that module or one of its parent
packages) ONLY while a work package has not landed yet (the Phase-0 window — WP5's
``test_registry_complete.py`` later asserts every ``jobs.type`` has a handler). Any other
``ImportError`` (a module that exists but fails to import) propagates.
"""

from __future__ import annotations

import importlib
import logging
import sqlite3
from dataclasses import dataclass, field, replace
from typing import Callable

from ..clock import Clock, to_iso
from ..config import Settings
from ..interfaces import Handler

log = logging.getLogger("wd.jobs.registry")

# the jobs.type CHECK list of 0001_init.sql
JOB_TYPES: tuple[str, ...] = (
    "generate_content",
    "lookup_word",
    "consolidate_bank",
    "generate_svg",
    "fetch_image",
    "send_email",
    "send_webhook",
    "prewarm_plan",
)

HANDLER_MODULES: tuple[str, ...] = (
    "wd.ai.content",
    "wd.ai.lookup",
    "wd.ai.consolidate",
    "wd.ai.svg",
    "wd.ai.prewarm",
    "wd.images.handler",
    "wd.delivery.email",
    "wd.delivery.webhook",
)


@dataclass
class JobContext:
    """What a handler gets besides its jobs.

    ``db`` is a connection *factory* (one connection per job run — never shared across threads);
    ``enqueue`` is ``queue.enqueue`` (call as ``ctx.enqueue(conn, type, payload, dedupe_key=...)``);
    ``worker_id``/``boot_id`` form ``jobs.locked_by`` (``'<worker>:<boot_id>'``).
    """

    db: Callable[[], sqlite3.Connection]
    cfg: Settings
    clock: Clock
    enqueue: Callable[..., int]
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("wd.jobs"))
    worker_id: str = "once"
    boot_id: str = ""

    def now(self) -> str:
        return to_iso(self.clock.now_utc())

    @property
    def locked_by(self) -> str:
        return f"{self.worker_id}:{self.boot_id}"

    def for_worker(self, worker_id: str) -> "JobContext":
        return replace(self, worker_id=worker_id)


_HANDLERS: dict[str, Handler] = {}


def register(type: str) -> Callable[[Handler], Handler]:
    """Decorator registering ``fn`` as THE handler for job ``type`` (must be a ``jobs.type`` CHECK value)."""
    if type not in JOB_TYPES:
        raise ValueError(f"unknown job type {type!r}; allowed: {', '.join(JOB_TYPES)}")

    def deco(fn: Handler) -> Handler:
        previous = _HANDLERS.get(type)
        if previous is not None and previous is not fn:
            log.warning("handler for %s replaced: %s → %s", type, getattr(previous, "__qualname__", previous), getattr(fn, "__qualname__", fn))
        _HANDLERS[type] = fn
        return fn

    return deco


def get_handler(type: str) -> Handler | None:
    return _HANDLERS.get(type)


def registered_types() -> set[str]:
    """Job types that currently have a handler (WP5's completeness test compares this with the CHECK list)."""
    return set(_HANDLERS)


def _module_missing(exc: ModuleNotFoundError, module: str) -> bool:
    name = exc.name or ""
    return name == module or module.startswith(name + ".")


def load_handlers() -> list[str]:
    """Import every :data:`HANDLER_MODULES` entry; returns the modules that were skipped because they do not exist yet."""
    skipped: list[str] = []
    for module in HANDLER_MODULES:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as e:
            if _module_missing(e, module):
                log.warning("handler module %s is not available yet; its job type has no handler", module)
                skipped.append(module)
                continue
            raise
    return skipped


def reset() -> None:
    """Forget every registered handler (tests only)."""
    _HANDLERS.clear()
