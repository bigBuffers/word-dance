"""Single-process worker lease — ``kv.worker_lease`` = ``{"instance": ..., "expires_at": ...}`` (CLAUDE_INTEGRATION §6.2, DEPLOY §3/§9).

The ``wd serve`` lifespan takes the lease before starting worker/scheduler threads and renews it
every 30 s; a second ``wd serve`` finds it live and idles with a warning. ``wd worker-once``,
``wd tick`` and ``wd restore`` refuse to run (exit 2) while :func:`is_live` returns a lease.

Losing the lease fences the process: when a renewal finds another instance holding it (our renewals
lapsed for more than the 90 s TTL — a long stall, a paused VM — and someone started a second ``wd serve``),
:class:`LeaseKeeper` sets its ``lost`` event, and every worker/scheduler thread built with
``lease_lost=keeper.lost`` stops claiming jobs and sweeping stale locks while it is set (otherwise both
processes would claim, and each 5-minute sweep would hand the other's running jobs back to ``queued`` —
the double Claude spend the lease exists to prevent). The keeper keeps trying ``acquire()`` every round
and clears the event once the lease is ours again, so a fenced process recovers on its own when the
other instance goes away.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Callable

from ..clock import to_iso
from ..db import kv_delete, kv_get, kv_set, tx

log = logging.getLogger("wd.jobs.lease")

KEY = "worker_lease"
TTL_SECONDS = 90
RENEW_SECONDS = 30


def read(conn: sqlite3.Connection) -> dict | None:
    raw = kv_get(conn, KEY)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) and "instance" in value and "expires_at" in value else None


def is_live(conn: sqlite3.Connection, now: str) -> dict | None:
    """The lease when it has not expired at ``now`` (ISO), else None."""
    lease = read(conn)
    if lease and str(lease["expires_at"]) > now:
        return lease
    return None


def acquire(conn: sqlite3.Connection, instance: str, now: datetime, ttl_s: int = TTL_SECONDS) -> bool:
    """Take the lease when it is absent, expired or already ours. Atomic (``BEGIN IMMEDIATE``)."""
    now_iso = to_iso(now)
    with tx(conn):
        current = read(conn)
        if current and current["instance"] != instance and str(current["expires_at"]) > now_iso:
            return False
        kv_set(conn, KEY, json.dumps({"instance": instance, "expires_at": to_iso(now + timedelta(seconds=ttl_s))}), now=now_iso)
        return True


def renew(conn: sqlite3.Connection, instance: str, now: datetime, ttl_s: int = TTL_SECONDS) -> bool:
    """Extend our own lease; False when another instance holds it (we lost it)."""
    now_iso = to_iso(now)
    with tx(conn):
        current = read(conn)
        if current and current["instance"] != instance and str(current["expires_at"]) > now_iso:
            return False
        kv_set(conn, KEY, json.dumps({"instance": instance, "expires_at": to_iso(now + timedelta(seconds=ttl_s))}), now=now_iso)
        return True


def release(conn: sqlite3.Connection, instance: str) -> bool:
    with tx(conn):
        current = read(conn)
        if current and current["instance"] == instance:
            kv_delete(conn, KEY)
            return True
        return False


class LeaseKeeper(threading.Thread):
    """Renews the lease every :data:`RENEW_SECONDS`; ``lost`` is set while another instance holds it.

    ``lost`` is the fence the worker/scheduler threads consult (``lease_lost=`` constructor argument): while it
    is set they neither claim jobs nor sweep stale locks. The keeper does not exit on a loss — it retries
    :func:`acquire` every round and clears ``lost`` when the lease is ours again (the other instance stopped or
    its own lease lapsed), so the workers resume without a restart.
    """

    def __init__(self, connect: Callable[[], sqlite3.Connection], instance: str, now_utc: Callable[[], datetime], interval_s: float = RENEW_SECONDS):
        super().__init__(name="lease-keeper", daemon=True)
        self._connect = connect
        self._instance = instance
        self._now = now_utc
        self._interval = interval_s
        self._stop_event = threading.Event()  # not `_stop`: threading.Thread uses that name internally
        self.lost = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                conn = self._connect()
                try:
                    now = self._now()
                    ok = acquire(conn, self._instance, now) if self.lost.is_set() else renew(conn, self._instance, now)
                    holder = None if ok else read(conn)
                finally:
                    conn.close()
            except sqlite3.Error as e:  # transient; try again next round
                log.warning("lease renewal failed: %s", e)
                continue
            if ok and self.lost.is_set():
                log.warning("worker lease re-acquired; this process resumes its workers", extra={"event": "lease_reacquired"})
                self.lost.clear()
            elif not ok and not self.lost.is_set():
                log.error(
                    "worker lease lost to another instance (%s); this process stops claiming jobs until it is re-acquired",
                    holder,
                    extra={"event": "lease_lost"},
                )
                self.lost.set()

    def stop(self) -> None:
        self._stop_event.set()
