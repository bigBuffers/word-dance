"""Image search providers (DESIGN §9): Wikimedia Commons (primary), Openverse (secondary), keyed Pixabay / Pexels.

Each provider implements :class:`wd.interfaces.ImageProvider` (``name`` + ``search(query, limit)``) and raises
:class:`wd.interfaces.ProviderError` (status, retry_after_s) on HTTP / network failure. :func:`build_chain` turns
the ordered ``WD_IMAGE_PROVIDERS`` list into instances, skipping keyed providers whose key is missing.
"""

from __future__ import annotations

from typing import Callable, Sequence

import httpx

from ...config import Settings
from ...interfaces import ImageProvider
from .openverse import OpenverseProvider
from .pexels import PexelsProvider
from .pixabay import PixabayProvider
from .wikimedia import WikimediaProvider

PROVIDER_CLASSES: dict[str, type] = {
    "wikimedia": WikimediaProvider,
    "openverse": OpenverseProvider,
    "pixabay": PixabayProvider,
    "pexels": PexelsProvider,
}

PHOTO_PROVIDERS: tuple[str, ...] = tuple(PROVIDER_CLASSES)


def is_keyed(name: str, cfg: Settings) -> bool:
    """True when a provider needs an API key that is configured (Pixabay / Pexels)."""
    if name == "pixabay":
        return bool(cfg.pixabay_key)
    if name == "pexels":
        return bool(cfg.pexels_key)
    return True


def build_chain(
    cfg: Settings,
    names: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> list[ImageProvider]:
    """Instantiate the provider chain in order (default ``cfg.image_providers``).

    Unknown names raise ``ValueError``; a keyed provider without its key is skipped (DEPLOY §4: keyed providers are
    only appended to the chain when keys exist, but an explicit ``provider`` payload may still name one).
    """
    chain: list[ImageProvider] = []
    for name in names or cfg.image_providers:
        cls = PROVIDER_CLASSES.get(name)
        if cls is None:
            raise ValueError(f"unknown image provider {name!r}")
        if not is_keyed(name, cfg):
            continue
        chain.append(cls(cfg, client_factory=client_factory))
    return chain


__all__ = [
    "PROVIDER_CLASSES",
    "PHOTO_PROVIDERS",
    "build_chain",
    "is_keyed",
    "WikimediaProvider",
    "OpenverseProvider",
    "PixabayProvider",
    "PexelsProvider",
]
