"""Deterministic template card (DESIGN §9 "Template card"): an 800×500 SVG rendered from database data only.

Pastel gradient from ``crc32(lemma)`` (never Python's salted ``hash``), headword (72 px, shrinking for long
phrases), phonetic, the first ``meaning_zh`` / translation line, the first example sentence and a small mark.
Every string is XML-escaped. :func:`render` is pure; :func:`render_card` reads the word (+ active content) and
caches the result in an in-memory LRU keyed by ``(word_id, active_content_id, words.updated_at)``.
"""

from __future__ import annotations

import colorsys
import json
import sqlite3
import threading
import zlib
from collections import OrderedDict
from typing import Any, Mapping
from xml.sax.saxutils import escape, quoteattr

WIDTH, HEIGHT = 800, 500
LRU_SIZE = 2000
FONT_STACK = "'Noto Sans', 'Noto Sans CJK SC', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif"
MARK = "word-Dance"

_cache: "OrderedDict[tuple[int, int | None, str], str]" = OrderedDict()
_cache_lock = threading.Lock()


def _hsl_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def palette(lemma: str) -> tuple[str, str, str, str]:
    """``(gradient_start, gradient_end, ink, accent)`` for a lemma — deterministic across processes."""
    seed = zlib.crc32(lemma.encode("utf-8"))
    h1 = (seed % 360) / 360.0
    h2 = ((seed // 360) % 360) / 360.0 * 0.15 + h1 + 0.06
    start = _hsl_hex(h1, 0.55, 0.88)
    end = _hsl_hex(h2, 0.5, 0.78)
    ink = _hsl_hex(h1, 0.35, 0.22)
    accent = _hsl_hex(h1 + 0.5, 0.45, 0.45)
    return start, end, ink, accent


def _display_width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def fit(text: str, max_units: int) -> str:
    """Truncate ``text`` to ``max_units`` display units (CJK = 2) with an ellipsis."""
    text = " ".join((text or "").split())
    if _display_width(text) <= max_units:
        return text
    out: list[str] = []
    used = 0
    for ch in text:
        w = 2 if ord(ch) > 0x2E7F else 1
        if used + w > max_units - 1:
            break
        out.append(ch)
        used += w
    return "".join(out).rstrip() + "…"


def headword_size(display: str) -> int:
    n = max(1, len(display))
    if n <= 10:
        return 72
    return max(28, int(72 * 10 / n))


def first_line(text: str | None) -> str:
    if not text:
        return ""
    for line in str(text).splitlines():
        if line.strip():
            return line.strip()
    return ""


def render(word: Mapping[str, Any], content: Mapping[str, Any] | None = None) -> str:
    """Pure renderer: ``word`` has ``lemma``, ``display``, ``phonetic``, ``translation``, ``definition``;
    ``content`` (optional) is the active ``Content`` object (``meaning_zh``, ``examples``)."""
    lemma = str(word.get("lemma") or "")
    display = str(word.get("display") or lemma)
    start, end, ink, accent = palette(lemma)
    phonetic = str(word.get("phonetic") or "").strip()
    meaning = ""
    example = ""
    if content:
        meaning = first_line(str(content.get("meaning_zh") or ""))
        examples = content.get("examples") or []
        if examples and isinstance(examples[0], Mapping):
            example = str(examples[0].get("en") or "")
    if not meaning:
        meaning = first_line(word.get("translation")) or first_line(word.get("definition"))
    gid = "g" + format(zlib.crc32(lemma.encode("utf-8")), "08x")
    seed = zlib.crc32(("deco:" + lemma).encode("utf-8"))
    c1x, c1y, c1r = 560 + seed % 200, 60 + (seed // 7) % 120, 90 + (seed // 11) % 70
    c2x, c2y, c2r = 40 + (seed // 13) % 160, 380 + (seed // 17) % 100, 60 + (seed // 19) % 60
    size = headword_size(display)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-label={quoteattr(display)}>',
        "<defs>",
        f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{start}"/><stop offset="1" stop-color="{end}"/></linearGradient>',
        "</defs>",
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#{gid})"/>',
        f'<circle cx="{c1x}" cy="{c1y}" r="{c1r}" fill="#ffffff" fill-opacity="0.35"/>',
        f'<circle cx="{c2x}" cy="{c2y}" r="{c2r}" fill="{accent}" fill-opacity="0.18"/>',
        f'<text x="60" y="{215 if phonetic else 235}" font-family="{FONT_STACK}" font-size="{size}" font-weight="700" fill="{ink}">{escape(fit(display, 36))}</text>',
    ]
    if phonetic:
        lines.append(f'<text x="62" y="262" font-family="{FONT_STACK}" font-size="28" fill="{ink}" fill-opacity="0.75">{escape(fit(phonetic, 48))}</text>')
    if meaning:
        lines.append(f'<text x="60" y="322" font-family="{FONT_STACK}" font-size="30" fill="{ink}">{escape(fit(meaning, 44))}</text>')
    if example:
        lines.append(f'<text x="60" y="388" font-family="{FONT_STACK}" font-size="22" font-style="italic" fill="{ink}" fill-opacity="0.85">{escape(fit(example, 62))}</text>')
    lines.append(f'<text x="{WIDTH - 40}" y="{HEIGHT - 28}" text-anchor="end" font-family="{FONT_STACK}" font-size="16" fill="{ink}" fill-opacity="0.6">{escape(MARK)}</text>')
    lines.append("</svg>")
    return "".join(lines)


def _cache_get(key: tuple[int, int | None, str]) -> str | None:
    with _cache_lock:
        svg = _cache.get(key)
        if svg is not None:
            _cache.move_to_end(key)
        return svg


def _cache_put(key: tuple[int, int | None, str], svg: str) -> None:
    with _cache_lock:
        _cache[key] = svg
        _cache.move_to_end(key)
        while len(_cache) > LRU_SIZE:
            _cache.popitem(last=False)


def cache_clear() -> None:
    with _cache_lock:
        _cache.clear()


def cache_size() -> int:
    with _cache_lock:
        return len(_cache)


def render_card(conn: sqlite3.Connection, word_id: int) -> str:
    """The template card for ``word_id`` from the database (LRU-cached); raises ``LookupError`` for an unknown word."""
    row = conn.execute(
        "SELECT id, lemma, display, phonetic, translation, definition, active_content_id, updated_at FROM words WHERE id = ?",
        (int(word_id),),
    ).fetchone()
    if row is None:
        raise LookupError(f"word {word_id} does not exist")
    key = (int(row["id"]), row["active_content_id"], str(row["updated_at"] or ""))
    cached = _cache_get(key)
    if cached is not None:
        return cached
    content: dict[str, Any] | None = None
    if row["active_content_id"] is not None:
        crow = conn.execute("SELECT content_json FROM word_contents WHERE id = ? AND status = 'active'", (row["active_content_id"],)).fetchone()
        if crow is not None:
            try:
                parsed = json.loads(crow["content_json"])
                content = parsed if isinstance(parsed, dict) else None
            except (TypeError, ValueError):
                content = None
    svg = render({k: row[k] for k in row.keys()}, content)
    _cache_put(key, svg)
    return svg
