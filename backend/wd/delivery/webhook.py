"""Webhook delivery (WP4, DESIGN §6.5, API.md 17): the ``send_webhook`` handler, the five formats and the SSRF-safe
:func:`safe_post` (``https`` only, hostname never an IP literal, every DNS record public, the connection pinned to
the resolved address with the ``Host`` header and ``sni_hostname``, 10 s timeout, no redirects).

Formats (payload shapes): ``generic`` ``{type, date, title, body, counts, words:[{word, phonetic, meaning_zh}], url}``
(``url: null`` when no public URL is known) · ``wecom`` ``{"msgtype":"text","text":{"content":…}}`` · ``feishu``
``{"msg_type":"text","content":{"text":…}}`` · ``serverchan`` ``{"title":…,"desp":…}`` · ``bark`` ``{"title":…,"body":…,"url":…}``
(``url`` omitted when unknown). :func:`send_test_webhook` is called synchronously by ``POST /api/settings/webhook/test``
(WP2's settings router) and answers ``{ok, http_status, error, reason}``: ``error`` is the English transport diagnostic
kept for the admin job ledger, ``reason`` the closed set of API.md 17 (:data:`REASONS`, classified from the exception
type by :func:`classify_error`) that the UI maps to zh copy.

A 2xx is not yet a delivery: 企业微信, 飞书, Server酱 and Bark answer ``200`` with an error body (``errcode`` / ``code`` ≠ 0, Bark
``code`` ≠ 200) when the key is wrong or the message is refused — :func:`provider_error` reads that body for the format, so the
ledger, the batch status and the settings test say ``HTTP 200 but wecom errcode 93000: …`` instead of a false success.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import sqlite3
import ssl
from typing import Any, Callable, Iterator, Mapping, NamedTuple
from urllib.parse import urlsplit, urlunsplit

import httpx

from .. import __version__, db
from ..interfaces import Job
from ..jobs import queue
from ..jobs.registry import JobContext, register
from ..services import batches
from . import email as email_mod

log = logging.getLogger("wd.delivery.webhook")

TIMEOUT_S = 10.0
FORMATS: tuple[str, ...] = ("generic", "wecom", "feishu", "serverchan", "bark")
HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".lan", ".home", ".intranet", ".corp", ".test", ".invalid", ".example")
NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
SHARED_V4 = ipaddress.ip_network("100.64.0.0/10")
TEST_TITLE_ZH = "word-Dance 测试消息"
TEST_BODY_ZH = "Webhook 配置成功，每日词汇将推送到这里。"
NO_LINK_ZH = email_mod.NO_LINK_ZH
DELIVERY_ERROR_CHARS = 300
#: API.md 17 ``reason`` values (``schemas.WebhookTestReason`` mirrors them; ``None`` on success)
REASONS: tuple[str, ...] = ("dns_failed", "host_not_public", "connect_failed", "timeout", "tls_failed", "http_error", "invalid_url")
#: substrings of the resolver errors httpcore wraps into a ``ConnectError`` (glibc / macOS / Windows spellings)
DNS_MARKERS: tuple[str, ...] = ("name or service not known", "nodename nor servname", "name resolution", "getaddrinfo", "no address associated", "name does not resolve")
#: substrings of the OpenSSL errors httpcore wraps into a ``ConnectError`` (``[SSL: CERTIFICATE_VERIFY_FAILED] …``)
TLS_MARKERS: tuple[str, ...] = ("ssl", "tls", "certificate")

#: tests replace this with a factory returning an ``httpx.Client`` on a ``MockTransport``
CLIENT_FACTORY: Callable[[], httpx.Client] | None = None


class WebhookError(Exception):
    """The request was refused or failed (reason in the message)."""


class SsrfError(WebhookError):
    """The URL or a resolved address violates the SSRF rules (never retried) — ``reason`` ``host_not_public``."""


class InvalidUrlError(SsrfError):
    """The URL itself is unusable for a webhook (scheme, credentials, host, port) — ``reason`` ``invalid_url``."""


class DnsError(SsrfError):
    """The hostname has no usable address records — ``reason`` ``dns_failed`` (final like every :class:`SsrfError`)."""


class PostResult(NamedTuple):
    """What :func:`safe_post` reports: ``error`` and ``reason`` are None on a 2xx response, else the English diagnostic
    (``rejected: …`` / ``request failed: <Exception>: …`` / ``HTTP <code>``) and one of :data:`REASONS`."""

    http_status: int | None
    error: str | None
    reason: str | None


# -------------------------------------------------------------------------------------------- SSRF
def is_public_ip(value: str) -> bool:
    """True only for a globally routable unicast address (IPv4-mapped / NAT64 / 6to4 wrappers are unwrapped first)."""
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
        raise DnsError(f"cannot resolve {host}: {e}") from e
    ips: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = str(sockaddr[0])
        if ip not in ips:
            ips.append(ip)
    return ips


def validate_url(url: str) -> tuple[str, str]:
    """Shape check: ``https``, a real hostname, no credentials; returns ``(host, normalised_url)``.

    A malformed URL raises :class:`InvalidUrlError`, a hostname the SSRF policy denies (IP literal, ``localhost``,
    local suffixes, no dot) a plain :class:`SsrfError`.
    """
    try:
        parts = urlsplit((url or "").strip())
    except ValueError as e:  # e.g. an unbalanced IPv6 bracket
        raise InvalidUrlError(f"malformed URL: {e}") from e
    if parts.scheme.lower() != "https":
        raise InvalidUrlError("only https URLs are allowed")
    if parts.username is not None or parts.password is not None:
        raise InvalidUrlError("credentials in URL")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise InvalidUrlError("URL has no host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SsrfError("IP-literal URLs are refused")
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES) or "." not in host:
        raise SsrfError(f"host {host} is not public")
    if not HOSTNAME_RE.match(host):
        raise InvalidUrlError(f"invalid hostname {host!r}")
    try:
        port = parts.port
    except ValueError as e:
        raise InvalidUrlError("invalid port") from e
    netloc = host if port in (None, 443) else f"{host}:{port}"
    return host, urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))


def pin(url: str) -> tuple[str, str]:
    """Validate, resolve, require every record public; returns ``(host, url_with_the_resolved_ip)``."""
    host, url = validate_url(url)
    ips = resolve_host(host)
    if not ips:
        raise DnsError(f"{host} has no address records")
    for ip in ips:
        if not is_public_ip(ip):
            raise SsrfError(f"{host} resolves to a non-public address {ip}")
    chosen = ips[0]
    parts = urlsplit(url)
    port = parts.port
    netloc = f"[{chosen}]" if ":" in chosen else chosen
    if port not in (None, 443):
        netloc = f"{netloc}:{port}"
    return host, urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))


def _client() -> httpx.Client:
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY()
    return httpx.Client(
        timeout=httpx.Timeout(TIMEOUT_S, connect=TIMEOUT_S),
        follow_redirects=False,
        headers={"User-Agent": f"word-Dance/{__version__}"},
    )


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """``exc`` and everything it was raised from (``__cause__`` / ``__context__``), nearest first."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def classify_error(exc: BaseException) -> str:
    """The API.md 17 ``reason`` for a failed send, from the exception type (``error`` keeps the raw diagnostic).

    Our own refusals carry their class (:class:`DnsError` → ``dns_failed``, :class:`InvalidUrlError` → ``invalid_url``,
    any other :class:`SsrfError` → ``host_not_public``). httpx timeouts → ``timeout``; a ``ConnectError`` (or any other
    transport error) raised from an :class:`ssl.SSLError` or whose text names OpenSSL → ``tls_failed``, from a
    :class:`socket.gaierror` or whose text names the resolver → ``dns_failed``; everything else → ``connect_failed``.
    """
    if isinstance(exc, DnsError):
        return "dns_failed"
    if isinstance(exc, InvalidUrlError):
        return "invalid_url"
    if isinstance(exc, SsrfError):
        return "host_not_public"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    chain = list(_chain(exc))
    if any(isinstance(e, socket.gaierror) for e in chain):
        return "dns_failed"
    if any(isinstance(e, ssl.SSLError) for e in chain):
        return "tls_failed"
    text = " ".join(str(e) for e in chain).lower()
    if any(marker in text for marker in DNS_MARKERS):
        return "dns_failed"
    if any(marker in text for marker in TLS_MARKERS):
        return "tls_failed"
    return "connect_failed"


def safe_post(url: str, payload: Mapping[str, Any], *, timeout_s: float = TIMEOUT_S, client: httpx.Client | None = None, fmt: str = "generic") -> PostResult:
    """POST ``payload`` as JSON under the SSRF rules; returns :class:`PostResult` ``(http_status, error, reason)`` and
    never raises.

    ``error`` and ``reason`` are None on a 2xx response. An :class:`SsrfError` is reported with ``http_status None``
    and the ``rejected: …`` diagnostic, a transport failure as ``request failed: <Exception>: …``, a non-2xx answer as
    ``HTTP <code>`` with ``reason`` ``http_error``; :func:`classify_error` names the other reasons. ``fmt`` names the payload
    format so a 2xx whose body carries the provider's own error (:func:`provider_error`) is reported as ``HTTP <code> but …``
    with ``reason`` ``http_error`` instead of a success.
    """
    try:
        host, pinned = pin(url)
    except SsrfError as e:
        return PostResult(None, f"rejected: {e}", classify_error(e))
    own = client is None
    c = client if client is not None else _client()
    try:
        response = c.post(
            pinned,
            json=dict(payload),
            headers={"Host": host, "Content-Type": "application/json; charset=utf-8"},
            extensions={"sni_hostname": host},
            follow_redirects=False,
            timeout=timeout_s,
        )
    except httpx.HTTPError as e:
        return PostResult(None, f"request failed: {e.__class__.__name__}: {e}", classify_error(e))
    finally:
        if own:
            c.close()
    if 200 <= response.status_code < 300:
        problem = provider_error(fmt, response)
        if problem is not None:
            return PostResult(response.status_code, f"HTTP {response.status_code} but {problem}", "http_error")
        return PostResult(response.status_code, None, None)
    return PostResult(response.status_code, f"HTTP {response.status_code}", "http_error")


PROVIDER_MESSAGE_MAX = 80


def provider_error(fmt: str, response: httpx.Response) -> str | None:
    """The provider's own refusal inside a 2xx answer, or None: 企业微信 ``{errcode, errmsg}`` (0 = ok), 飞书 ``{code, msg}`` (new) /
    ``{StatusCode, StatusMessage}`` (legacy) (0 = ok), Server酱 Turbo / ³ ``{code, message}`` (0 = ok), Bark ``{code, message}``
    (200 = ok). ``generic`` and any non-JSON or unexpected body pass — the operator's own endpoint owes nothing but a 2xx."""
    if fmt == "generic":
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None

    def code_of(*keys: str) -> tuple[str, int] | None:
        for key in keys:
            value = body.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return key, value
            if isinstance(value, str) and value.strip().lstrip("-").isdigit():
                return key, int(value.strip())
        return None

    def text_of(*keys: str) -> str:
        for key in keys:
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:PROVIDER_MESSAGE_MAX]
        return ""

    if fmt == "wecom":
        found = code_of("errcode")
        if found is not None and found[1] != 0:
            return f"wecom errcode {found[1]}: {text_of('errmsg')}".rstrip(": ")
    elif fmt == "feishu":
        found = code_of("code", "StatusCode")
        if found is not None and found[1] != 0:
            return f"feishu {found[0]} {found[1]}: {text_of('msg', 'StatusMessage', 'message')}".rstrip(": ")
    elif fmt == "serverchan":
        found = code_of("code")
        if found is not None and found[1] != 0:
            return f"serverchan code {found[1]}: {text_of('message', 'info')}".rstrip(": ")
    elif fmt == "bark":
        found = code_of("code")
        if found is not None and found[1] != 200:
            return f"bark code {found[1]}: {text_of('message')}".rstrip(": ")
    return None


# ------------------------------------------------------------------------------------------ formats
def digest_body(d: email_mod.Digest) -> str:
    """The plain-text body shared by the text-style formats."""
    lines = [d.summary_zh, ""]
    lines.extend(d.word_lines())
    lines.append("")
    lines.append(f"{email_mod.OPEN_LINK_ZH}：{d.url}" if d.url else NO_LINK_ZH)
    return "\n".join(lines).strip()


def build_payload(fmt: str, title: str, body: str, *, url: str | None, date: str, counts: Mapping[str, int] | None = None, words: list[dict[str, Any]] | None = None, type_: str = "daily_push") -> dict[str, Any]:
    """The request body for ``fmt`` (DESIGN §6.5 shapes)."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown webhook format {fmt!r}")
    text = f"{title}\n{body}"
    if fmt == "generic":
        return {
            "type": type_,
            "date": date,
            "title": title,
            "body": body,
            "counts": dict(counts or {"review": 0, "new": 0, "screen": 0, "extra": 0, "deferred_reviews": 0}),
            "words": list(words or []),
            "url": url,
        }
    if fmt == "wecom":
        return {"msgtype": "text", "text": {"content": text}}
    if fmt == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if fmt == "serverchan":
        return {"title": title, "desp": body}
    payload: dict[str, Any] = {"title": title, "body": body}  # bark
    if url:
        payload["url"] = url
    return payload


def digest_payload(fmt: str, d: email_mod.Digest) -> dict[str, Any]:
    return build_payload(
        fmt,
        d.title,
        digest_body(d),
        url=d.url,
        date=d.local_date,
        counts={"review": d.review, "new": d.new, "screen": d.screen, "extra": d.extra, "deferred_reviews": d.deferred},
        words=[{"word": w.word, "phonetic": w.phonetic, "meaning_zh": w.meaning_zh} for w in d.words],
    )


# ------------------------------------------------------------------------------------------ sending
def _set_webhook_status(conn: sqlite3.Connection, batch_id: int, status: str, error: str | None = None) -> None:
    with db.maybe_tx(conn):
        conn.execute(
            "UPDATE push_batches SET webhook_status = ?, delivery_error = ? WHERE id = ?",
            (status, None if error is None else error[:DELIVERY_ERROR_CHARS], int(batch_id)),
        )


def send_batch_webhook(conn: sqlite3.Connection, cfg: Any, batch_id: int, now: str) -> dict[str, Any]:
    """Send the digest of ``batch_id`` to the user's webhook; idempotent (``sent`` batches are not re-sent).

    Raises :class:`WebhookError` on an HTTP/network failure (retried by the handler) and :class:`SsrfError` for a
    refused URL (final).
    """
    batch = batches.batch_row(conn, batch_id)
    if batch is None:
        return {"skipped": "batch_missing"}
    if batch.get("webhook_status") == "sent":
        return {"skipped": "already_sent"}
    s = conn.execute("SELECT webhook_enabled, webhook_url, webhook_format FROM user_settings WHERE user_id = ?", (int(batch["user_id"]),)).fetchone()
    if s is None or not int(s["webhook_enabled"] or 0) or not s["webhook_url"]:
        _set_webhook_status(conn, batch_id, "skipped")
        return {"skipped": "channel_disabled"}
    fmt = str(s["webhook_format"] or "generic")
    payload = digest_payload(fmt, email_mod.build_digest(conn, cfg, batch))
    status, error, _reason = safe_post(str(s["webhook_url"]), payload, fmt=fmt)  # the ledger keeps the diagnostic text only
    if error is None:
        _set_webhook_status(conn, batch_id, "sent")
        log.info("webhook sent", extra={"event": "webhook_sent", "user_id": int(batch["user_id"]), "status": status})
        return {"sent": True, "http_status": status, "format": fmt}
    if status is None and error.startswith("rejected:"):
        raise SsrfError(error)
    raise WebhookError(error)


def send_test_webhook(settings_row: Mapping[str, Any]) -> dict[str, Any]:
    """API.md 17: post a test message in the configured format synchronously → ``{ok, http_status, error, reason}``
    (``reason`` ∈ :data:`REASONS`, None when ``ok``)."""
    url = str(settings_row.get("webhook_url") or "")
    fmt = str(settings_row.get("webhook_format") or "generic")
    if fmt not in FORMATS:
        fmt = "generic"
    from datetime import datetime, timezone

    payload = build_payload(fmt, TEST_TITLE_ZH, TEST_BODY_ZH, url=None, date=datetime.now(timezone.utc).date().isoformat(), type_="test")
    result = safe_post(url, payload, fmt=fmt)
    return {"ok": result.error is None, "http_status": result.http_status, "error": result.error, "reason": result.reason}


@register("send_webhook")
def handle_send_webhook(ctx: JobContext, jobs: list[Job]) -> None:
    """``send_webhook`` handler: HTTP failures retry through ``queue.fail``; SSRF rejections are final (``failed``)."""
    for job in jobs:
        conn = ctx.db()
        try:
            now = ctx.now()
            batch_id = (job.payload or {}).get("batch_id")
            if batch_id is None:
                queue.fail(conn, job.id, "send_webhook payload without batch_id", now=now)
                continue
            try:
                result = send_batch_webhook(conn, ctx.cfg, int(batch_id), now)
            except SsrfError as e:
                _set_webhook_status(conn, int(batch_id), "failed", str(e))
                queue.finish(conn, job.id, {"error": str(e)[:DELIVERY_ERROR_CHARS], "final": True}, now=now)
                log.warning("webhook refused: %s", e, extra={"event": "webhook_rejected", "job_id": job.id})
                continue
            except WebhookError as e:
                status = queue.fail(conn, job.id, str(e), now=now)
                _set_webhook_status(conn, int(batch_id), "failed" if status == "dead" else "queued", str(e))
                log.warning("webhook delivery failed (%s): %s", status, e, extra={"event": "webhook_failed", "job_id": job.id})
                continue
            queue.finish(conn, job.id, result, now=now)
        finally:
            conn.close()


__all__ = [
    "CLIENT_FACTORY",
    "DnsError",
    "FORMATS",
    "InvalidUrlError",
    "PostResult",
    "REASONS",
    "SsrfError",
    "TEST_BODY_ZH",
    "TEST_TITLE_ZH",
    "WebhookError",
    "build_payload",
    "classify_error",
    "digest_body",
    "digest_payload",
    "handle_send_webhook",
    "is_public_ip",
    "pin",
    "resolve_host",
    "safe_post",
    "send_batch_webhook",
    "send_test_webhook",
    "validate_url",
]
