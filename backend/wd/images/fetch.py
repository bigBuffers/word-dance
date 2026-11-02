"""SSRF-safe image download and normalisation (DESIGN §9 "Download", §10 SSRF row).

:func:`safe_download` — ``https`` only, hostname (never an IP literal), every A/AAAA record public (loopback, RFC 1918,
link-local, CGNAT 100.64/10, multicast, reserved, ``::1``, ULA ``fc00::/7``, ``fe80::/10`` and NAT64/IPv4-mapped
wrappers of those are rejected), the connection goes to the validated IP with the ``Host`` header and
``extensions={'sni_hostname': host}`` (DNS pinning), ≤ 3 redirects each re-validated, ``Content-Type: image/*``,
streamed with a byte cap (``WD_IMAGE_MAX_BYTES``), magic bytes JPEG/PNG/WebP.

:func:`normalise_image` — Pillow ``MAX_IMAGE_PIXELS=40_000_000`` (bomb warnings are errors), ``verify()`` then
reopen, ``exif_transpose``, RGB (alpha composited on white), long edge ≤ ``WD_IMAGE_MAX_EDGE``, progressive JPEG
q82 without EXIF/ICC.

:func:`download_and_store` — both steps plus :mod:`store` (sha path, 0600, dedupe); returns None on any failure.
"""

from __future__ import annotations

import io
import ipaddress
import logging
import re
import socket
import warnings
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import Settings
from ..interfaces import Candidate
from . import store
from .providers import base

log = logging.getLogger("wd.images.fetch")

Image.MAX_IMAGE_PIXELS = 40_000_000

MAX_REDIRECTS = 3
CHUNK_BYTES = 64 * 1024
JPEG_QUALITY = 82
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*\.?$")
NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
SHARED_V4 = ipaddress.ip_network("100.64.0.0/10")
REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class FetchError(Exception):
    """The download was refused or failed (reason in the message)."""


class SsrfError(FetchError):
    """The URL or a resolved address violates the SSRF rules."""


@dataclass
class Download:
    data: bytes
    final_url: str
    content_type: str


@dataclass
class NormalisedImage:
    data: bytes
    width: int
    height: int
    source_format: str


@dataclass
class StoredImage:
    sha256: str
    file_path: str
    file_bytes: int
    width: int
    height: int
    mime: str
    source_url: str


# ------------------------------------------------------------------------------------------ addresses
def is_public_ip(value: str) -> bool:
    """True only for a globally routable unicast address (IPv4-mapped / NAT64 wrappers are unwrapped first)."""
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            ip = mapped
        elif ip in NAT64_PREFIX:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
        elif ip.teredo is not None:
            return False
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv4Address) and ip in SHARED_V4:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return False
    return bool(ip.is_global)


def resolve_host(host: str) -> list[str]:
    """All A/AAAA records of ``host`` (module-level so tests can replace it)."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SsrfError(f"cannot resolve {host}: {e}") from e
    ips: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = str(sockaddr[0])
        if ip not in ips:
            ips.append(ip)
    return ips


def validate_url(url: str) -> tuple[str, str]:
    """Check the URL shape; returns ``(host, url)`` with the host lower-cased. Raises :class:`SsrfError`."""
    raw = url.strip()
    try:
        # the whole URL, not only the host: a C0/DEL byte in the path or query, or a port that is not a number, would
        # otherwise surface inside the request as httpx.InvalidURL / ValueError — neither is an httpx.HTTPError, so
        # nothing below would turn it into a FetchError and the whole fetch job would crash on one candidate
        httpx.URL(raw)
        parts = urlsplit(raw)
        port = parts.port
    except (httpx.InvalidURL, ValueError) as e:
        raise SsrfError(f"invalid URL: {e}") from e
    if parts.scheme.lower() != "https":
        raise SsrfError("only https URLs are downloaded")
    if parts.username is not None or parts.password is not None:
        raise SsrfError("credentials in URL")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise SsrfError("URL has no host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SsrfError("IP-literal URLs are refused")
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        raise SsrfError(f"host {host} is not public")
    if not HOSTNAME_RE.match(host):
        raise SsrfError(f"invalid hostname {host!r}")
    if port not in (None, 443):
        raise SsrfError("only port 443 is allowed")
    normalised = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
    return host, normalised


def pin(url: str) -> tuple[str, str]:
    """Validate ``url``, resolve its host, require every record public; returns ``(host, url_with_ip)``."""
    host, url = validate_url(url)
    ips = resolve_host(host)
    if not ips:
        raise SsrfError(f"{host} has no address records")
    for ip in ips:
        if not is_public_ip(ip):
            raise SsrfError(f"{host} resolves to a non-public address {ip}")
    chosen = ips[0]
    parts = urlsplit(url)
    netloc = f"[{chosen}]" if ":" in chosen else chosen
    return host, urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))


# ------------------------------------------------------------------------------------------- download
def sniff_mime(data: bytes) -> str | None:
    """``image/jpeg`` / ``image/png`` / ``image/webp`` from the magic bytes, else None."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def download_client(cfg: Settings) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": base.user_agent(cfg), "Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8"},
    )


def safe_download(
    url: str,
    cfg: Settings,
    *,
    client_factory: Callable[[], httpx.Client] | None = None,
    max_bytes: int | None = None,
    max_redirects: int = MAX_REDIRECTS,
) -> Download:
    """Fetch ``url`` under the SSRF rules; returns the raw bytes (magic bytes verified) or raises :class:`FetchError`."""
    cap = int(max_bytes or cfg.image_max_bytes)
    client = client_factory() if client_factory else download_client(cfg)
    current = url
    with client:
        for _hop in range(max_redirects + 1):
            host, pinned_url = pin(current)
            try:
                headers = base.request_headers(cfg, {"Host": host, "Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8"})
                with client.stream("GET", pinned_url, headers=headers, extensions={"sni_hostname": host}, follow_redirects=False) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError(f"HTTP {response.status_code} without Location")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise FetchError(f"HTTP {response.status_code}")
                    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                    if not content_type.startswith("image/"):
                        raise FetchError(f"unexpected Content-Type {content_type or '(none)'}")
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > cap:
                        raise FetchError(f"Content-Length {declared} exceeds the {cap}-byte cap")
                    buf = bytearray()
                    for chunk in response.iter_bytes(CHUNK_BYTES):
                        buf += chunk
                        if len(buf) > cap:
                            raise FetchError(f"body exceeds the {cap}-byte cap")
            except (httpx.HTTPError, httpx.InvalidURL) as e:  # InvalidURL is not an HTTPError (belt and braces to validate_url)
                raise FetchError(f"request failed: {e.__class__.__name__}: {e}") from e
            data = bytes(buf)
            if sniff_mime(data) is None:
                raise FetchError("not a JPEG/PNG/WebP file (magic bytes)")
            return Download(data=data, final_url=current, content_type=content_type)
    raise FetchError(f"more than {max_redirects} redirects")


# ------------------------------------------------------------------------------------------ normalise
def normalise_image(data: bytes, max_edge: int) -> NormalisedImage:
    """Decode defensively and re-encode as a metadata-free progressive JPEG with the long edge ≤ ``max_edge``."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            probe = Image.open(io.BytesIO(data))
            source_format = probe.format or ""
            if source_format not in ALLOWED_FORMATS:
                raise FetchError(f"unsupported image format {source_format or 'unknown'}")
            probe.verify()
            img = Image.open(io.BytesIO(data))
            img.load()
        except FetchError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError, SyntaxError) as e:
            raise FetchError(f"image decode failed: {e.__class__.__name__}: {e}") from e
    img = ImageOps.exif_transpose(img) or img
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, rgba).convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, progressive=True, optimize=True)
    return NormalisedImage(data=out.getvalue(), width=img.width, height=img.height, source_format=source_format)


def download_and_store(cand: Candidate, cfg: Settings, *, client_factory: Callable[[], httpx.Client] | None = None) -> StoredImage | None:
    """``safe_download`` → ``normalise_image`` → ``store.write_bytes``; None (logged) when any step refuses."""
    try:
        download = safe_download(cand.image_url, cfg, client_factory=client_factory)
        image = normalise_image(download.data, cfg.image_max_edge)
    except FetchError as e:
        log.info("image download refused for %s:%s: %s", cand.provider, cand.ref, e, extra={"provider": cand.provider, "event": "image_refused"})
        return None
    stored = store.write_bytes(cfg, image.data, "jpg")
    return StoredImage(
        sha256=stored.sha256,
        file_path=stored.file_path,
        file_bytes=stored.file_bytes,
        width=image.width,
        height=image.height,
        mime="image/jpeg",
        source_url=cand.image_url,
    )
