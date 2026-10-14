"""After ``registry.load_handlers()``, every value of the ``jobs.type`` CHECK list in ``0001_init.sql`` has a handler.

The Phase-0 ``ModuleNotFoundError`` tolerance of ``load_handlers`` must no longer hide a missing module: the five WP5
handler modules are asserted unconditionally; a handler module of another work package that is not yet merged into this
checkout makes the completeness assertion skip with the module named (never pass silently)."""

from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest


def _drop_editable_finder() -> None:
    """The shared venv's editable install maps ``wd`` to the main checkout; its finder would import children missing
    from this worktree from there. Keep the completeness check about THIS checkout."""
    sys.meta_path[:] = [f for f in sys.meta_path if "editable" not in (getattr(f, "__module__", "") + type(f).__name__).lower()]


_drop_editable_finder()

from wd.jobs import registry  # noqa: E402

MIGRATION = Path(registry.__file__).resolve().parents[1] / "migrations" / "0001_init.sql"
OWNERS: dict[str, str] = {
    "generate_content": "wd.ai.content",
    "lookup_word": "wd.ai.lookup",
    "consolidate_bank": "wd.ai.consolidate",
    "generate_svg": "wd.ai.svg",
    "prewarm_plan": "wd.ai.prewarm",
    "fetch_image": "wd.images.handler",
    "send_email": "wd.delivery.email",
    "send_webhook": "wd.delivery.webhook",
}
WP5_TYPES = ("generate_content", "lookup_word", "consolidate_bank", "generate_svg", "prewarm_plan")


def check_list_types() -> set[str]:
    sql = MIGRATION.read_text(encoding="utf-8")
    start = sql.index("CREATE TABLE jobs")
    m = re.search(r"type\s+TEXT NOT NULL CHECK \(type IN \(([^)]*)\)\)", sql[start:])
    assert m, "jobs.type CHECK list not found"
    return {t.strip().strip("'") for t in m.group(1).split(",")}


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Start from an empty registry. Decorators only run on import, so handler modules another test already imported
    are reloaded — otherwise ``load_handlers()`` would find nothing to do and the check would be meaningless."""
    saved = dict(registry._HANDLERS)
    registry.reset()
    for module in registry.HANDLER_MODULES:
        loaded = sys.modules.get(module)
        if loaded is not None:
            importlib.reload(loaded)
    yield
    registry.reset()
    registry._HANDLERS.update(saved)


def test_owner_map_covers_the_check_list_and_handler_modules():
    assert set(OWNERS) == check_list_types() == set(registry.JOB_TYPES)
    assert set(OWNERS.values()) == set(registry.HANDLER_MODULES)


def test_wp5_handlers_are_registered_after_load_handlers():
    skipped = registry.load_handlers()
    assert not any(m.startswith("wd.ai.") for m in skipped), skipped
    registered = registry.registered_types()
    assert set(WP5_TYPES) <= registered, set(WP5_TYPES) - registered
    for t in WP5_TYPES:
        handler = registry.get_handler(t)
        assert callable(handler) and handler.__module__ == OWNERS[t]


def test_every_jobs_type_check_value_has_a_handler():
    skipped = registry.load_handlers()
    missing = check_list_types() - registry.registered_types()
    unmerged = sorted(OWNERS[t] for t in missing if importlib.util.find_spec(OWNERS[t]) is None)
    if unmerged:
        assert set(unmerged) <= set(skipped)
        pytest.skip(f"handler modules of other work packages not merged into this checkout yet: {', '.join(unmerged)}")
    assert missing == set(), missing
    assert skipped == []


def test_a_present_module_that_registers_nothing_is_a_failure(monkeypatch):
    """A module that exists but forgets its @register must surface as a missing handler, never be skipped."""
    registry.reset()
    monkeypatch.setattr(registry, "HANDLER_MODULES", ("wd.ai.budget",))  # exists, registers no handler
    assert registry.load_handlers() == []
    assert registry.registered_types() == set()
    for module in registry.HANDLER_MODULES:
        importlib.import_module(module)
