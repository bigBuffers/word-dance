"""jobs/registry.py: registration, load_handlers tolerance for missing modules only, JobContext helpers."""

from __future__ import annotations

import importlib
import logging

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


def test_job_types_match_the_schema_check_list():
    sql = (registry.__file__ and __import__("pathlib").Path(registry.__file__).resolve().parents[1] / "migrations" / "0001_init.sql").read_text(encoding="utf-8")
    start = sql.index("CREATE TABLE jobs")
    check = sql[start:].split("type         TEXT NOT NULL CHECK (type IN (")[1].split("))")[0]
    in_schema = {t.strip().strip("'") for t in check.split(",")}
    assert in_schema == set(JOB_TYPES)


def test_register_and_registered_types():
    @registry.register("send_email")
    def h(ctx, jobs):
        pass

    assert registry.registered_types() == {"send_email"}
    assert registry.get_handler("send_email") is h
    assert registry.get_handler("fetch_image") is None
    with pytest.raises(ValueError):
        registry.register("brew_tea")


def test_load_handlers_tolerates_missing_modules_only():
    skipped = registry.load_handlers()
    for module in skipped:
        assert module in HANDLER_MODULES
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)


def test_load_handlers_propagates_other_import_errors(monkeypatch):
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


def test_load_handlers_tolerates_a_missing_parent_package(monkeypatch):
    def fake(name, package=None):
        exc = ModuleNotFoundError(f"No module named '{name.rsplit('.', 1)[0]}'")
        exc.name = name.rsplit(".", 1)[0]
        raise exc

    monkeypatch.setattr(registry.importlib, "import_module", fake)
    assert registry.load_handlers() == list(HANDLER_MODULES)


def test_job_context_helpers(settings, connect, frozen_clock):
    ctx = JobContext(db=connect, cfg=settings, clock=frozen_clock, enqueue=queue.enqueue, log=logging.getLogger("t"), worker_id="main", boot_id="abc")
    assert ctx.now() == "2026-10-14T00:00:00Z"
    assert ctx.locked_by == "main:abc"
    w = ctx.for_worker("claude-2")
    assert w.locked_by == "claude-2:abc" and w.cfg is settings and ctx.worker_id == "main"
