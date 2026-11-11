"""``GET /media/audio`` — API.md endpoint 76: one pronunciation clip (``wd.audio``). Under ``/media/`` like the other cached
files: the ``/api/*`` middleware stamps ``Cache-Control: no-store`` on every API answer, and a clip must be cacheable.

Query ``text`` (≤ 300 chars: Latin letters, digits, the punctuation of an English sentence — ``wd.audio.TEXT_RE``) and
``accent`` (``en-US`` default | ``en-GB``). Session cookie required — any logged-in user, the 推荐词 of the welcome screening
speak too. A cache hit costs nothing; a miss counts against ``audio:user:<id>`` (``SYNTH_PER_MINUTE``) and synthesises through
the configured provider — except under the read-only ``cache`` provider, where a miss is 503 ``missing`` at once (event
``audio_clip_missing`` at INFO, nothing to protect). Answers ``audio/mp4`` (``say``) or ``audio/mpeg`` (``youdao``, ``bailian``) with ``Cache-Control: private,
max-age=604800`` (the clip for a text changes only when the operator switches provider or voice; a week bounds how long a
browser keeps the old one), ``Accept-Ranges`` (the client plays the URL in an ``<audio>`` element) and ``nosniff``; 400
``validation_error`` (``details.fields.text`` / ``.accent``); 503 ``audio_unavailable`` ``{reason: "off" | "busy" | "failed" | "missing"}``
— ``off`` tells the client to stop asking for the rest of its session, ``missing`` (the read-only ``cache`` provider has no clip for
this text) to use its own voice for this one. The learner's text is logged at DEBUG only (DESIGN §10).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from .. import audio, security
from ..deps import current_user, get_db
from ..errors import ApiError

log = logging.getLogger("wd.routers.audio")

router = APIRouter()

SYNTH_PER_MINUTE = 60  # cache misses per user and minute: a study session plays a few new words a minute, a scraper hundreds
CACHE_CONTROL = "private, max-age=604800"


@router.get("/media/audio", include_in_schema=False)
def pronunciation(
    request: Request,
    text: str = Query(..., min_length=1, max_length=400),
    accent: str = Query("en-US"),
    user: dict[str, Any] = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    cfg = request.app.state.settings
    if accent not in audio.ACCENTS:
        raise ApiError("validation_error", details={"fields": {"accent": "只支持 en-US 或 en-GB"}})
    spoken = audio.normalize_text(text)
    if spoken is None:
        raise ApiError("validation_error", details={"fields": {"text": f"1–{audio.MAX_TEXT_CHARS} 个英文字母、数字或常见标点"}})
    if audio.provider_for(cfg) == "off":
        raise ApiError("audio_unavailable", details={"reason": "off"})
    try:
        clip = audio.lookup(cfg, accent, spoken)
        if clip is None:
            if audio.provider_for(cfg) != "cache":  # a read-only mirror synthesises nothing: no budget to protect, `missing` follows
                security.rate_limit(conn, f"audio:user:{user['id']}", limit=SYNTH_PER_MINUTE, window_s=60, now=request.app.state.clock.now_utc())
            clip = audio.synthesize(cfg, accent, spoken)
    except audio.AudioError as e:
        if e.reason == "missing":  # not a fault: the mirror has not been synced since this text appeared (ops.md §5)
            log.info("no mirrored clip for a %d-char %s text", len(spoken), accent, extra={"event": "audio_clip_missing"})
        else:
            log.warning("pronunciation unavailable (%s) for a %d-char %s text: %s", e.reason, len(spoken), accent, e.detail or "-", extra={"event": "audio_unavailable"})
        log.debug("pronunciation unavailable for %r", spoken)
        raise ApiError("audio_unavailable", details={"reason": e.reason}) from None
    return FileResponse(clip.path, media_type=clip.media_type, headers={"Cache-Control": CACHE_CONTROL, "X-Content-Type-Options": "nosniff"})
