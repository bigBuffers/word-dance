"""Media routes (API.md endpoints 52–53, WP6).

* ``GET /media/images/{path}`` — a cached photo or sanitised SVG; ``path`` must match
  ``^[0-9a-f]{2}/[0-9a-f]{64}\\.(jpg|svg)$`` (anything else, incl. traversal attempts, is 404);
  ``Cache-Control: private, max-age=31536000, immutable``, ``nosniff``, and for SVG
  ``Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'``. Session cookie required.
* ``GET /media/card/{word_id}.svg`` — the deterministic template card (LRU-cached), ``private, max-age=86400``,
  same SVG headers; 404 ``word_not_found`` outside the API.md §1 visibility rule.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse

from ..deps import current_user, get_db, visible_word_sql
from ..errors import ApiError
from ..images import render_card

router = APIRouter()

IMAGE_PATH_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{64}\.(jpg|svg)$")
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"
IMMUTABLE_CACHE = "private, max-age=31536000, immutable"
CARD_CACHE = "private, max-age=86400"
SVG_MIME = "image/svg+xml"
JPEG_MIME = "image/jpeg"


def svg_headers(cache: str) -> dict[str, str]:
    return {"Cache-Control": cache, "X-Content-Type-Options": "nosniff", "Content-Security-Policy": SVG_CSP}


@router.get("/media/images/{path:path}", include_in_schema=False)
def media_image(path: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    if not IMAGE_PATH_RE.match(path):
        raise ApiError("not_found")  # shape first: a malformed/traversal path is 404 whoever asks (API.md 52)
    current_user(request, conn)  # then the session cookie (401 unauthorized)
    file = request.app.state.settings.images_dir / path
    if not file.is_file():
        raise ApiError("not_found")
    if path.endswith(".svg"):
        return FileResponse(file, media_type=SVG_MIME, headers=svg_headers(IMMUTABLE_CACHE))
    return FileResponse(file, media_type=JPEG_MIME, headers={"Cache-Control": IMMUTABLE_CACHE, "X-Content-Type-Options": "nosniff"})


@router.get("/media/card/{word_id:int}.svg", include_in_schema=False)
def media_card(word_id: int, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute(f"SELECT id FROM words WHERE id = :id AND ({visible_word_sql(user)})", {"id": word_id, "me": user["id"]}).fetchone()
    if row is None:
        raise ApiError("word_not_found")
    svg = render_card(conn, word_id)
    return Response(content=svg, media_type=SVG_MIME, headers=svg_headers(CARD_CACHE))
