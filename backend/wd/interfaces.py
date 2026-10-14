"""Interface contracts frozen by Phase 0 (TASKS.md §I).

Protocols and dataclasses shared across work packages. Implementations live elsewhere:
``clock.SystemClock`` / tests' ``FrozenClock`` (:class:`Clock`), ``delivery.mailer`` (:class:`Mailer`),
``images/providers/*`` (WP6, :class:`ImageProvider`), ``ai/runner.py`` (WP5, :class:`ClaudeRunner`).
Job handlers are ``Callable[[JobContext, list[Job]], None]`` and must call ``queue.finish`` /
``queue.fail`` / ``queue.defer`` for every job they were handed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

from .clock import Clock  # re-exported: `Clock` is defined once, in clock.py

if TYPE_CHECKING:  # avoid a circular import at runtime (registry imports Job from here)
    from .jobs.registry import JobContext

__all__ = [
    "Clock",
    "Mailer",
    "ImageProvider",
    "ProviderError",
    "Candidate",
    "ClaudeRunner",
    "ClaudeResult",
    "Job",
    "Handler",
    "BackgroundThread",
]


@runtime_checkable
class Mailer(Protocol):
    """Sends one message; raises ``delivery.mailer.MailerError`` on failure so the job can retry."""

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None: ...


class ProviderError(Exception):
    """An image provider request failed (HTTP status / network). ``retry_after_s`` comes from ``Retry-After``."""

    def __init__(self, message: str, status: int | None = None, retry_after_s: int | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s


@dataclass
class Candidate:
    """One image search hit, normalised across providers (DESIGN §9 `select.rank` input)."""

    provider: str
    ref: str
    title: str
    creator: str | None
    creator_url: str | None
    license: str
    license_url: str | None
    landing_url: str
    image_url: str
    width: int | None
    height: int | None
    mime: str | None
    tags: list[str] = field(default_factory=list)
    mature: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ImageProvider(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[Candidate]:
        """One HTTP request; raises :class:`ProviderError` (status, retry_after_s) on failure."""
        ...


@dataclass
class ClaudeResult:
    """Outcome of one ``claude -p`` spawn (CLAUDE_INTEGRATION §3 statuses)."""

    ok: bool
    status: str  # success | error | timeout | invalid_output | budget | auth | overloaded | spawn_error
    structured: dict | None
    cost_usd: float
    call_id: int
    model_used: str | None
    error: str | None


@runtime_checkable
class ClaudeRunner(Protocol):
    def run(
        self,
        conn: sqlite3.Connection,
        *,
        kind: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        max_budget_usd: float,
        timeout_s: int,
        word_count: int,
        job_ids: list[int],
    ) -> ClaudeResult: ...


@dataclass
class Job:
    """A ``jobs`` row with ``payload_json`` / ``result_json`` decoded."""

    id: int
    type: str
    payload: dict[str, Any]
    dedupe_key: str | None
    priority: int
    status: str
    attempts: int
    max_attempts: int
    run_after: str
    locked_at: str | None
    locked_by: str | None
    last_error: str | None
    result: dict[str, Any] | None
    created_at: str
    updated_at: str
    finished_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict) -> "Job":
        r = row if isinstance(row, dict) else {k: row[k] for k in row.keys()}
        return cls(
            id=int(r["id"]),
            type=r["type"],
            payload=_loads(r.get("payload_json"), {}),
            dedupe_key=r.get("dedupe_key"),
            priority=int(r["priority"]),
            status=r["status"],
            attempts=int(r["attempts"]),
            max_attempts=int(r["max_attempts"]),
            run_after=r["run_after"],
            locked_at=r.get("locked_at"),
            locked_by=r.get("locked_by"),
            last_error=r.get("last_error"),
            result=_loads(r.get("result_json"), None),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            finished_at=r.get("finished_at"),
        )

    @property
    def group_size(self) -> int | None:
        """``payload.group_size`` when set (bisection, CLAUDE_INTEGRATION §6.3)."""
        v = self.payload.get("group_size")
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _loads(text: str | None, default: Any) -> Any:
    if text is None or text == "":
        return default
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, dict) else default


Handler = Callable[["JobContext", list[Job]], None]
"""Job handler: must call queue.finish / queue.fail / queue.defer for every job it receives."""


@runtime_checkable
class BackgroundThread(Protocol):
    """Shape of ``ClaudeWorker`` / ``IoWorker`` (WP5) and ``Scheduler`` (WP4) as ``main.py`` drives them.

    ``main.create_app``'s lifespan constructs each as ``Cls(ctx)`` (``ctx`` a ``JobContext`` whose
    ``worker_id`` is ``claude-<n>`` / ``io-1`` / ``scheduler``), calls ``start()``, and on shutdown
    ``stop()`` then ``join(timeout)``.
    """

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...
