"""After ``registry.load_handlers()``, every value of the ``jobs.type`` CHECK list in ``0001_init.sql`` has a handler.

Since the work packages were integrated (TASKS post-step 1) ``load_handlers`` has no missing-module tolerance left:
every handler module is imported unconditionally and the completeness assertion never skips."""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

from wd.jobs import registry

MIGRATIONS = Path(registry.__file__).resolve().parents[1] / "migrations"
OWNERS: dict[str, str] = {
    "generate_content": "wd.ai.content",
    "lookup_word": "wd.ai.lookup",
    "consolidate_bank": "wd.ai.consolidate",
    "generate_svg": "wd.ai.svg",
    "prewarm_plan": "wd.ai.prewarm",
    "fetch_image": "wd.images.handler",
    "send_email": "wd.delivery.email",
    "send_webhook": "wd.delivery.webhook",
    "generate_dance": "wd.ai.dance",
}
WP5_TYPES = ("generate_content", "lookup_word", "consolidate_bank", "generate_svg", "prewarm_plan", "generate_dance")


def check_list_types() -> set[str]:
    """The jobs.type CHECK list of the newest migration that (re)creates `jobs` (0001, rebuilt by 0016_word_dances.sql)."""
    for path in sorted(MIGRATIONS.glob("*.sql"), reverse=True):
        sql = path.read_text(encoding="utf-8")
        m = re.search(r"CREATE TABLE jobs(?:_new)?\s*\(.*?type\s+TEXT NOT NULL CHECK \(type IN \(([^)]*)\)\)", sql, re.S)
        if m:
            return {t.strip().strip("'") for t in m.group(1).split(",")}
    raise AssertionError("jobs.type CHECK list not found")


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
    registry.load_handlers()
    registered = registry.registered_types()
    assert set(WP5_TYPES) <= registered, set(WP5_TYPES) - registered
    for t in WP5_TYPES:
        handler = registry.get_handler(t)
        assert callable(handler) and handler.__module__ == OWNERS[t]


def test_every_jobs_type_check_value_has_a_handler():
    registry.load_handlers()
    missing = check_list_types() - registry.registered_types()
    assert missing == set(), missing
    for t, module in OWNERS.items():
        handler = registry.get_handler(t)
        assert callable(handler) and handler.__module__ == module, (t, handler)


def test_a_present_module_that_registers_nothing_is_a_failure(monkeypatch):
    """A module that exists but forgets its @register must surface as a missing handler, never be skipped."""
    registry.reset()
    monkeypatch.setattr(registry, "HANDLER_MODULES", ("wd.ai.budget",))  # exists, registers no handler
    registry.load_handlers()
    assert registry.registered_types() == set()
    assert check_list_types() - registry.registered_types() == check_list_types()
