"""Pexels (optional keyed provider, ``WD_PEXELS_KEY``).

``GET https://api.pexels.com/v1/search?query=<kw>&per_page=<n>&orientation=landscape`` with ``Authorization: <key>``.
``src.large`` (940 px) is downloaded and re-encoded to ≤ 800 px. Licence: the Pexels License. Pexels has no
illustration filter, so ``search`` accepts the ``style`` keyword of ``interfaces.ImageProvider`` and ignores it; the
handler keeps Pexels out of the ``kid`` round altogether (PLAN §5.1 C8).
"""

from __future__ import annotations

from typing import Callable

import httpx

from ...config import Settings
from ...interfaces import Candidate, ProviderError
from . import base

API_URL = "https://api.pexels.com/v1/search"
LICENSE_NAME = "Pexels License"
LICENSE_URL = "https://www.pexels.com/license/"


class PexelsProvider:
    name = "pexels"

    def __init__(self, cfg: Settings, *, client_factory: Callable[[], httpx.Client] | None = None):
        self.cfg = cfg
        self._client_factory = client_factory or (lambda: base.make_client(cfg))

    def params(self, query: str, limit: int) -> dict[str, object]:
        return {"query": query, "per_page": max(1, min(int(limit), 80)), "orientation": "landscape"}

    def search(self, query: str, limit: int, *, style: str = "neutral") -> list[Candidate]:
        if not self.cfg.pexels_key:
            raise ProviderError("pexels: WD_PEXELS_KEY is not configured")
        with self._client_factory() as client:
            data = base.get_json(client, self.name, API_URL, params=self.params(query, limit), headers=base.request_headers(self.cfg, {"Authorization": self.cfg.pexels_key}))
        return parse_search(data)


def parse_search(data: dict) -> list[Candidate]:
    out: list[Candidate] = []
    for photo in data.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        src = photo.get("src") or {}
        image_url = str((src.get("large") if isinstance(src, dict) else None) or (src.get("original") if isinstance(src, dict) else None) or "")
        if not image_url.startswith("https://"):
            continue
        width, height = photo.get("width"), photo.get("height")
        out.append(
            Candidate(
                provider="pexels",
                ref=str(photo.get("id")),
                title=base.clean_text(photo.get("alt"), 200),
                creator=base.clean_text(photo.get("photographer"), 100) or None,
                creator_url=(str(photo["photographer_url"]) if photo.get("photographer_url") else None),
                license=LICENSE_NAME,
                license_url=LICENSE_URL,
                landing_url=str(photo.get("url") or ""),
                image_url=image_url,
                width=int(width) if isinstance(width, (int, float)) else None,
                height=int(height) if isinstance(height, (int, float)) else None,
                mime="image/jpeg",
                tags=[],
                mature=False,
                extra={"avg_color": photo.get("avg_color")},
            )
        )
    return out
