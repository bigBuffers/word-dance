"""Wikimedia Commons search (DESIGN §9, primary provider).

Request (verbatim, **no** ``formatversion=2``)::

    action=query&generator=search&gsrsearch=<kw> filetype:bitmap&gsrnamespace=6&gsrlimit=10
    &prop=imageinfo&iiprop=url|extmetadata|size|mime&iiurlwidth=800&format=json

The response is the legacy shape the verified fixture ``tests/fixtures/wikimedia_search.json`` has: ``query.pages``
is an object keyed by pageid, each page carrying ``imageinfo[0].{thumburl, thumbwidth, thumbheight, url,
descriptionurl, extmetadata}``. Only ``thumburl`` (≤ 800 px, served from ``thumb.wikimedia.org``) is ever
downloaded, never the original ``url``; every ``utm_*`` parameter is stripped before a URL is stored, excluded or
compared. Politeness: ≤ 1 request/s process-wide (:class:`RateGate`), 429/503 → cooldown (``quota.py``).
"""

from __future__ import annotations

import re
from typing import Callable

import httpx

from ...config import Settings
from ...interfaces import Candidate
from . import base

API_URL = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH = 800
_FILE_PREFIX_RE = re.compile(r"^File:", re.I)
_EXT_RE = re.compile(r"\.[A-Za-z0-9]{2,5}$")


class WikimediaProvider:
    name = "wikimedia"

    def __init__(self, cfg: Settings, *, client_factory: Callable[[], httpx.Client] | None = None, gate: base.RateGate | None = None):
        self.cfg = cfg
        self._client_factory = client_factory or (lambda: base.make_client(cfg))
        self._gate = gate or base.gate_for("wikimedia", cfg.wikimedia_min_interval_ms / 1000.0)

    def params(self, query: str, limit: int) -> dict[str, object]:
        return {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": 6,
            "gsrlimit": max(1, min(int(limit), 50)),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": THUMB_WIDTH,
            "format": "json",
        }

    def search(self, query: str, limit: int) -> list[Candidate]:
        self._gate.wait()
        with self._client_factory() as client:
            data = base.get_json(client, self.name, API_URL, params=self.params(query, limit), headers=base.request_headers(self.cfg))
        return parse_search(data)


def _meta(ext: dict, key: str) -> str:
    v = ext.get(key)
    if isinstance(v, dict):
        value = v.get("value")
        return "" if value is None else str(value)
    return "" if v is None else str(v)


def parse_search(data: dict) -> list[Candidate]:
    """Legacy ``query.pages`` object (or a ``formatversion=2`` list, tolerated) → candidates in search order, de-duplicated by image URL."""
    query = data.get("query") or {}
    pages = query.get("pages") or {}
    page_list = list(pages.values()) if isinstance(pages, dict) else list(pages) if isinstance(pages, list) else []
    page_list.sort(key=lambda p: (int(p.get("index", 0) or 0), int(p.get("pageid", 0) or 0)))
    out: list[Candidate] = []
    seen_urls: set[str] = set()
    for page in page_list:
        if not isinstance(page, dict):
            continue
        infos = page.get("imageinfo") or []
        info = infos[0] if infos and isinstance(infos[0], dict) else None
        if not info or not info.get("thumburl"):
            continue
        image_url = base.strip_utm(str(info["thumburl"]))
        if image_url in seen_urls:
            continue
        seen_urls.add(image_url)
        ext = info.get("extmetadata") or {}
        if not isinstance(ext, dict):
            ext = {}
        raw_title = str(page.get("title") or "")
        title = _EXT_RE.sub("", _FILE_PREFIX_RE.sub("", raw_title)).replace("_", " ").strip()
        artist_html = _meta(ext, "Artist")
        creator = base.html_to_text(artist_html) or None
        license_name = _meta(ext, "LicenseShortName") or _meta(ext, "UsageTerms") or _meta(ext, "License")
        categories = [c.strip() for c in _meta(ext, "Categories").split("|") if c.strip()]
        original_url = base.strip_utm(str(info.get("url") or ""))
        mime = info.get("mime") or base.mime_from_url(original_url or image_url)
        width = info.get("width") or info.get("thumbwidth")
        height = info.get("height") or info.get("thumbheight")
        pageid = page.get("pageid")
        out.append(
            Candidate(
                provider="wikimedia",
                ref=str(pageid),
                title=title,
                creator=creator,
                creator_url=base.first_href(artist_html),
                license=license_name.strip(),
                license_url=(_meta(ext, "LicenseUrl") or None),
                landing_url=str(info.get("descriptionurl") or f"https://commons.wikimedia.org/?curid={pageid}"),
                image_url=image_url,
                width=int(width) if isinstance(width, (int, float)) else None,
                height=int(height) if isinstance(height, (int, float)) else None,
                mime=str(mime) if mime else None,
                tags=[c.lower() for c in categories],
                mature=False,
                extra={
                    "assessments": _meta(ext, "Assessments"),
                    "restrictions": _meta(ext, "Restrictions").strip(),
                    "description": base.html_to_text(_meta(ext, "ImageDescription"))[:300],
                    "object_name": _meta(ext, "ObjectName"),
                    "original_url": original_url,
                    "thumb_width": info.get("thumbwidth"),
                    "thumb_height": info.get("thumbheight"),
                    "credit": base.html_to_text(_meta(ext, "Credit"))[:200],
                },
            )
        )
    return out
