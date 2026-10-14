"""Pixabay (optional keyed provider, ``WD_PIXABAY_KEY``).

``GET https://pixabay.com/api/?key=…&q=<kw>&image_type=photo&safesearch=true&per_page=<n>&min_width=400``.
Hits carry ``largeImageURL`` (1280 px) which is downloaded and re-encoded to ≤ 800 px like every photo.
Licence: the Pixabay Content License (attribution not required, shown anyway).
"""

from __future__ import annotations

from typing import Callable

import httpx

from ...config import Settings
from ...interfaces import Candidate, ProviderError
from . import base

API_URL = "https://pixabay.com/api/"
LICENSE_NAME = "Pixabay License"
LICENSE_URL = "https://pixabay.com/service/license-summary/"


class PixabayProvider:
    name = "pixabay"

    def __init__(self, cfg: Settings, *, client_factory: Callable[[], httpx.Client] | None = None):
        self.cfg = cfg
        self._client_factory = client_factory or (lambda: base.make_client(cfg))

    def params(self, query: str, limit: int) -> dict[str, object]:
        return {
            "key": self.cfg.pixabay_key,
            "q": query,
            "image_type": "photo",
            "safesearch": "true",
            "per_page": max(3, min(int(limit), 200)),  # the API accepts 3–200
            "min_width": 400,
            "lang": "en",
        }

    def search(self, query: str, limit: int) -> list[Candidate]:
        if not self.cfg.pixabay_key:
            raise ProviderError("pixabay: WD_PIXABAY_KEY is not configured")
        with self._client_factory() as client:
            data = base.get_json(client, self.name, API_URL, params=self.params(query, limit), headers=base.request_headers(self.cfg))
        return parse_search(data)


def parse_search(data: dict) -> list[Candidate]:
    out: list[Candidate] = []
    for hit in data.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        image_url = str(hit.get("largeImageURL") or hit.get("webformatURL") or "")
        if not image_url.startswith("https://"):
            continue
        tag_text = str(hit.get("tags") or "")
        tags = [t.strip().lower() for t in tag_text.split(",") if t.strip()]
        user = base.clean_text(hit.get("user"), 100)
        user_id = hit.get("user_id")
        width, height = hit.get("imageWidth"), hit.get("imageHeight")
        out.append(
            Candidate(
                provider="pixabay",
                ref=str(hit.get("id")),
                title=(tags[0].capitalize() if tags else ""),
                creator=user or None,
                creator_url=(f"https://pixabay.com/users/{user}-{user_id}/" if user and user_id is not None else None),
                license=LICENSE_NAME,
                license_url=LICENSE_URL,
                landing_url=str(hit.get("pageURL") or ""),
                image_url=image_url,
                width=int(width) if isinstance(width, (int, float)) else None,
                height=int(height) if isinstance(height, (int, float)) else None,
                mime=base.mime_from_url(image_url) or "image/jpeg",
                tags=tags,
                mature=False,
                extra={"type": hit.get("type")},
            )
        )
    return out
