"""Image pipeline (WP6, DESIGN §9).

Public surface for the other packages (TASKS §I):

* :func:`reject_active_image` — ``POST /api/words/{id}/report {target:'image'}`` (WP3's word routes, admin reports)
* :func:`image_meta` — ``ImageMeta`` with the template-card fallback (WP3 / WP4; never None)
* :func:`render_card` — the template SVG (media route 53)
* :func:`activate_svg` / :func:`clean_svg` — used by the ``generate_svg`` handler (WP5)
* :func:`request_refresh` (换一张, API.md 29) · :func:`admin_refetch` (API.md 69) · :func:`word_is_studied`
* :func:`retry_if_failed` / :func:`retry_failed_studied` — the failed-image retry rules (PLAN §5.1 C7): the scheduler's
  03:30 maintenance and ``wd images-retry`` call the sweep; the per-word hook is for the bank / batch sites (R-16)
* :func:`photo_mix` (``AdminOverview.words.with_photo/with_claude_svg/card_only``) and ``quota.status`` for the admin overview
"""

from __future__ import annotations

from .card_svg import render, render_card
from .sanitize_svg import SvgRejected
from .sanitize_svg import clean as clean_svg
from .service import (
    RETRY_MAX_AUTO_30D,
    RETRY_MIN_AGE_H,
    RETRY_NIGHTLY_LIMIT,
    RETRY_NIGHTLY_PRIORITY,
    admin_refetch,
    card_meta,
    enqueue_fetch,
    image_meta,
    photo_mix,
    reject_active_image,
    request_refresh,
    retry_failed_studied,
    retry_if_failed,
    word_is_studied,
)
from .store import activate_svg

__all__ = [
    "RETRY_MAX_AUTO_30D",
    "RETRY_MIN_AGE_H",
    "RETRY_NIGHTLY_LIMIT",
    "RETRY_NIGHTLY_PRIORITY",
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
    "retry_failed_studied",
    "retry_if_failed",
    "word_is_studied",
]
