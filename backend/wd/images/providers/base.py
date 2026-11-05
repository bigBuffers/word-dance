"""Shared provider plumbing (DESIGN §9): User-Agent, JSON GET with ``ProviderError`` mapping, licence
normalisation and allow-list, ``utm_*`` stripping, HTML-to-text for Commons attribution fields, and the
process-wide :class:`RateGate` behind Wikimedia's "≤ 1 request per second" politeness rule.
"""

from __future__ import annotations

import html
import re
import threading
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Callable, Mapping

import httpx

from ... import __version__
from ...config import Settings
from ...interfaces import ProviderError

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
MAX_API_REDIRECTS = 3

_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_WS_RE = re.compile(r"\s+")

# Licence families used for scoring (DESIGN §9: cc0/pd +3 · by +2 · by-sa +1); keyed stock providers grant a
# permissive licence of their own and score like CC BY.
LICENSE_CC0 = "cc0"
LICENSE_BY = "by"
LICENSE_BY_SA = "by-sa"
LICENSE_PERMISSIVE = "permissive"
LICENSE_OTHER = "other"

_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "jpe": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "bmp": "image/bmp",
}


# ------------------------------------------------------------------------------------ identity / http
def user_agent(cfg: Settings) -> str:
    """``word-Dance/<ver> (self-hosted vocabulary trainer; +<WD_PUBLIC_URL>; <WD_CONTACT_EMAIL>)`` (DESIGN §9).

    The ``+<url>`` part is omitted while ``WD_PUBLIC_URL`` is empty; the contact e-mail is always present
    (Wikimedia's User-Agent policy wants a way to reach the operator).
    """
    parts = ["self-hosted vocabulary trainer"]
    if cfg.public_url:
        parts.append("+" + cfg.public_url)
    parts.append(cfg.contact_email_effective)
    return f"word-Dance/{__version__} ({'; '.join(parts)})"


def make_client(cfg: Settings, *, accept: str = "application/json", follow_redirects: bool = True) -> httpx.Client:
    """An ``httpx.Client`` for provider API calls (tests inject ``httpx.MockTransport`` through ``mock_http``)."""
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=follow_redirects,
        max_redirects=MAX_API_REDIRECTS,
        headers={"User-Agent": user_agent(cfg), "Accept": accept},
    )


def request_headers(cfg: Settings, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Per-request headers: the User-Agent is set on every request so an injected client never hides it."""
    headers = {"User-Agent": user_agent(cfg)}
    if extra:
        headers.update(extra)
    return headers


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    """``Retry-After`` as seconds (delta-seconds or an HTTP-date), None when absent/unparsable."""
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        return int(v)
    try:
        when = parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    return max(0, int((when - ref).total_seconds()))


def get_json_with_headers(
    client: httpx.Client, name: str, url: str, *, params: Mapping[str, object] | None = None, headers: Mapping[str, str] | None = None
) -> tuple[dict, httpx.Headers]:
    """One GET expecting a JSON object, returned with the response headers; network / HTTP / decoding problems become
    :class:`ProviderError`. The headers matter to a caller that must read ``Retry-After`` off a *200* answer — MediaWiki
    reports ``maxlag`` that way (``wikimedia.py``), where :func:`get_json` alone would see a successful request."""
    try:
        response = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:
        raise ProviderError(f"{name}: request failed: {e.__class__.__name__}: {e}") from e
    if response.status_code >= 400:
        raise ProviderError(
            f"{name}: HTTP {response.status_code}",
            status=response.status_code,
            retry_after_s=parse_retry_after(response.headers.get("Retry-After")),
        )
    try:
        data = response.json()
    except ValueError as e:
        raise ProviderError(f"{name}: response is not JSON", status=response.status_code) from e
    if not isinstance(data, dict):
        raise ProviderError(f"{name}: unexpected JSON shape", status=response.status_code)
    return data, response.headers


def get_json(client: httpx.Client, name: str, url: str, *, params: Mapping[str, object] | None = None, headers: Mapping[str, str] | None = None) -> dict:
    """:func:`get_json_with_headers` without the headers (every provider but Commons)."""
    data, _ = get_json_with_headers(client, name, url, params=params, headers=headers)
    return data


# ---------------------------------------------------------------------------------------- url hygiene
def strip_utm(url: str) -> str:
    """Remove every ``utm_*`` query parameter (Commons appends ``?utm_source=…`` to thumb and original URLs)."""
    if not url or "?" not in url:
        return url
    base, _, query = url.partition("?")
    fragment = ""
    if "#" in query:
        query, _, fragment = query.partition("#")
    kept = [p for p in query.split("&") if p and not p.split("=", 1)[0].lower().startswith("utm_")]
    out = base
    if kept:
        out += "?" + "&".join(kept)
    if fragment:
        out += "#" + fragment
    return out


def mime_from_url(url: str | None) -> str | None:
    """MIME type guessed from the URL's file extension (query string ignored), or None."""
    if not url:
        return None
    path = url.split("?", 1)[0].split("#", 1)[0]
    ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    return _MIME_BY_EXT.get(ext)


def mime_from_filetype(filetype: str | None) -> str | None:
    if not filetype:
        return None
    return _MIME_BY_EXT.get(str(filetype).lower().lstrip("."))


# ------------------------------------------------------------------------------------- html → text
def html_to_text(fragment: str | None) -> str:
    """Strip tags from a Commons HTML field (``Artist``, ``Credit``) and collapse whitespace."""
    if not fragment:
        return ""
    text = _TAG_RE.sub(" ", fragment)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def first_href(fragment: str | None) -> str | None:
    """The first ``href`` of an HTML fragment as an absolute https URL (protocol-relative ``//`` resolved)."""
    if not fragment:
        return None
    m = _HREF_RE.search(fragment)
    if not m:
        return None
    href = html.unescape(m.group(1)).strip()
    if href.startswith("//"):
        href = "https:" + href
    if not href.lower().startswith(("http://", "https://")):
        return None
    return href


# ------------------------------------------------------------------------------------------ licences
def _license_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[\s\-_/]+", name.strip().lower()) if t]


def license_family(name: str | None) -> str:
    """``cc0`` · ``by`` · ``by-sa`` · ``permissive`` (Pixabay / Pexels licences) · ``other`` (incl. NC/ND)."""
    if not name:
        return LICENSE_OTHER
    tokens = _license_tokens(name)
    joined = " ".join(tokens)
    if "nc" in tokens or "nd" in tokens:
        return LICENSE_OTHER
    if joined.startswith("cc0") or joined.startswith("public domain") or joined.startswith("pd") or joined.startswith("pdm") or joined.startswith("cc zero"):
        return LICENSE_CC0
    if joined.startswith("pixabay") or joined.startswith("pexels"):
        return LICENSE_PERMISSIVE
    if joined.startswith("cc by sa") or joined.startswith("by sa"):
        return LICENSE_BY_SA
    if joined.startswith("cc by") or joined == "by" or joined.startswith("by "):
        return LICENSE_BY
    return LICENSE_OTHER


def license_allowed(name: str | None) -> bool:
    """DESIGN §9 allow-list: CC0 / Public domain / PD / CC BY / CC BY-SA (never NC or ND) + the keyed providers' licences."""
    return license_family(name) != LICENSE_OTHER


def openverse_license_name(code: str | None, version: str | None) -> str:
    """Openverse licence code (+ version) → display name: ``by``+``2.0`` → ``CC BY 2.0``, ``cc0`` → ``CC0 1.0``, ``pdm`` → ``Public domain``."""
    c = (code or "").strip().lower()
    v = (version or "").strip()
    if c == "pdm":
        return "Public domain"
    if c == "cc0":
        return f"CC0 {v or '1.0'}"
    if not c:
        return "unknown"
    name = "CC " + c.upper()
    return f"{name} {v}" if v else name


# ------------------------------------------------------------------------------------------ rate gate
class RateGate:
    """Process-wide minimum interval between calls (Wikimedia politeness ≤ 1 req/s).

    ``wait()`` blocks until ``min_interval_s`` has passed since the previous call and records the new instant;
    callers are serialised by a lock so concurrent threads never exceed the rate. ``monotonic``/``sleep`` are
    injectable for tests.
    """

    def __init__(self, min_interval_s: float, *, monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> float:
        """Block as needed; returns the seconds slept."""
        with self._lock:
            slept = 0.0
            now = self._monotonic()
            if self._last is not None:
                remaining = self._last + self.min_interval_s - now
                if remaining > 0:
                    self._sleep(remaining)
                    slept = remaining
                    now = self._monotonic()
            self._last = now
            return slept


_GATES: dict[str, RateGate] = {}
_GATES_LOCK = threading.Lock()


def gate_for(name: str, min_interval_s: float) -> RateGate:
    """The shared gate for ``name`` (created on first use; the interval follows the current settings)."""
    with _GATES_LOCK:
        gate = _GATES.get(name)
        if gate is None:
            gate = RateGate(min_interval_s)
            _GATES[name] = gate
        else:
            gate.min_interval_s = max(0.0, float(min_interval_s))
        return gate


def clean_text(value: object, limit: int = 300) -> str:
    """Normalise a provider string field: str(), whitespace collapsed, truncated."""
    if value is None:
        return ""
    text = _WS_RE.sub(" ", str(value)).strip()
    return text[:limit]
