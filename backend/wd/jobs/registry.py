"""Job handler registry (Phase 0, frozen contract — TASKS §I).

Handlers are registered with the :func:`register` decorator::

    @register("generate_content")
    def handle(ctx: JobContext, jobs: list[Job]) -> None: ...

Decorators only run on import, so :func:`load_handlers` imports the fixed :data:`HANDLER_MODULES`
tuple. Every entry exists since the work packages were integrated (TASKS post-step 1), so a module that
cannot be imported — missing or broken — propagates its ``ImportError``: the Phase-0 tolerance for
not-yet-landed modules is gone, and ``test_registry_complete.py`` asserts that every ``jobs.type`` CHECK
value has a handler afterwards.
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

# the jobs.type CHECK list (0001_init.sql, rebuilt with generate_dance by 0016_word_dances.sql)
JOB_TYPES: tuple[str, ...] = (
    "generate_content",
    "lookup_word",
    "consolidate_bank",
    "generate_svg",
    "fetch_image",
    "send_email",
    "send_webhook",
    "prewarm_plan",
    "generate_dance",
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
    "wd.ai.dance",
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


def load_handlers() -> None:
    """Import every :data:`HANDLER_MODULES` entry so their ``@register`` decorators run.

    Called from the ``main.py`` lifespan, ``queue.run_once`` and ``wd worker-once``. An import failure of any
    kind propagates — a missing handler module is a packaging error, never something to run without.
    """
    for module in HANDLER_MODULES:
        importlib.import_module(module)


def reset() -> None:
    """Forget every registered handler (tests only)."""
    _HANDLERS.clear()
