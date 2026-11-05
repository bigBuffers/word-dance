"""Logging (DEPLOY §6): JSON lines to stdout → journald, optional rotating file, in-memory ring buffer.

Fields: ``ts level logger msg request_id user_id method path status duration_ms job_id job_type worker
cost_usd provider event word_ids word_id`` — any of them passed as ``extra={...}`` on a log call appears in the line.
``RING`` keeps the last 2000 formatted lines for ``wd logs --tail N`` (WP5 ``diag``).
Bodies, passwords, tokens and prompts are never logged (prompts only as word lists at DEBUG).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from collections import deque
from datetime import datetime, timezone

from .config import Settings

EXTRA_FIELDS = (
    "request_id",
    "user_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "job_id",
    "job_type",
    "worker",
    "cost_usd",
    "provider",
    "event",
    "word_ids",  # scheduler.maintenance `image_retry`: which failed-image words were requeued (PLAN §5.1 C7)
    "word_id",  # images.handler `query_ignored` (PLAN §5.1 C5): the word whose admin query was dropped — an extra not listed here never reaches the journal
)

RING: deque[str] = deque(maxlen=2000)
_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for f in EXTRA_FIELDS:
            v = record.__dict__.get(f)
            if v is not None:
                line[f] = v
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{datetime.fromtimestamp(record.created).strftime('%H:%M:%S')} {record.levelname:<7} {record.name}: {record.getMessage()}"
        extras = " ".join(f"{f}={record.__dict__[f]}" for f in EXTRA_FIELDS if record.__dict__.get(f) is not None)
        if extras:
            base += "  " + extras
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            RING.append(self.format(record))
        except Exception:  # pragma: no cover - never let logging break the app
            pass


def configure_logging(cfg: Settings, *, stream=None) -> None:
    """Install root handlers once (idempotent); later calls only adjust the level."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.log_level, logging.INFO))
    if _CONFIGURED:
        return
    formatter: logging.Formatter = JsonFormatter() if cfg.log_format == "json" else TextFormatter()
    console = logging.StreamHandler(stream or sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)
    ring = RingHandler()
    ring.setFormatter(formatter)
    root.addHandler(ring)
    if cfg.log_file:
        fh = logging.handlers.RotatingFileHandler(cfg.log_file, maxBytes=50 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)
    # uvicorn's own loggers propagate to root; we emit one request line ourselves (main.py middleware)
    logging.getLogger("uvicorn.access").disabled = True
    _CONFIGURED = True
