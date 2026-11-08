"""jobs/registry.py: registration, load_handlers importing every handler module (no missing-module tolerance), JobContext helpers."""

from __future__ import annotations

import importlib
import logging
import sys

import pytest

from wd.jobs import queue, registry
from wd.jobs.registry import HANDLER_MODULES, JOB_TYPES, JobContext


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(registry._HANDLERS)
    registry.reset()
    yield
    registry.reset()
    registry._HANDLERS.update(saved)


def _jobs_check_list() -> set[str]:
    """The jobs.type CHECK list of the NEWEST migration that (re)creates `jobs` (0001, rebuilt by 0016_word_dances.sql)."""
    import re
    from pathlib import Path

    files = sorted((Path(registry.__file__).resolve().parents[1] / "migrations").glob("*.sql"))
    for path in reversed(files):
        sql = path.read_text(encoding="utf-8")
        m = re.search(r"CREATE TABLE jobs(?:_new)?\s*\(.*?type\s+TEXT NOT NULL CHECK \(type IN \(([^)]*)\)\)", sql, re.S)
        if m:
            return {t.strip().strip("'") for t in m.group(1).split(",")}
    raise AssertionError("no migration creates jobs")


def test_job_types_match_the_schema_check_list():
    assert _jobs_check_list() == set(JOB_TYPES)


def test_register_and_registered_types():
    @registry.register("send_email")
    def h(ctx, jobs):
        pass

    assert registry.registered_types() == {"send_email"}
    assert registry.get_handler("send_email") is h
    assert registry.get_handler("fetch_image") is None
    with pytest.raises(ValueError):
        registry.register("brew_tea")


def test_load_handlers_imports_every_handler_module():
    """Every HANDLER_MODULES entry exists and is imported (TASKS post-step 1: no Phase-0 tolerance left); that each one
    registers its job type is test_registry_complete.py's job (it reloads the modules so the decorators run again)."""
    assert registry.load_handlers() is None
    for module in HANDLER_MODULES:
        assert module in sys.modules, module


def test_load_handlers_propagates_import_errors(monkeypatch):
    real = importlib.import_module

    def fake(name, package=None):
        if name == HANDLER_MODULES[0]:
            exc = ModuleNotFoundError("No module named 'wd.ai.budget'")
            exc.name = "wd.ai.budget"  # a dependency of an EXISTING module is missing → must surface
            raise exc
        return real(name, package)

    monkeypatch.setattr(registry.importlib, "import_module", fake)
    with pytest.raises(ModuleNotFoundError):
        registry.load_handlers()


def test_load_handlers_does_not_tolerate_a_missing_handler_module(monkeypatch):
    """A handler module that cannot be imported is a packaging error, never a silently missing handler."""

    def fake(name, package=None):
        exc = ModuleNotFoundError(f"No module named '{name}'")
        exc.name = name
        raise exc

    monkeypatch.setattr(registry.importlib, "import_module", fake)
    with pytest.raises(ModuleNotFoundError):
        registry.load_handlers()
    assert registry.registered_types() == set()


def test_job_context_helpers(settings, connect, frozen_clock):
    ctx = JobContext(db=connect, cfg=settings, clock=frozen_clock, enqueue=queue.enqueue, log=logging.getLogger("t"), worker_id="main", boot_id="abc")
    assert ctx.now() == "2026-10-14T00:00:00Z"
    assert ctx.locked_by == "main:abc"
    w = ctx.for_worker("claude-2")
    assert w.locked_by == "claude-2:abc" and w.cfg is settings and ctx.worker_id == "main"
