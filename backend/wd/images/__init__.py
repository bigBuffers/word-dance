"""Image pipeline (WP6, DESIGN §9).

Public surface for the other packages (TASKS §I):

* :func:`reject_active_image` — ``POST /api/words/{id}/report {target:'image'}`` (WP3's word routes, admin reports)
* :func:`image_meta` — ``ImageMeta`` with the template-card fallback (WP3 / WP4; never None)
* :func:`render_card` — the template SVG (media route 53)
* :func:`activate_svg` / :func:`clean_svg` — used by the ``generate_svg`` handler (WP5)
* :func:`request_refresh` (换一张, API.md 29) · :func:`admin_refetch` (API.md 69) · :func:`word_is_studied`
* :func:`photo_mix` (``AdminOverview.words.with_photo/with_claude_svg/card_only``) and ``quota.status`` for the admin overview
"""

from __future__ import annotations

from .card_svg import render, render_card
from .sanitize_svg import SvgRejected
from .sanitize_svg import clean as clean_svg
from .service import admin_refetch, card_meta, enqueue_fetch, image_meta, photo_mix, reject_active_image, request_refresh, word_is_studied
from .store import activate_svg

__all__ = [
    "SvgRejected",
    "activate_svg",
    "admin_refetch",
    "card_meta",
    "clean_svg",
    "enqueue_fetch",
    "image_meta",
    "photo_mix",
    "reject_active_image",
    "render",
    "render_card",
    "request_refresh",
    "word_is_studied",
]
