"""E-mail delivery (WP4, DESIGN §6.5, API.md 18): the ``send_email`` job handler, digest rendering and :func:`public_url`.

Payloads: ``{"batch_id": 9}`` for a published batch (dedupe ``email:<batch_id>``) or ``{"user_id": 7, "test": true}``
for the 发送测试邮件 button (dedupe ``email:test:<user_id>``). The digest (first 10 words with phonetic, meaning and
first example, no images) is rendered from ``templates/daily_email.{txt,html}``; the button links to
``<public_url>/today`` and is omitted when no public URL is known (text 「请在浏览器中打开 word-Dance」).

The mailer comes from ``delivery.mailer.mailer_from_settings(cfg)``; tests install a ``RecordingMailer`` through
:func:`set_mailer`. Sending failures (``MailerError``) are retried through ``queue.fail`` (2 / 10 / 60 min backoff);
``push_batches.email_status`` tracks ``queued → sent | failed | skipped``.
"""

from __future__ import annotations

import html
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from string import Template
from typing import Any, Mapping

from .. import db
from ..clock import compute_next_push, parse_iso, to_iso, zone
from ..interfaces import Job, Mailer
from ..jobs import queue
from ..jobs.registry import JobContext, register
from ..services import batches, words
from .mailer import MailerError, mailer_from_settings

log = logging.getLogger("wd.delivery.email")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
SUBJECT_PREFIX = "【word-Dance】"
TEST_SUBJECT = f"{SUBJECT_PREFIX}测试邮件"
DIGEST_WORDS = 10
NO_LINK_ZH = "请在浏览器中打开 word-Dance"
OPEN_LINK_ZH = "打开 word-Dance 开始学习"
START_BUTTON_ZH = "开始学习"
DELIVERY_ERROR_CHARS = 300

_mailer_override: Mailer | None = None


# ---------------------------------------------------------------------------------------- plumbing
def set_mailer(mailer: Mailer | None) -> None:
    """Install a mailer for every later send (tests: ``RecordingMailer``); None restores the configured one."""
    global _mailer_override
    _mailer_override = mailer


def get_mailer(cfg: Any) -> Mailer | None:
    """The mailer to use: the test override, else the SMTP mailer (None while SMTP is unconfigured)."""
    if _mailer_override is not None:
        return _mailer_override
    return mailer_from_settings(cfg)


def public_url(conn: sqlite3.Connection, cfg: Any) -> str | None:
    """DESIGN §6.5: ``WD_PUBLIC_URL`` → ``kv.public_url_guess`` → None (then links are omitted)."""
    configured = str(getattr(cfg, "public_url", "") or "").strip().rstrip("/")
    if configured:
        return configured
    guess = (db.kv_get(conn, "public_url_guess") or "").strip().rstrip("/")
    return guess or None


def today_link(base: str | None) -> str | None:
    return None if not base else f"{base}/today"


def date_zh(d: date | str) -> str:
    """``10月14日``."""
    dd = d if isinstance(d, date) else date.fromisoformat(str(d))
    return f"{dd.month}月{dd.day}日"


def local_time_zh(instant: datetime | str, tz: str) -> str:
    """``10月15日 08:00`` for a UTC instant rendered in ``tz``."""
    dt = instant if isinstance(instant, datetime) else parse_iso(str(instant))
    local = dt.astimezone(zone(tz))
    return f"{local.month}月{local.day}日 {local.hour:02d}:{local.minute:02d}"


def _template(name: str) -> Template:
    return Template((TEMPLATES_DIR / name).read_text(encoding="utf-8"))


def _row(conn: sqlite3.Connection, sql: str, params: Any = ()) -> dict[str, Any] | None:
    r = conn.execute(sql, params).fetchone()
    return None if r is None else {k: r[k] for k in r.keys()}


# ------------------------------------------------------------------------------------------- digest
@dataclass
class DigestWord:
    word: str
    phonetic: str | None
    meaning_zh: str
    example_en: str | None = None
    example_zh: str | None = None


@dataclass
class Digest:
    """What both channels render (shared by ``delivery.webhook``)."""

    batch_id: int
    local_date: str
    date_zh: str
    review: int
    new: int
    screen: int
    extra: int
    deferred: int
    words: list[DigestWord] = field(default_factory=list)
    url: str | None = None  # <public_url>/today, None when unknown

    @property
    def counts_zh(self) -> str:
        parts = [f"复习 {self.review}", f"新词 {self.new}"]
        if self.screen:
            parts.append(f"推荐 {self.screen}")
        return " · ".join(parts)

    @property
    def subject(self) -> str:
        return f"{SUBJECT_PREFIX}今日词汇 {self.date_zh} · {self.counts_zh}"

    @property
    def title(self) -> str:
        return f"word-Dance 今日词汇 {self.date_zh} · {self.counts_zh}"

    @property
    def summary_zh(self) -> str:
        line = f"复习 {self.review} · 新词 {self.new} · 推荐词 {self.screen}"
        if self.extra:
            line += f" · 加练 {self.extra}"
        if self.deferred:
            line += f"（另有 {self.deferred} 个复习顺延）"
        return line

    def word_lines(self) -> list[str]:
        lines = []
        for i, w in enumerate(self.words, 1):
            head = f"{i}. {w.word}"
            if w.phonetic:
                head += f" /{w.phonetic}/"
            if w.meaning_zh:
                head += f" — {w.meaning_zh}"
            lines.append(head)
            if w.example_en:
                lines.append(f"   {w.example_en}")
                if w.example_zh:
                    lines.append(f"   {w.example_zh}")
        return lines


def build_digest(conn: sqlite3.Connection, cfg: Any, batch: Mapping[str, Any], *, limit: int = DIGEST_WORDS) -> Digest:
    """The first ``limit`` distinct words of the batch in study order, with content when available."""
    rows = conn.execute(
        "SELECT pi.word_id, MIN(pi.position) AS pos FROM push_items pi WHERE pi.batch_id = ? GROUP BY pi.word_id ORDER BY pos LIMIT ?",
        (int(batch["id"]), int(limit)),
    ).fetchall()
    out: list[DigestWord] = []
    for word_id, _pos in rows:
        w = words.word_row(conn, int(word_id))
        if w is None:
            continue
        content = words.active_content(conn, w) or {}
        example = (content.get("examples") or [None])[0] if isinstance(content.get("examples"), list) else None
        meaning = str(content.get("meaning_zh") or "").strip() or words.short_meaning(w)
        out.append(
            DigestWord(
                word=str(w["display"]),
                phonetic=(w.get("phonetic") or None),
                meaning_zh=meaning,
                example_en=(str(example.get("en")).strip() if isinstance(example, dict) and example.get("en") else None),
                example_zh=(str(example.get("zh")).strip() if isinstance(example, dict) and example.get("zh") else None),
            )
        )
    return Digest(
        batch_id=int(batch["id"]),
        local_date=str(batch["local_date"]),
        date_zh=date_zh(str(batch["local_date"])),
        review=int(batch.get("review_count") or 0),
        new=int(batch.get("new_count") or 0),
        screen=int(batch.get("screen_count") or 0),
        extra=int(batch.get("extra_count") or 0),
        deferred=int(batch.get("deferred_reviews") or 0),
        words=out,
        url=today_link(public_url(conn, cfg)),
    )


# ---------------------------------------------------------------------------------------- rendering
def render_digest(d: Digest) -> tuple[str, str, str]:
    """``(subject, text, html)`` for a daily digest."""
    link_line = f"{OPEN_LINK_ZH}：{d.url}" if d.url else NO_LINK_ZH
    text = _template("daily_email.txt").safe_substitute(
        title=d.title,
        summary=d.summary_zh,
        word_lines="\n".join(d.word_lines()) or "（今天没有新的词汇）",
        link_line=link_line,
    )
    rows = []
    for i, w in enumerate(d.words, 1):
        head = f"<strong>{html.escape(w.word)}</strong>"
        if w.phonetic:
            head += f' <span style="color:#7b8794;">/{html.escape(w.phonetic)}/</span>'
        meaning = html.escape(w.meaning_zh)
        example = ""
        if w.example_en:
            example = f'<div style="color:#52606d;font-size:13px;padding-top:4px;">{html.escape(w.example_en)}'
            if w.example_zh:
                example += f'<br>{html.escape(w.example_zh)}'
            example += "</div>"
        rows.append(
            '<tr><td style="padding:10px 0;border-top:1px solid #e4e7eb;font-size:15px;">'
            f'<span style="color:#9aa5b1;">{i}.</span> {head} <span style="color:#1f2933;">{meaning}</span>{example}</td></tr>'
        )
    if d.url:
        cta = (
            f'<a href="{html.escape(d.url, quote=True)}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;'
            f'padding:12px 20px;border-radius:8px;font-size:15px;font-weight:600;">{START_BUTTON_ZH}</a>'
        )
    else:
        cta = f'<span style="font-size:14px;color:#52606d;">{NO_LINK_ZH}</span>'
    page = _template("daily_email.html").safe_substitute(
        title=html.escape(d.title),
        summary=html.escape(d.summary_zh),
        rows="\n".join(rows) or '<tr><td style="padding:10px 0;color:#7b8794;">（今天没有新的词汇）</td></tr>',
        cta=cta,
    )
    return d.subject, text, page


def render_test(next_push_at: datetime | str | None, tz: str, url: str | None) -> tuple[str, str, str]:
    """``(subject, text, html)`` for the API.md 18 test e-mail: body = the next push time in the user's timezone + the link."""
    when = local_time_zh(next_push_at, tz) if next_push_at else "（未设置）"
    body = f"这是一封测试邮件。你的下次推送时间：{when}（{tz}）"
    link_line = f"{OPEN_LINK_ZH}：{url}" if url else NO_LINK_ZH
    text = f"{body}\n\n{link_line}\n\n—— word-Dance\n"
    link_html = f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>' if url else html.escape(NO_LINK_ZH)
    page = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>'
        f"{html.escape(TEST_SUBJECT)}</title></head><body style=\"font-family:sans-serif;color:#1f2933;\">"
        f"<p>{html.escape(body)}</p><p>{link_html}</p><p style=\"color:#9aa5b1;font-size:12px;\">word-Dance</p></body></html>"
    )
    return TEST_SUBJECT, text, page


# ------------------------------------------------------------------------------------------ sending
def _user_and_settings(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    return _row(
        conn,
        "SELECT u.id, u.email, u.email_verified_at, s.timezone, s.push_time, s.next_push_at, s.email_enabled "
        "FROM users u LEFT JOIN user_settings s ON s.user_id = u.id WHERE u.id = ?",
        (int(user_id),),
    )


def _set_email_status(conn: sqlite3.Connection, batch_id: int, status: str, error: str | None = None) -> None:
    with db.maybe_tx(conn):
        conn.execute(
            "UPDATE push_batches SET email_status = ?, delivery_error = ? WHERE id = ?",
            (status, None if error is None else error[:DELIVERY_ERROR_CHARS], int(batch_id)),
        )


def send_digest_email(conn: sqlite3.Connection, cfg: Any, batch_id: int, now: str) -> dict[str, Any]:
    """Render and send the digest for ``batch_id``; idempotent (an already ``sent`` batch is not sent twice)."""
    batch = batches.batch_row(conn, batch_id)
    if batch is None:
        return {"skipped": "batch_missing"}
    if batch.get("email_status") == "sent":
        return {"skipped": "already_sent"}
    u = _user_and_settings(conn, int(batch["user_id"]))
    if u is None or not u.get("email") or u.get("email_verified_at") is None or not int(u.get("email_enabled") or 0):
        _set_email_status(conn, batch_id, "skipped")
        return {"skipped": "channel_disabled"}
    mailer = get_mailer(cfg)
    if mailer is None:
        _set_email_status(conn, batch_id, "skipped", "SMTP not configured")
        return {"skipped": "smtp_unconfigured"}
    subject, text, page = render_digest(build_digest(conn, cfg, batch))
    mailer.send(str(u["email"]), subject, text, page)  # MailerError propagates to the handler → retry
    _set_email_status(conn, batch_id, "sent")
    log.info("digest e-mail sent", extra={"event": "email_sent", "user_id": int(batch["user_id"])})
    return {"sent": True, "batch_id": int(batch_id)}


def send_test_email(conn: sqlite3.Connection, cfg: Any, user_id: int, now: str) -> dict[str, Any]:
    """The API.md 18 test e-mail (subject 【word-Dance】测试邮件); ``push_batches`` is untouched."""
    u = _user_and_settings(conn, user_id)
    if u is None or not u.get("email") or u.get("email_verified_at") is None:
        return {"skipped": "no_verified_email"}
    mailer = get_mailer(cfg)
    if mailer is None:
        return {"skipped": "smtp_unconfigured"}
    tz = str(u.get("timezone") or "Asia/Shanghai")
    next_push = u.get("next_push_at") or to_iso(compute_next_push(parse_iso(now), tz, str(u.get("push_time") or "08:00")))
    subject, text, page = render_test(next_push, tz, today_link(public_url(conn, cfg)))
    mailer.send(str(u["email"]), subject, text, page)
    log.info("test e-mail sent", extra={"event": "email_test_sent", "user_id": int(user_id)})
    return {"sent": True, "test": True}


def deliver(conn: sqlite3.Connection, cfg: Any, job: Job, now: str) -> dict[str, Any]:
    payload = job.payload or {}
    if payload.get("test"):
        return send_test_email(conn, cfg, int(payload["user_id"]), now)
    return send_digest_email(conn, cfg, int(payload["batch_id"]), now)


@register("send_email")
def handle_send_email(ctx: JobContext, jobs: list[Job]) -> None:
    """``send_email`` handler: one connection per job; ``MailerError`` → ``queue.fail`` (retry / dead → ``failed``)."""
    for job in jobs:
        conn = ctx.db()
        try:
            now = ctx.now()
            try:
                result = deliver(conn, ctx.cfg, job, now)
            except MailerError as e:
                status = queue.fail(conn, job.id, str(e), now=now)
                batch_id = (job.payload or {}).get("batch_id")
                if batch_id is not None:
                    _set_email_status(conn, int(batch_id), "failed" if status == "dead" else "queued", str(e))
                log.warning("e-mail delivery failed (%s): %s", status, e, extra={"event": "email_failed", "job_id": job.id})
                continue
            queue.finish(conn, job.id, result, now=now)
        finally:
            conn.close()


__all__ = [
    "DIGEST_WORDS",
    "Digest",
    "DigestWord",
    "NO_LINK_ZH",
    "TEST_SUBJECT",
    "build_digest",
    "date_zh",
    "deliver",
    "get_mailer",
    "handle_send_email",
    "local_time_zh",
    "public_url",
    "render_digest",
    "render_test",
    "send_digest_email",
    "send_test_email",
    "set_mailer",
    "today_link",
]
