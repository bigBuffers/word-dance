"""Self-hosted image captcha in front of the public verification-code sends (API.md 79 / 80 / 90; docs/AUTH_SIGNUP_DESIGN.md §5.3).

The CSP is ``script-src 'self'`` (no third-party widget) and ``img-src 'self' data:``, so the challenge is a PNG ``data:`` URI of
four digits drawn with Pillow's bundled font (``ImageFont.load_default(size=…)`` — no font files), lightly rotated per glyph over
noise lines and dots. The challenge is stateless: ``id = token_urlsafe(12)``, ``exp`` = unix seconds now + :data:`TTL_S`,
``sig = hex HMAC-SHA256(WD_SECRET_KEY, "<id>:<exp>:<answer>")`` — the client returns ``id`` / ``exp`` / ``sig`` with the digits
it read and :func:`verify` recomputes the HMAC. Single use is enforced through ``auth_throttle`` (``captcha:<id>``, limit 1 per
:data:`REUSE_WINDOW_S`) and the use is claimed BEFORE the answer is compared, so a wrong guess also burns the challenge — four digits
could otherwise be brute-forced within the two minutes. ``WD_CAPTCHA=off`` (the test env) skips the gate at the endpoints, not here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import sqlite3
from datetime import datetime
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

from .errors import ApiError

TTL_S = 120  # CaptchaChallenge.expires_in_s
REUSE_WINDOW_S = 180  # the single-use throttle outlives the TTL, so an expired-then-replayed token is refused either way
DIGITS = 4
WIDTH, HEIGHT = 160, 56
FONT_SIZE = 36
NOISE_LINES = 5
NOISE_DOTS = 90
MAX_ROTATION_DEG = 18
BACKGROUND = (247, 246, 241)
INK = ((42, 54, 92), (74, 48, 96), (36, 88, 70), (116, 54, 42))
_ALPHABET = "0123456789"


def signature(secret_key: str, challenge_id: str, exp: int, answer: str) -> str:
    """hex HMAC-SHA256(WD_SECRET_KEY, ``id:exp:answer``) — what ``CaptchaChallenge.sig`` carries."""
    return hmac.new(secret_key.encode("utf-8"), f"{challenge_id}:{int(exp)}:{answer}".encode("utf-8"), hashlib.sha256).hexdigest()


def _font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=FONT_SIZE)  # Pillow ≥ 10.1 scales its bundled font
    except TypeError:  # pragma: no cover - an older Pillow: the fixed bitmap font
        return ImageFont.load_default()


def render_png(answer: str, rng: secrets.SystemRandom | None = None) -> bytes:
    """The challenge picture: ``answer`` glyph by glyph, each rotated a little, over noise lines and dots."""
    r = rng or secrets.SystemRandom()
    img = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(img)
    for _ in range(NOISE_LINES):
        colour = r.choice(INK)
        draw.line([(r.randint(0, WIDTH), r.randint(0, HEIGHT)), (r.randint(0, WIDTH), r.randint(0, HEIGHT))], fill=colour, width=1)
    font = _font()
    slot = WIDTH // (len(answer) + 1)
    for i, ch in enumerate(answer):
        glyph = Image.new("RGBA", (slot + 12, HEIGHT), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glyph)
        gd.text((6, (HEIGHT - FONT_SIZE) // 2 - 4), ch, font=font, fill=r.choice(INK))
        glyph = glyph.rotate(r.uniform(-MAX_ROTATION_DEG, MAX_ROTATION_DEG), resample=Image.BICUBIC, expand=False)
        img.paste(glyph, (slot // 2 + i * slot + r.randint(-4, 4), r.randint(-3, 3)), glyph)
    for _ in range(NOISE_DOTS):
        draw.point((r.randint(0, WIDTH - 1), r.randint(0, HEIGHT - 1)), fill=r.choice(INK))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def new_challenge(secret_key: str, now: datetime) -> tuple[dict[str, Any], str]:
    """``(CaptchaChallenge payload, answer)`` — the payload is API.md §9 ``CaptchaChallenge`` (``image`` a PNG ``data:`` URI);
    the answer is returned for tests and never leaves the server otherwise."""
    answer = "".join(secrets.choice(_ALPHABET) for _ in range(DIGITS))
    challenge_id = secrets.token_urlsafe(12)
    exp = int(now.timestamp()) + TTL_S
    payload = {
        "id": challenge_id,
        "image": "data:image/png;base64," + base64.b64encode(render_png(answer)).decode("ascii"),
        "exp": exp,
        "sig": signature(secret_key, challenge_id, exp, answer),
        "expires_in_s": TTL_S,
    }
    return payload, answer


def _field(token: Any, name: str) -> Any:
    if isinstance(token, Mapping):
        return token.get(name)
    return getattr(token, name, None)


def verify(conn: sqlite3.Connection, secret_key: str, token: Any, now: datetime) -> None:
    """Accept a ``CaptchaToken`` (a mapping or a model with ``id`` / ``exp`` / ``sig`` / ``answer``) once, or raise 400 ``invalid_captcha``.

    Order: the challenge must be unexpired, then its single use is claimed on ``auth_throttle`` (``captcha:<id>``), then the
    signature over the submitted answer is compared in constant time — so a wrong answer spends the challenge too.
    """
    from . import security  # security imports deps; keep this module import-light for the routers

    try:
        challenge_id = str(_field(token, "id") or "")
        exp = int(_field(token, "exp") or 0)
        sig = str(_field(token, "sig") or "")
        answer = "".join(str(_field(token, "answer") or "").split())
    except (TypeError, ValueError):
        raise ApiError("invalid_captcha") from None
    if not challenge_id or not sig or exp <= int(now.timestamp()) or exp > int(now.timestamp()) + TTL_S + 60:
        raise ApiError("invalid_captcha")
    if security.throttle_hit(conn, f"captcha:{challenge_id}", limit=1, window_s=REUSE_WINDOW_S, now=now) is not None:
        raise ApiError("invalid_captcha")  # already used (right or wrong) within the window
    if not hmac.compare_digest(sig, signature(secret_key, challenge_id, exp, answer)):
        raise ApiError("invalid_captcha")


__all__ = ["DIGITS", "REUSE_WINDOW_S", "TTL_S", "new_challenge", "render_png", "signature", "verify"]
