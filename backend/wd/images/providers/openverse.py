"""Openverse search (DESIGN §9, secondary provider).

``GET https://api.openverse.org/v1/images/?q=<kw>&page_size=<limit ≤ 20>&license_type=commercial&mature=false`` — the
handler asks for 10 and only ever looks at 10, so the page is 10 (PLAN §5.1 C8; it used to fetch 20). The ``kid`` style
(illustration-first round) adds ``category=illustration``; the ``neutral`` round adds **no** ``category=photograph``,
which would drop every uncategorised result and narrow the default chain. Anonymous limits are 20/min and 200/day;
``quota.py`` enforces ``WD_OPENVERSE_MINUTE_LIMIT=15`` / ``WD_OPENVERSE_DAILY_LIMIT=160``. Only ``url`` (the full image
on the source host) is downloaded — **never** the ``thumbnail`` on ``api.openverse.org``, which would spend API quota.
An optional registered app (``WD_OPENVERSE_CLIENT_ID/SECRET``) sends a client-credentials bearer token; failures fall
back to anonymous.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import httpx

from ...config import Settings
from ...interfaces import Candidate
from . import base

log = logging.getLogger("wd.images.openverse")

API_URL = "https://api.openverse.org/v1/images/"
TOKEN_URL = "https://api.openverse.org/v1/auth_tokens/token/"
API_HOST = "api.openverse.org"
MAX_PAGE_SIZE = 20  # the anonymous API maximum
KID_CATEGORY = "illustration"

_token_lock = threading.Lock()
_token_cache: dict[str, object] = {"token": None, "expires_at": 0.0, "client_id": None}


class OpenverseProvider:
    name = "openverse"

    def __init__(self, cfg: Settings, *, client_factory: Callable[[], httpx.Client] | None = None):
        self.cfg = cfg
        self._client_factory = client_factory or (lambda: base.make_client(cfg))

    def params(self, query: str, limit: int, *, style: str = "neutral") -> dict[str, object]:
        params: dict[str, object] = {"q": query, "page_size": max(1, min(int(limit), MAX_PAGE_SIZE)), "license_type": "commercial", "mature": "false"}
        if style == "kid":
            params["category"] = KID_CATEGORY
        return params

    def _bearer(self, client: httpx.Client) -> str | None:
        """Client-credentials token when a registered app is configured (cached until it expires); None → anonymous."""
        cid, secret = self.cfg.openverse_client_id, self.cfg.openverse_client_secret
        if not cid or not secret:
            return None
        with _token_lock:
            if _token_cache["token"] and _token_cache["client_id"] == cid and float(_token_cache["expires_at"]) > time.monotonic() + 30:
                return str(_token_cache["token"])
            try:
                response = client.post(TOKEN_URL, data={"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
                if response.status_code >= 400:
                    raise ValueError(f"HTTP {response.status_code}")
                payload = response.json()
                token = str(payload["access_token"])
                expires_in = float(payload.get("expires_in") or 3600)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                log.warning("openverse token request failed; continuing anonymously: %s", e, extra={"provider": "openverse"})
                return None
            _token_cache.update({"token": token, "expires_at": time.monotonic() + expires_in, "client_id": cid})
            return token

    def search(self, query: str, limit: int, *, style: str = "neutral") -> list[Candidate]:
        with self._client_factory() as client:
            headers = base.request_headers(self.cfg)
            token = self._bearer(client)
            if token:
                headers["Authorization"] = f"Bearer {token}"
            data = base.get_json(client, self.name, API_URL, params=self.params(query, limit, style=style), headers=headers)
        return parse_search(data)[: max(1, int(limit))]


def parse_search(data: dict) -> list[Candidate]:
    """``results[]`` → candidates (relevance order); entries without a downloadable source URL are skipped."""
    out: list[Candidate] = []
    seen: set[str] = set()
    for r in data.get("results") or []:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url") or "")
        if not url.startswith("https://"):
            continue
        try:
            host = httpx.URL(url).host.lower()
        except httpx.InvalidURL:
            continue  # a URL httpx cannot build a request for (C0/DEL byte, bad port) — one result, not the whole search
        if host == API_HOST:
            continue  # never download through the API host (thumbnails spend quota)
        ref = str(r.get("id") or "")
        if not ref or ref in seen or url in seen:
            continue
        seen.add(ref)
        seen.add(url)
        tags = [str(t.get("name")).lower() for t in (r.get("tags") or []) if isinstance(t, dict) and t.get("name")]
        width, height = r.get("width"), r.get("height")
        out.append(
            Candidate(
                provider="openverse",
                ref=ref,
                title=base.clean_text(r.get("title"), 200),
                creator=base.clean_text(r.get("creator"), 200) or None,
                creator_url=(str(r["creator_url"]) if r.get("creator_url") else None),
                license=base.openverse_license_name(r.get("license"), r.get("license_version")),
                license_url=(str(r["license_url"]) if r.get("license_url") else None),
                landing_url=str(r.get("foreign_landing_url") or r.get("detail_url") or ""),
                image_url=url,
                width=int(width) if isinstance(width, (int, float)) else None,
                height=int(height) if isinstance(height, (int, float)) else None,
                mime=base.mime_from_filetype(r.get("filetype")) or base.mime_from_url(url),
                tags=tags,
                mature=bool(r.get("mature")),
                extra={
                    "attribution": base.clean_text(r.get("attribution"), 400) or None,
                    "sensitivity": list(r.get("unstable__sensitivity") or []),
                    "source": r.get("source"),
                    "license_code": r.get("license"),
                    "category": (str(r["category"]).strip().lower() or None) if isinstance(r.get("category"), str) else None,  # photograph / illustration / digitized_artwork (select.score)
                },
            )
        )
    return out
