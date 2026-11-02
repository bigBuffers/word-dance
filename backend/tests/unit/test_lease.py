"""jobs/lease.py: acquire / renew / release semantics and the LeaseKeeper fence (`lost` set on a takeover, cleared on re-acquire)."""

from __future__ import annotations

import time
from datetime import timedelta

from wd.clock import to_iso
from wd.jobs import lease


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_acquire_renew_release(conn, frozen_clock):
    t0 = frozen_clock.now_utc()
    assert lease.acquire(conn, "A", t0)
    assert lease.read(conn) == {"instance": "A", "expires_at": to_iso(t0 + timedelta(seconds=lease.TTL_SECONDS))}
    assert not lease.acquire(conn, "B", t0)  # live and someone else's
    assert lease.acquire(conn, "A", t0 + timedelta(seconds=10))  # ours: re-entrant
    assert not lease.renew(conn, "B", t0 + timedelta(seconds=20))
    assert lease.acquire(conn, "B", t0 + timedelta(seconds=10 + lease.TTL_SECONDS + 1))  # expired: taken over
    assert not lease.renew(conn, "A", t0 + timedelta(seconds=10 + lease.TTL_SECONDS + 1))  # the loser sees it
    assert not lease.release(conn, "A") and lease.release(conn, "B") and lease.read(conn) is None
    assert lease.is_live(conn, to_iso(t0)) is None


def test_keeper_fences_on_a_takeover_and_recovers_when_the_lease_is_free_again(conn, connect, frozen_clock):
    t0 = frozen_clock.now_utc()
    assert lease.acquire(conn, "A", t0)
    keeper = lease.LeaseKeeper(connect, "A", frozen_clock.now_utc, interval_s=0.05)
    keeper.start()
    try:
        time.sleep(0.2)
        assert not keeper.lost.is_set() and lease.read(conn)["instance"] == "A"  # renewing happily
        # A's renewals lapsed for more than the TTL (stall / paused VM) and an operator started a second instance:
        # B takes the lease as of t0 + 91 s; the keeper's own clock is still t0, so this is atomic w.r.t. its renewals.
        assert lease.acquire(conn, "B", t0 + timedelta(seconds=lease.TTL_SECONDS + 1))
        assert keeper.lost.wait(5), "the keeper never noticed the loss"
        time.sleep(0.2)
        assert keeper.is_alive(), "the keeper must keep running (and retrying) after a loss"
        assert lease.read(conn)["instance"] == "B"  # a fenced keeper never overwrites the holder's lease
        assert keeper.lost.is_set()
        # the other instance goes away: the keeper re-acquires on its next round and lifts the fence
        assert lease.release(conn, "B")
        assert _wait_until(lambda: not keeper.lost.is_set()), "the fence was not lifted after the lease became free"
        assert lease.read(conn)["instance"] == "A"
        # and a second loss / recovery cycle works the same way
        assert lease.acquire(conn, "C", t0 + timedelta(seconds=lease.TTL_SECONDS + 1))
        assert keeper.lost.wait(5)
        assert lease.release(conn, "C")
        assert _wait_until(lambda: not keeper.lost.is_set())
    finally:
        keeper.stop()
        keeper.join(timeout=5)
    assert not keeper.is_alive()
