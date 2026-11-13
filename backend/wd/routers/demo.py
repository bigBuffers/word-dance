"""The read-only demo of the login page — API.md endpoints 77–78 (docs/AUTH_SIGNUP_DESIGN.md D9, slice 1-A).

* ``GET /api/demo`` (public): :data:`DEMO_LEMMAS` resolved by lemma and kept only while public, validated and unmerged (the guest
  predicate of ``deps.visible_word_sql(None)`` plus the validity rule); a missing lemma is skipped, never a 500. Each item is the
  ``WordBrief`` (``my_state`` null — no ``user_words`` lookup), the active ``Content``, a card-shaped ``ImageMeta`` whose URL is the
  public route below (``kind`` / ``provider`` ``svg`` / ``claude_svg`` when the active image is a Claude SVG, else ``card`` /
  ``card_svg``) and the ``DanceSpec`` of ``wd.dance.spec_for_word``. No writes, no enqueues, no throttle rows.
* ``GET /media/demo/{word_id}.svg`` (public): the demo word's active Claude SVG file, else the template card (``render_card``), with
  ``Cache-Control: public, max-age=86400`` and the SVG headers of the ``/media`` routes; 404 ``not_found`` for any id outside the
  demo set — the route must never become a session-less card renderer for the whole vocabulary.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse

from .. import dance
from ..deps import get_db
from ..errors import ApiError
from ..images import card_meta, render_card
from ..images.service import active_image_row
from ..schemas import DemoResponse
from ..services import words
from .media import SVG_MIME, svg_headers

log = logging.getLogger("wd.routers.demo")

router = APIRouter()

DEMO_LEMMAS: tuple[str, ...] = ("up", "jump", "cold")  # the canonical dance examples (docs/WORD_DANCE_DESIGN.md): rise, hop, shiver
DEMO_CACHE = "public, max-age=86400"  # the words are public and allow-listed, so a proxy may cache the card


def demo_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The demo words that exist and are public, validated and unmerged, in :data:`DEMO_LEMMAS` order."""
    rows: list[dict[str, Any]] = []
    for lemma in DEMO_LEMMAS:
        row = words.word_by_lemma(conn, lemma)
        if row is None:
            continue
        if int(row.get("is_public") or 0) != 1 or int(row.get("is_valid_english") or 0) != 1 or row.get("merged_into_word_id") is not None:
            continue
        rows.append(row)
    return rows


def _active_svg(conn: sqlite3.Connection, request: Request, word_id: int) -> tuple[sqlite3.Row, Any] | None:
    """The word's active Claude SVG row and its file when both exist (a photo or a missing file falls back to the card)."""
    row = active_image_row(conn, word_id)
    if row is None or str(row["provider"]) != "claude_svg" or str(row["mime"]) != SVG_MIME:
        return None
    file = request.app.state.settings.images_dir / str(row["file_path"])
    if not file.is_file():
        return None
    return row, file


def demo_image_meta(conn: sqlite3.Connection, request: Request, row: dict[str, Any]) -> dict[str, Any]:
    """API.md 77: ``ImageMeta`` pointing at the public demo route; ``svg`` / ``claude_svg`` for an active Claude SVG, else the card.
    ``word_layer`` / ``hook_zh`` / ``note_zh`` stay the card's ``false`` / ``null`` / ``null`` even when that SVG is a 记忆图卡: the
    demo route has no ``?plain=1`` (a guest has no ``image_word`` setting to switch off) and the demo card shows no 记忆 section."""
    word_id = int(row["id"])
    meta = card_meta(word_id)
    meta["url"] = f"/media/demo/{word_id}.svg"
    active = _active_svg(conn, request, word_id)
    if active is not None:
        image, _file = active
        meta.update({"id": int(image["id"]), "kind": "svg", "provider": "claude_svg", "width": image["width"], "height": image["height"], "alt_zh": image["alt_zh"]})
    return meta


@router.get("/api/demo", response_model=DemoResponse)
def demo(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    items = []
    for row in demo_rows(conn):
        items.append(
            {
                "word": words.word_brief(conn, {**row, "my_state": None}, 0),
                "content": words.active_content(conn, row),
                "image": demo_image_meta(conn, request, row),
                "dance": dance.spec_for_word(conn, row),
            }
        )
    return {"items": items}


@router.get("/media/demo/{word_id:int}.svg", include_in_schema=False)
def demo_card(word_id: int, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    if word_id not in {int(r["id"]) for r in demo_rows(conn)}:
        raise ApiError("not_found")
    active = _active_svg(conn, request, word_id)
    if active is not None:
        _row, file = active
        return FileResponse(file, media_type=SVG_MIME, headers=svg_headers(DEMO_CACHE))
    try:
        svg = render_card(conn, word_id)
    except LookupError as e:  # the row vanished between the two queries
        raise ApiError("not_found") from e
    return Response(content=svg, media_type=SVG_MIME, headers=svg_headers(DEMO_CACHE))
