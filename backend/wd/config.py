"""Runtime configuration (Phase 0, frozen contract — TASKS.md P0 step 4).

Every ``WD_*`` variable of DEPLOY.md §4 with its default, read from the process
environment (systemd ``EnvironmentFile`` in production; ``.env`` loaded by the CLI
through python-dotenv for manual runs; monkeypatched env in tests).

Validation rules:
* paths are resolved to absolute ``Path`` objects (directories are *not* created here —
  see :func:`ensure_dirs`);
* ``WD_AUDIO_PROVIDER`` is ``auto`` / ``say`` / ``youdao`` / ``bailian`` / ``cache`` / ``off`` (wd/audio.py; ``auto`` becomes ``say`` on a
  host with ``/usr/bin/say`` and ``off`` elsewhere — ``Settings.audio_provider_effective``; ``bailian`` is never chosen by ``auto``);
  ``cache`` serves the ``say`` clips another host synthesised and needs ``WD_AUDIO_CACHE_VOICES`` naming both accents' voices
  (``en-US=Ava (Premium);en-GB=Serena (Premium)``); ``WD_AUDIO_CACHE_MB`` bounds the clip cache; ``bailian`` (阿里云百炼 CosyVoice /
  Qwen-Audio TTS over its synchronous HTTP API, slice server-audio-2) refuses to start without ``WD_BAILIAN_API_KEY_FILE`` (the
  ``WD_ALIYUN_ACCESS_KEY_SECRET_FILE`` rule: an existing readable regular file, group/other-readable warns, the first line is read at
  call time) and ``WD_BAILIAN_WORKSPACE_ID`` (the 业务空间 id the endpoint host is built from), ``WD_BAILIAN_REGION`` is ``cn-beijing``
  / ``ap-southeast-1``, ``WD_BAILIAN_TTS_URL`` (an optional full endpoint override) must be an http(s) URL naming a host, and
  ``WD_BAILIAN_TTS_VOICES`` has the ``WD_AUDIO_CACHE_VOICES`` shape and must name both accents under ``bailian``;
  ``Settings.bailian_tts_url`` holds the endpoint in force (the override, else
  ``https://{WorkspaceId}.{region}.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer``, empty without a workspace id);
* ``WD_TZ`` must be a known IANA zone;
* numeric ranges raise :class:`ConfigError`, except ``WD_AI_BATCH_SIZE`` (clamped to 1–12
  because ``content_v1.json`` has ``items.maxItems: 12``), ``WD_AI_FALLBACK_BATCH_SIZE`` (the same
  1–12 rule) and ``WD_AI_CONCURRENCY`` (clamped to 1–3), which are clamped with a warning as
  DEPLOY §4 specifies;
* ``WD_SEED_PATH`` defaults to ``<repo>/data/seed/vocab.jsonl.gz`` resolved from the
  installed package (``Path(wd.__file__).parents[2]``), correct for the editable install;
* the fallback provider (docs/AI_FALLBACK_MODEL.md §4.3, CLAUDE_INTEGRATION §10.1): ``WD_AI_FALLBACK_BASE_URL``
  follows the ``WD_PUBLIC_URL`` rule (``http://`` or ``https://`` plus a host; plain ``http://`` to a non-loopback
  host only warns — the bearer key would travel in cleartext), ``WD_AI_FALLBACK_API_KEY_FILE`` must be an existing
  readable regular file (a group/other-readable mode warns), ``WD_AI_FALLBACK_PRICE_JSON`` names exactly ``input`` /
  ``output`` (both, when the object is not empty) and optionally ``cache_read``; ``WD_AI_FALLBACK_KINDS`` defaults to
  ``content,lookup,consolidate`` (an empty or blank value — ``""``, ``" "``, ``","`` — is the default; ``svg`` is never
  accepted) and
  ``WD_AI_FALLBACK_BATCH_SIZE`` (words per ``generate_content`` call while the fallback takes the group, default 5)
  is clamped like ``WD_AI_BATCH_SIZE``; ``openai_http`` mode with a kind removed from ``WD_AI_FALLBACK_KINDS`` starts
  with a warning that those jobs (and SVG / dance jobs, always) wait indefinitely;
* sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.2, DEPLOY §4): ``WD_REGISTRATION_MODE`` gains ``verified``;
  ``WD_SMS_PROVIDER`` is ``off`` / ``aliyun_verify`` and ``aliyun_verify`` refuses to start without ``WD_ALIYUN_ACCESS_KEY_ID``,
  ``WD_ALIYUN_ACCESS_KEY_SECRET_FILE`` and ``WD_ALIYUN_SMS_SIGN_NAME``; ``WD_MAIL_PROVIDER`` is ``smtp`` / ``aliyun_dm`` and
  ``aliyun_dm`` needs the same key id + secret file plus ``WD_SMTP_FROM`` (its sender address); the secret file follows the
  ``WD_AI_FALLBACK_API_KEY_FILE`` rule (an existing readable regular file, a group/other-readable mode warns; its first line is
  read at call time); ``WD_SMS_DAILY_CAP`` / ``WD_SMS_HOURLY_CAP`` are 0–100000 (0 = the cap is already reached),
  ``WD_CODE_IP_HOURLY`` 1–100000, ``WD_PHONE_STALE_DAYS`` 1–3650, ``WD_CAPTCHA`` ``on`` / ``off`` (the image captcha gates only
  the public code sends, endpoints 80 / 90) and ``WD_AI_USER_DAILY_WORDS`` 0–100000 (0 = unlimited; the per-user AI quota
  public sign-up relies on). An unchanged ``.env`` keeps today's behaviour: every default is the pre-0018 one;
* third-party sign-in (docs/AUTH_SIGNUP_DESIGN.md §5.3, API.md §3.3, slice 2-A — everything ships dark): ``WD_WECHAT_APPID`` needs
  ``WD_WECHAT_SECRET_FILE`` (``Settings.wechat_configured``), ``WD_QQ_APPID`` needs ``WD_QQ_KEY_FILE`` and ``WD_QQ_CALLBACK_URL``
  (``qq_configured``), ``WD_APPLE_CLIENT_ID`` needs ``WD_APPLE_CALLBACK_URL`` (``apple_configured``) — an appid without its secret
  file / callback is a :class:`ConfigError` like ``aliyun_verify`` without its key; the two secret FILES follow the
  ``WD_ALIYUN_ACCESS_KEY_SECRET_FILE`` rule (must exist and be readable at startup, group/other-readable warns, the first line is read
  at call time and never lands in ``Settings``); the two callback URLs must be ``https://`` (``http://`` only under ``WD_DEV=1``);
  ``WD_WECHAT_ENV`` is ``release`` / ``trial`` / ``develop``; ``WD_AUTH_FAKE_PROVIDERS=1`` (the fake WeChat / QQ / Apple clients and the
  fake consent routes) refuses to start without ``WD_DEV=1``. Nothing here is a secret for ``GET /api/admin/config`` — the paths are
  shown, the files' contents never read into Settings (``SECRET_KEYS`` unchanged).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
from dataclasses import dataclass, field, fields
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Mapping

from . import clock as _clock

log = logging.getLogger("wd.config")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = Path("/home/sqin/word-dance-data")
DEFAULT_SEED_PATH = REPO_ROOT / "data" / "seed" / "vocab.jsonl.gz"
DEFAULT_FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

REGISTRATION_MODES = ("open", "invite", "closed", "verified")  # verified = a phone / e-mail code creates the account (docs/AUTH_SIGNUP_DESIGN.md)
SMTP_TLS_MODES = ("starttls", "ssl", "none")
# sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.2)
SMS_PROVIDERS = ("off", "aliyun_verify")  # aliyun_verify = Aliyun 号码认证 SendSmsVerifyCode (delivery/sms.py)
MAIL_PROVIDERS = ("smtp", "aliyun_dm")  # aliyun_dm = Aliyun DirectMail SingleSendMail with the WD_ALIYUN_* key and WD_SMTP_FROM as the sender
CAPTCHA_MODES = ("on", "off")  # the self-hosted image captcha in front of the public code sends (endpoints 79, 80, 90)
# third-party sign-in (docs/AUTH_SIGNUP_DESIGN.md §5.3, slice 2-A)
WECHAT_ENVS = ("release", "trial", "develop")  # WD_WECHAT_ENV — the `env_version` of the 小程序码 (develop / trial while the mini program is unpublished)
COOKIE_SECURE_MODES = ("auto", "1", "0")
IMAGE_PROVIDERS = ("wikimedia", "openverse", "pixabay", "pexels")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LOG_FORMATS = ("json", "text")
# fallback provider (docs/AI_FALLBACK_MODEL.md §4.3, CLAUDE_INTEGRATION §10)
AI_PROVIDER_MODES = ("claude_cli", "openai_http", "auto", "split")  # split = learner-triggered kinds on the fallback, the operator's work on the CLI
FALLBACK_KINDS = ("none", "openai_http")
FALLBACK_DIALECTS = ("auto", "zhipu", "bailian", "deepseek", "generic")
FALLBACK_JSON_MODES = ("auto", "json_object", "json_schema")
FALLBACK_THINKING_MODES = ("off", "on", "default")
FALLBACK_TASK_KINDS = ("content", "lookup", "consolidate")  # `svg`, `dance` and `probe` are never routed by WD_AI_FALLBACK_KINDS
FALLBACK_PRICE_KEYS = frozenset({"input", "output", "cache_read"})  # WD_AI_FALLBACK_PRICE_JSON names (CNY per million tokens)
AUDIO_PROVIDERS = ("auto", "say", "youdao", "bailian", "cache", "off")  # WD_AUDIO_PROVIDER (wd/audio.py): auto = say when SAY_BIN exists, else off (never bailian); cache = another host's say clips, read-only
AUDIO_ACCENTS = ("en-US", "en-GB")  # mirrors wd.audio.ACCENTS (which imports this module)
SAY_BIN = "/usr/bin/say"  # macOS text-to-speech; its presence decides the `auto` audio provider
# 阿里云百炼 cloud TTS (wd/audio.py `bailian`, slice server-audio-2): keys and models are per region; the TTS host is the 业务空间's own
BAILIAN_REGIONS = ("cn-beijing", "ap-southeast-1")  # WD_BAILIAN_REGION — 华北2（北京）/ 新加坡, the two regions with the TTS models
BAILIAN_TTS_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"  # the synchronous CosyVoice / Qwen-Audio-TTS endpoint path
DEFAULT_BAILIAN_TTS_MODEL = "cosyvoice-v3-flash"  # 1 元 / 万字符 (北京); qwen-audio-3.1-tts-flash is the documented alternative on the same endpoint
DEFAULT_BAILIAN_TTS_VOICES = "en-US=loongabby_v3;en-GB=loongemily_v3"  # CosyVoice v3 system voices: 美式英文女 / 英式英文女

# values masked as "***" by GET /api/admin/config (API.md 73) and never logged
SECRET_KEYS = frozenset(
    {
        "WD_SECRET_KEY",
        "WD_SMTP_PASSWORD",
        "WD_OPENVERSE_CLIENT_SECRET",
        "WD_PIXABAY_KEY",
        "WD_PEXELS_KEY",
        "WD_ADMIN_PASSWORD",
        "WD_AI_FALLBACK_API_KEY",
        "WD_ALIYUN_ACCESS_KEY_ID",
    }
)


class ConfigError(ValueError):
    """An invalid ``WD_*`` value; the message names the variable."""



def parse_cache_voices(raw: str, name: str = "WD_AUDIO_CACHE_VOICES") -> dict[str, str]:
    """``WD_AUDIO_CACHE_VOICES`` — ``en-US=Ava (Premium);en-GB=Serena (Premium)`` → ``{accent: voice}`` (the names exactly as
    ``say -v '?'`` prints them on the host that synthesises); :class:`ConfigError` on a malformed pair, an unknown accent or a repeat.
    ``WD_BAILIAN_TTS_VOICES`` (``en-US=loongabby_v3;en-GB=loongemily_v3``) has the same shape — ``name`` is the variable the error names."""
    out: dict[str, str] = {}
    for part in (p.strip() for p in raw.split(";")):
        if not part:
            continue
        accent, sep, voice = (x.strip() for x in part.partition("="))
        if not sep or accent not in AUDIO_ACCENTS or not voice:
            hint = "(as `say -v '?'` lists them on the host that synthesises)" if name == "WD_AUDIO_CACHE_VOICES" else "(a 百炼 voice id of the model, e.g. loongabby_v3)"
            raise ConfigError(f"{name} must be `en-US=<voice>;en-GB=<voice>` {hint}, got {part!r}")
        if accent in out:
            raise ConfigError(f"{name} names {accent} twice")
        out[accent] = voice
    return out


def bailian_endpoint(workspace_id: str, region: str) -> str:
    """The 百炼 TTS endpoint of a 业务空间 in a region: ``https://{WorkspaceId}.{region}.maas.aliyuncs.com`` + :data:`BAILIAN_TTS_PATH`
    (the production host form the Base-URL page recommends; ``dashscope.aliyuncs.com`` is the legacy one)."""
    return f"https://{workspace_id}.{region}.maas.aliyuncs.com{BAILIAN_TTS_PATH}"

@dataclass(frozen=True)
class Settings:
    """Effective configuration. Field names drop the ``WD_`` prefix and are lower-case."""

    # --- paths / network ------------------------------------------------------------
    data_dir: Path = DEFAULT_DATA_DIR
    db_path: Path = DEFAULT_DATA_DIR / "word-dance.db"
    host: str = "0.0.0.0"
    port: int = 8000
    public_url: str = ""
    seed_path: Path = DEFAULT_SEED_PATH
    frontend_dist: Path = DEFAULT_FRONTEND_DIST
    trust_proxy: bool = False
    cookie_secure: str = "auto"
    dev: bool = False
    secret_key: str = ""
    tz: str = "Asia/Shanghai"
    registration_mode: str = "invite"
    session_days: int = 30
    max_body_bytes: int = 1_048_576
    worker_enabled: bool = True
    tick_seconds: int = 60
    prebuild_hours: int = 3
    contact_email: str = ""
    # --- claude ---------------------------------------------------------------------
    claude_bin: str = "/home/sqin/.local/bin/claude"
    claude_home: str = ""
    claude_path: str = "/home/sqin/.local/bin:/usr/local/bin:/usr/bin:/bin"
    claude_cwd: Path = DEFAULT_DATA_DIR / "claude-cwd"
    ai_enabled: bool = True
    ai_model: str = "sonnet"
    ai_cli_fallback_model: str = ""  # the CLI's own --fallback-model (Claude ↔ Claude only); was WD_AI_FALLBACK_MODEL before 0010
    ai_extra_args: str = ""
    ai_batch_size: int = 10
    ai_concurrency: int = 1
    ai_timeout_content_sec: int = 180
    ai_timeout_lookup_sec: int = 120
    ai_timeout_consolidate_sec: int = 240
    ai_timeout_svg_sec: int = 120
    ai_timeout_dance_sec: int = 120
    ai_budget_content: float = 0.25
    ai_budget_lookup: float = 0.15
    ai_budget_consolidate: float = 0.40
    ai_budget_svg: float = 0.10
    ai_budget_dance: float = 0.25
    ai_daily_budget_usd: float = 3.00
    ai_monthly_budget_usd: float = 40.00
    ai_prewarm_daily_budget_usd: float = 1.00
    ai_hourly_call_cap: int = 60
    ai_svg_daily_budget_usd: float = 0.50
    ai_dance_daily_budget_usd: float = 0.50
    ai_user_daily_words: int = 80  # words per learner per UTC day that may trigger content generation (0 = unlimited; docs/AUTH_SIGNUP_DESIGN.md D2, PUBLIC_LAUNCH A1/A2)
    ai_log_keep_days: int = 14
    # --- fallback provider + automatic failover (docs/AI_FALLBACK_MODEL.md §4.3) --------
    ai_provider: str = "claude_cli"  # claude_cli = today · openai_http = fallback only · auto = claude + automatic failover · split = learners' kinds on the fallback, prewarm / svg / dance on claude
    ai_fallback_kind: str = "none"  # none | openai_http
    ai_fallback_base_url: str = ""  # e.g. https://open.bigmodel.cn/api/paas/v4
    ai_fallback_api_key: str = ""  # secret; prefer the 0600 file below
    ai_fallback_api_key_file: str = ""
    ai_fallback_model: str = ""  # vendor model id, e.g. glm-4.7-flash
    ai_fallback_dialect: str = "auto"  # auto | zhipu | bailian | deepseek | generic
    ai_fallback_json_mode: str = "auto"  # auto | json_object | json_schema
    ai_fallback_thinking: str = "off"  # off | on | default
    ai_fallback_timeout_scale: float = 1.5
    ai_fallback_max_output_tokens: int = 0  # 0 = the adapter's per-kind table
    ai_fallback_hourly_call_cap: int = 40
    ai_fallback_batch_size: int = 5  # words per generate_content call while the fallback takes the group (effective min(WD_AI_BATCH_SIZE, this))
    ai_fallback_kinds: tuple[str, ...] = ("content", "lookup", "consolidate")
    ai_fallback_prewarm: bool = False
    ai_fallback_price_json: str = ""  # {"input": CNY per 1M tokens, "output": …}; empty = free
    ai_cny_per_usd: float = 7.2
    ai_failover_cooldown_min: int = 30
    ai_failover_probe_every_min: int = 30
    ai_failover_overloaded_after: int = 3
    ai_failover_timeout_after: int = 2
    ai_failover_network_after: int = 2
    ecdict_db_path: Path | None = None
    # --- images ---------------------------------------------------------------------
    images_enabled: bool = True
    image_providers: tuple[str, ...] = ("wikimedia", "openverse")
    image_kid_stages: tuple[str, ...] = ()  # stage codes drawn in the child style (+ the illustration-first round); empty = off (PLAN §5.1 C3)
    svg_via_claude: bool = True
    image_max_bytes: int = 8_000_000
    image_max_edge: int = 800
    wikimedia_min_interval_ms: int = 1000
    wikimedia_daily_limit: int = 2000
    openverse_minute_limit: int = 15
    openverse_daily_limit: int = 160
    openverse_client_id: str = ""
    openverse_client_secret: str = ""
    pixabay_key: str = ""
    pexels_key: str = ""
    # --- pronunciation audio (wd/audio.py, API.md 76) ----------------------------------
    audio_provider: str = "auto"  # auto | say | youdao | bailian | cache | off — server-side clips for clients without an English voice
    audio_say_voice: str = ""  # macOS `say -v` voice for both accents; empty = the best installed one of audio.PREFERRED_VOICES
    audio_cache_voices: str = ""  # provider cache: "en-US=Ava (Premium);en-GB=Serena (Premium)" — the voices the mirrored say clips were made with
    audio_cache_mb: int = 256  # cap of the clip cache under audio/; the least recently played clips are removed beyond it
    # --- pronunciation: 百炼 cloud TTS (provider bailian, slice server-audio-2; dark until WD_AUDIO_PROVIDER=bailian) -----------
    bailian_api_key_file: str = ""  # 0600 file whose first line is the 百炼 API key (sk-…), read at call time; required with bailian
    bailian_workspace_id: str = ""  # the 业务空间 id — the TTS host is {WorkspaceId}.{region}.maas.aliyuncs.com; required with bailian
    bailian_region: str = "cn-beijing"  # cn-beijing | ap-southeast-1 (keys and models are per region)
    bailian_tts_url: str = ""  # the endpoint in force: WD_BAILIAN_TTS_URL when set, else derived from the workspace id + region (empty without one)
    bailian_tts_model: str = DEFAULT_BAILIAN_TTS_MODEL  # the `model` field: cosyvoice-v3-flash (1 元/万字符) or qwen-audio-3.1-tts-flash
    bailian_tts_voices: str = DEFAULT_BAILIAN_TTS_VOICES  # one voice per accent in the WD_AUDIO_CACHE_VOICES shape; both accents required with bailian
    # --- e-mail ---------------------------------------------------------------------
    mail_provider: str = "smtp"  # smtp | aliyun_dm — aliyun_dm sends through DirectMail with the WD_ALIYUN_* key; WD_SMTP_FROM stays the sender
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # the sender address of both mail providers (the DirectMail AccountName is its address part)
    smtp_tls: str = "starttls"
    # --- sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.2) --------------
    sms_provider: str = "off"  # off | aliyun_verify — phone codes are sent only when a provider is set (ServerFlags.sms_enabled)
    aliyun_access_key_id: str = ""  # RAM user AccessKey ID shared by aliyun_verify and aliyun_dm (masked by GET /api/admin/config)
    aliyun_access_key_secret_file: str = ""  # 0600 file whose first line is the AccessKey secret, read at call time
    aliyun_sms_sign_name: str = ""  # the system signature shown in the 号码认证 console (the SendSmsVerifyCode SignName)
    sms_daily_cap: int = 200  # phone codes per WD_TZ day for the whole site (0 = the cap is already reached); 503 sms_budget_exhausted beyond it
    sms_hourly_cap: int = 40  # phone codes per UTC hour for the whole site
    code_ip_hourly: int = 20  # verification-code sends per client IP per hour (endpoints 80, 85, 90)
    phone_stale_days: int = 90  # a phone identity unused this long needs a second factor at code login (the stale-phone challenge)
    captcha: str = "on"  # on | off — the image captcha in front of the public code sends when no session exists (tests set off)
    # --- third-party sign-in (docs/AUTH_SIGNUP_DESIGN.md §5.3, API.md §3.3 — slice 2-A, dark until the owner sets them) ---
    wechat_appid: str = ""  # the mini program's AppID; with wechat_secret_file turns the WeChat bridge on (endpoints 112–116)
    wechat_secret_file: str = ""  # 0600 file whose first line is the AppSecret, read at call time (delivery/wechat.py)
    wechat_env: str = "release"  # release | trial | develop — the env_version of the 小程序码 (endpoint 114)
    wechat_page: str = "pages/confirm/confirm"  # the mini-program page the 小程序码 opens
    qq_appid: str = ""  # QQ 互联 网站应用 APP ID; with qq_key_file + qq_callback_url turns QQ login on (118 / 119)
    qq_key_file: str = ""  # 0600 file whose first line is the APP Key
    qq_callback_url: str = ""  # the registered callback, https://<filed domain>/api/auth/qq/callback (the relay host proxies it here)
    apple_client_id: str = ""  # the Services ID (web); with apple_callback_url turns Sign in with Apple on (120 / 121)
    apple_app_id: str = ""  # the iOS bundle id, also accepted as `aud` — read but unused until the iOS Capacitor plugin exists
    apple_callback_url: str = ""  # https://<host>/api/auth/apple/callback, registered as a Return URL (must be https)
    auth_fake_providers: bool = False  # dev only (WD_DEV=1): the fake WeChat / QQ / Apple clients + the fake consent routes; the three flags read true
    # --- logging / backups / misc ---------------------------------------------------
    log_level: str = "INFO"
    log_format: str = "json"
    log_file: str = ""
    backup_keep_daily: int = 14
    backup_keep_weekly: int = 8
    admin_username: str = ""
    admin_password: str = ""
    dev_real_claude: bool = False
    smoke_mock_http: bool = False
    # which WD_* variables were present in the environment (for GET /api/admin/config `source`)
    env_sources: frozenset[str] = field(default_factory=frozenset, repr=False, compare=False)

    # ------------------------------------------------------------------ derived values
    @property
    def public_url_is_https(self) -> bool:
        return self.public_url.lower().startswith("https://")

    @property
    def cookie_secure_effective(self) -> bool:
        """``WD_COOKIE_SECURE``: ``1`` forces Secure, ``0`` disables it, ``auto`` follows an https ``WD_PUBLIC_URL``."""
        if self.cookie_secure == "1":
            return True
        if self.cookie_secure == "0":
            return False
        return self.public_url_is_https

    @property
    def public_origin(self) -> str | None:
        """Scheme + host[:port] of ``WD_PUBLIC_URL`` (accepted as a CSRF Origin, API.md §1), or None."""
        return origin_of(self.public_url) if self.public_url else None

    @property
    def email_configured(self) -> bool:
        """The e-mail channel exists when the selected mail provider's variables are set (DEPLOY §4): ``smtp`` → host and
        from-address; ``aliyun_dm`` → the Aliyun key id, its secret file and the from-address (the DirectMail sender)."""
        if self.mail_provider == "aliyun_dm":
            return bool(self.aliyun_access_key_id and self.aliyun_access_key_secret_file and self.smtp_from)
        return bool(self.smtp_host and self.smtp_from)

    @property
    def sms_configured(self) -> bool:
        """Phone verification codes can be sent: ``WD_SMS_PROVIDER`` is not ``off`` (``from_env`` refused to start without the
        provider's key id, secret file and signature, so no further check is needed here)."""
        return self.sms_provider != "off"

    @property
    def wechat_configured(self) -> bool:
        """The WeChat mini-program bridge (API.md 112–116) is on: ``WD_WECHAT_APPID`` and ``WD_WECHAT_SECRET_FILE`` are both set
        (``from_env`` refused an appid without the file). The fake providers of ``WD_AUTH_FAKE_PROVIDERS`` are NOT counted here —
        ``ServerFlags.wechat_enabled`` is ``wechat_configured or auth_fake_providers``."""
        return bool(self.wechat_appid and self.wechat_secret_file)

    @property
    def qq_configured(self) -> bool:
        """QQ 互联 login (API.md 118 / 119) is on: ``WD_QQ_APPID``, ``WD_QQ_KEY_FILE`` and ``WD_QQ_CALLBACK_URL`` are all set."""
        return bool(self.qq_appid and self.qq_key_file and self.qq_callback_url)

    @property
    def apple_configured(self) -> bool:
        """Sign in with Apple, web redirect flow (API.md 120 / 121), is on: ``WD_APPLE_CLIENT_ID`` and ``WD_APPLE_CALLBACK_URL`` are set."""
        return bool(self.apple_client_id and self.apple_callback_url)

    @property
    def fallback_configured(self) -> bool:
        """A fallback provider is fully configured: kind, base URL, model and a key (or a key file)."""
        return (
            self.ai_fallback_kind == "openai_http"
            and bool(self.ai_fallback_base_url)
            and bool(self.ai_fallback_model)
            and bool(self.ai_fallback_api_key or self.ai_fallback_api_key_file)
        )

    @property
    def claude_home_effective(self) -> str:
        return self.claude_home or os.environ.get("HOME", "/home/sqin")

    @property
    def contact_email_effective(self) -> str:
        return self.contact_email or "admin@localhost"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def claude_logs_dir(self) -> Path:
        return self.data_dir / "claude-logs"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def audio_dir(self) -> Path:
        """Cached pronunciation clips (``audio/<2hex>/<sha256>.m4a|.mp3``, wd/audio.py); safe to delete."""
        return self.data_dir / "audio"

    @property
    def audio_provider_effective(self) -> str:
        """``WD_AUDIO_PROVIDER`` with ``auto`` resolved: ``say`` when ``SAY_BIN`` exists on this host, else ``off``."""
        if self.audio_provider != "auto":
            return self.audio_provider
        return "say" if Path(SAY_BIN).is_file() else "off"

    @property
    def audio_cache_voice_map(self) -> dict[str, str]:
        """``accent → say voice`` of ``WD_AUDIO_CACHE_VOICES`` (validated by :func:`parse_cache_voices` in ``from_env``)."""
        return parse_cache_voices(self.audio_cache_voices)

    @property
    def bailian_voice_map(self) -> dict[str, str]:
        """``accent → 百炼 voice`` of ``WD_BAILIAN_TTS_VOICES`` (validated in ``from_env``; both accents present under ``bailian``)."""
        return parse_cache_voices(self.bailian_tts_voices, name="WD_BAILIAN_TTS_VOICES")

    def runtime_dirs(self) -> tuple[Path, ...]:
        """Directories that must exist under the data dir (DEPLOY §1)."""
        return (self.data_dir, self.images_dir, self.claude_cwd, self.claude_logs_dir, self.backups_dir, self.tmp_dir, self.audio_dir)

    # ------------------------------------------------------------------- constructors
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Build and validate the settings from ``env`` (default ``os.environ``)."""
        e = dict(os.environ if env is None else env)
        present = frozenset(k for k in e if k.startswith("WD_"))

        def raw(name: str) -> str | None:
            v = e.get(name)
            return v if v is not None and v != "" else None

        def text(name: str, default: str) -> str:
            v = raw(name)
            return default if v is None else v.strip()

        def flag(name: str, default: bool) -> bool:
            v = raw(name)
            if v is None:
                return default
            s = v.strip().lower()
            if s in ("1", "true", "yes", "on"):
                return True
            if s in ("0", "false", "no", "off"):
                return False
            raise ConfigError(f"{name} must be 0 or 1, got {v!r}")

        def integer(name: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
            v = raw(name)
            if v is None:
                return default
            try:
                n = int(v.strip())
            except ValueError:
                raise ConfigError(f"{name} must be an integer, got {v!r}") from None
            if (lo is not None and n < lo) or (hi is not None and n > hi):
                raise ConfigError(f"{name} must be between {lo} and {hi}, got {n}")
            return n

        def clamped(name: str, default: int, lo: int, hi: int) -> int:
            v = raw(name)
            if v is None:
                return default
            try:
                n = int(v.strip())
            except ValueError:
                raise ConfigError(f"{name} must be an integer, got {v!r}") from None
            c = max(lo, min(hi, n))
            if c != n:
                log.warning("%s=%d is outside %d–%d; clamped to %d", name, n, lo, hi, c)
            return c

        def money(name: str, default: float) -> float:
            v = raw(name)
            if v is None:
                return default
            try:
                x = float(v.strip())
            except ValueError:
                raise ConfigError(f"{name} must be a number, got {v!r}") from None
            if x < 0:
                raise ConfigError(f"{name} must be >= 0, got {x}")
            return x

        def choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
            v = text(name, default)
            if v not in allowed:
                raise ConfigError(f"{name} must be one of {', '.join(allowed)}, got {v!r}")
            return v

        def number(name: str, default: float, lo: float, hi: float) -> float:
            v = raw(name)
            if v is None:
                return default
            try:
                x = float(v.strip())
            except ValueError:
                raise ConfigError(f"{name} must be a number, got {v!r}") from None
            if x < lo or x > hi:
                raise ConfigError(f"{name} must be between {lo:g} and {hi:g}, got {x:g}")
            return x

        data_dir = Path(text("WD_DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser().resolve()
        db_path = Path(text("WD_DB_PATH", str(data_dir / "word-dance.db"))).expanduser().resolve()
        seed_path = Path(text("WD_SEED_PATH", str(DEFAULT_SEED_PATH))).expanduser().resolve()
        frontend_dist = Path(text("WD_FRONTEND_DIST", str(DEFAULT_FRONTEND_DIST))).expanduser().resolve()
        claude_cwd = Path(text("WD_CLAUDE_CWD", str(data_dir / "claude-cwd"))).expanduser().resolve()
        ecdict_raw = raw("WD_ECDICT_DB_PATH")
        ecdict_db_path = Path(ecdict_raw.strip()).expanduser().resolve() if ecdict_raw else None

        tz = text("WD_TZ", "Asia/Shanghai")
        if not _clock.is_valid_timezone(tz):
            raise ConfigError(f"WD_TZ is not a known IANA timezone: {tz!r}")

        public_url = text("WD_PUBLIC_URL", "").rstrip("/")
        if public_url and not (public_url.startswith("http://") or public_url.startswith("https://")):
            raise ConfigError(f"WD_PUBLIC_URL must start with http:// or https://, got {public_url!r}")

        secret_key = text("WD_SECRET_KEY", "")
        if not secret_key:
            # DEPLOY §4: must be non-empty in production (install.sh generates it). A per-process random key keeps
            # dev/test instances working; only unexpired e-mail codes depend on it.
            secret_key = "ephemeral-" + secrets.token_hex(32)
            log.warning("WD_SECRET_KEY is not set; using a random per-process key (e-mail codes will not survive a restart)")

        providers_raw = text("WD_IMAGE_PROVIDERS", "wikimedia,openverse")
        providers: list[str] = []
        for p in (x.strip().lower() for x in providers_raw.split(",")):
            if not p:
                continue
            if p not in IMAGE_PROVIDERS:
                raise ConfigError(f"WD_IMAGE_PROVIDERS contains an unknown provider {p!r}; allowed: {', '.join(IMAGE_PROVIDERS)}")
            if p not in providers:
                providers.append(p)
        pixabay_key = text("WD_PIXABAY_KEY", "")
        pexels_key = text("WD_PEXELS_KEY", "")
        if pixabay_key and "pixabay" not in providers:
            providers.append("pixabay")  # keyed providers are appended to the chain (DEPLOY §4)
        if pexels_key and "pexels" not in providers:
            providers.append("pexels")

        # WD_IMAGE_KID_STAGES: the stage codes whose words get the child picture style (images/style.style_for; DEPLOY §4).
        # Empty = off — the default until the pilot of design/images/SYNTHESIS.md §3.6 clears it for `xs`. The import is
        # function-level on purpose: schemas imports only pydantic + clock and config only clock, so there is no cycle, but
        # config must stay importable before the rest of the package.
        kid_raw = text("WD_IMAGE_KID_STAGES", "")
        kid_stages: list[str] = []
        if kid_raw.strip():
            from .schemas import STAGE_ORDER

            for code in (x.strip().lower() for x in kid_raw.split(",")):
                if not code:
                    continue
                if code not in STAGE_ORDER:
                    raise ConfigError(f"WD_IMAGE_KID_STAGES contains an unknown stage {code!r}; allowed: {', '.join(STAGE_ORDER)}")
                if code not in kid_stages:
                    kid_stages.append(code)

        # WD_CLAUDE_BIN (DEPLOY §4): a bare command name stays a PATH lookup in the child (runner.claude_env); a path with a
        # separator is made absolute against the start-up working directory like every other path setting above, because
        # the CLI is spawned in `claude_cwd`, not where the service started — a relative `backend/tests/fake_claude.py`
        # used to fail there with `spawn_error` and pause Claude for the cooldown (the PLAN §6 S5 rehearsal command).
        # An absolute path is kept verbatim: no symlink resolution, the CLI may locate its install through argv[0].
        claude_bin = text("WD_CLAUDE_BIN", "/home/sqin/.local/bin/claude")
        if os.sep in claude_bin:
            claude_bin = os.path.expanduser(claude_bin)
            if not os.path.isabs(claude_bin):
                claude_bin = os.path.abspath(claude_bin)

        log_level = text("WD_LOG_LEVEL", "INFO").upper()
        if log_level not in LOG_LEVELS:
            raise ConfigError(f"WD_LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}, got {log_level!r}")

        # fallback provider (docs/AI_FALLBACK_MODEL.md §4.3)
        audio_provider = choice("WD_AUDIO_PROVIDER", "auto", AUDIO_PROVIDERS)
        audio_cache_voices = text("WD_AUDIO_CACHE_VOICES", "")
        if set(parse_cache_voices(audio_cache_voices)) != set(AUDIO_ACCENTS) and audio_provider == "cache":
            raise ConfigError(
                "WD_AUDIO_PROVIDER=cache needs WD_AUDIO_CACHE_VOICES naming both accents, e.g. `en-US=Ava (Premium);en-GB=Serena (Premium)` "
                "— the voices the mirrored clips were made with (`wd audio-voices` on the host that synthesises)"
            )
        ai_provider = choice("WD_AI_PROVIDER", "claude_cli", AI_PROVIDER_MODES)
        fallback_kind = choice("WD_AI_FALLBACK_KIND", "none", FALLBACK_KINDS)
        fallback_model = text("WD_AI_FALLBACK_MODEL", "")
        fallback_base_url = text("WD_AI_FALLBACK_BASE_URL", "").rstrip("/")
        if fallback_base_url:
            # the WD_PUBLIC_URL rule (CLAUDE_INTEGRATION §10.1): httpx raises UnsupportedProtocol / InvalidURL before any
            # I/O for a scheme-less or ftp:// value, which the adapter classifies as a soft `network:` failure — every
            # group would defer forever instead of the service refusing to start. http:// stays allowed: the mock
            # server and local gateways listen on loopback; elsewhere the bearer key would travel in cleartext.
            if not fallback_base_url.lower().startswith(("http://", "https://")) or origin_of(fallback_base_url) is None:
                raise ConfigError(f"WD_AI_FALLBACK_BASE_URL must start with http:// or https:// and name a host, got {fallback_base_url!r}")
            if fallback_base_url.lower().startswith("http://") and not is_loopback_url(fallback_base_url):
                log.warning("WD_AI_FALLBACK_BASE_URL=%s uses plain http:// to a non-loopback host; the bearer key travels in cleartext", fallback_base_url)
        fallback_key = text("WD_AI_FALLBACK_API_KEY", "")
        fallback_key_file = text("WD_AI_FALLBACK_API_KEY_FILE", "")
        if fallback_key_file:
            # checked here, not at the first call: a typo would otherwise count as a configured fallback until a failover
            # reruns a group on it and gets `not_found: fallback not configured (api_key missing)` (CLAUDE_INTEGRATION §10.2)
            key_path = Path(fallback_key_file).expanduser()
            if not key_path.is_file():
                raise ConfigError(f"WD_AI_FALLBACK_API_KEY_FILE must name an existing regular file, got {fallback_key_file!r}")
            if not os.access(key_path, os.R_OK):
                raise ConfigError(f"WD_AI_FALLBACK_API_KEY_FILE is not readable by this user: {fallback_key_file!r}")
            key_mode = stat.S_IMODE(key_path.stat().st_mode)
            if key_mode & 0o077:
                log.warning("WD_AI_FALLBACK_API_KEY_FILE %s is readable by group/others (mode %o); chmod 600 it", fallback_key_file, key_mode)
        if fallback_kind == "none" and fallback_model:
            raise ConfigError(
                "WD_AI_FALLBACK_MODEL now names the fallback provider's model (set WD_AI_FALLBACK_KIND=openai_http); "
                "the Claude CLI --fallback-model moved to WD_AI_CLI_FALLBACK_MODEL"
            )
        fallback_ready = fallback_kind == "openai_http" and bool(fallback_base_url) and bool(fallback_model) and bool(fallback_key or fallback_key_file)
        if ai_provider != "claude_cli" and not fallback_ready:
            raise ConfigError(
                f"WD_AI_PROVIDER={ai_provider} needs WD_AI_FALLBACK_KIND=openai_http, WD_AI_FALLBACK_BASE_URL, WD_AI_FALLBACK_MODEL "
                "and WD_AI_FALLBACK_API_KEY (or WD_AI_FALLBACK_API_KEY_FILE)"
            )
        fallback_kinds: list[str] = []
        for k in (x.strip().lower() for x in text("WD_AI_FALLBACK_KINDS", "content,lookup,consolidate").split(",")):
            if not k:
                continue
            if k not in FALLBACK_TASK_KINDS:
                raise ConfigError(f"WD_AI_FALLBACK_KINDS contains an unsupported kind {k!r}; allowed: {', '.join(FALLBACK_TASK_KINDS)}")
            if k not in fallback_kinds:
                fallback_kinds.append(k)
        if not fallback_kinds:
            # "", " ", ",", " , " … all mean the default (DEPLOY §4 "empty or blank"): an empty list has no legitimate use —
            # auto would still switch to a fallback that serves nothing, openai_http would run nothing at all
            fallback_kinds = list(FALLBACK_TASK_KINDS)
        if ai_provider == "split":
            # the opposite failure of the openai_http case: a kind removed from the list is the operator's work to failover.realtime
            # and runs on the CLI — with the learners' input (a lookup's typed text, a consolidation's notes) that the mode exists to keep away
            exposed = [k for k in FALLBACK_TASK_KINDS if k not in fallback_kinds]
            if exposed:
                log.warning(
                    "WD_AI_PROVIDER=split with WD_AI_FALLBACK_KINDS=%s: learner-triggered %s jobs run on the Claude CLI — the learners' input reaches Claude; add %s back to WD_AI_FALLBACK_KINDS",
                    ",".join(fallback_kinds),
                    "/".join(exposed),
                    "/".join(exposed),
                )
        if ai_provider == "openai_http":
            # the CLI is never spawned in this mode, so a kind the operator removed from the list is never routable:
            # failover.choose answers (None, None) and common.claude_call re-defers the group every 30 minutes
            # (CLAUDE_INTEGRATION §10.1). svg never runs on the fallback. The default list names every routable kind, so
            # this fires only when one was removed. A warning, not a ConfigError: the documented emergency switch must keep working.
            idle = [k for k in FALLBACK_TASK_KINDS if k not in fallback_kinds]
            if idle:
                log.warning(
                    "WD_AI_PROVIDER=openai_http with WD_AI_FALLBACK_KINDS=%s: %s jobs wait indefinitely (svg and dance jobs always do in this mode — "
                    "they never run on the fallback and the CLI is never spawned); add %s back to WD_AI_FALLBACK_KINDS to run them on the fallback",
                    ",".join(fallback_kinds),
                    "/".join(idle),
                    "/".join(idle),
                )
        price_json = text("WD_AI_FALLBACK_PRICE_JSON", "")
        if price_json:
            try:
                price = json.loads(price_json)
            except ValueError:
                raise ConfigError("WD_AI_FALLBACK_PRICE_JSON must be a JSON object such as {\"input\": 0.2, \"output\": 0.8} (CNY per million tokens)") from None
            if not isinstance(price, dict) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 for v in price.values()):
                raise ConfigError("WD_AI_FALLBACK_PRICE_JSON must map price names to non-negative numbers (CNY per million tokens)")
            # the adapter reads input / output / cache_read with .get(…, 0.0): a mis-keyed table would silently record
            # cost_usd 0 for a paid leg and the daily / monthly caps would never see the spend. {} stays the free tier.
            unknown = set(price) - FALLBACK_PRICE_KEYS
            if unknown:
                raise ConfigError(f"WD_AI_FALLBACK_PRICE_JSON has unknown price name(s) {sorted(unknown)}; allowed: input, output, cache_read (CNY per million tokens)")
            if price and not {"input", "output"} <= set(price):
                raise ConfigError('WD_AI_FALLBACK_PRICE_JSON needs both "input" and "output" (write 0 for a free side); "cache_read" is optional')

        # sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.2): the provider preconditions are checked here, at
        # startup, like the fallback provider's — a missing key would otherwise surface as 503 sms_send_failed on the first code
        sms_provider = choice("WD_SMS_PROVIDER", "off", SMS_PROVIDERS)
        mail_provider = choice("WD_MAIL_PROVIDER", "smtp", MAIL_PROVIDERS)
        aliyun_key_id = text("WD_ALIYUN_ACCESS_KEY_ID", "")
        aliyun_secret_file = text("WD_ALIYUN_ACCESS_KEY_SECRET_FILE", "")
        aliyun_sign_name = text("WD_ALIYUN_SMS_SIGN_NAME", "")
        smtp_from = text("WD_SMTP_FROM", "")
        if aliyun_secret_file:
            # the WD_AI_FALLBACK_API_KEY_FILE rule: the file must exist and be readable now; the first line is read at call time
            secret_path = Path(aliyun_secret_file).expanduser()
            if not secret_path.is_file():
                raise ConfigError(f"WD_ALIYUN_ACCESS_KEY_SECRET_FILE must name an existing regular file, got {aliyun_secret_file!r}")
            if not os.access(secret_path, os.R_OK):
                raise ConfigError(f"WD_ALIYUN_ACCESS_KEY_SECRET_FILE is not readable by this user: {aliyun_secret_file!r}")
            secret_mode = stat.S_IMODE(secret_path.stat().st_mode)
            if secret_mode & 0o077:
                log.warning("WD_ALIYUN_ACCESS_KEY_SECRET_FILE %s is readable by group/others (mode %o); chmod 600 it", aliyun_secret_file, secret_mode)
        if sms_provider == "aliyun_verify" and not (aliyun_key_id and aliyun_secret_file and aliyun_sign_name):
            raise ConfigError("WD_SMS_PROVIDER=aliyun_verify needs WD_ALIYUN_ACCESS_KEY_ID, WD_ALIYUN_ACCESS_KEY_SECRET_FILE and WD_ALIYUN_SMS_SIGN_NAME")
        if mail_provider == "aliyun_dm" and not (aliyun_key_id and aliyun_secret_file and smtp_from):
            raise ConfigError("WD_MAIL_PROVIDER=aliyun_dm needs WD_ALIYUN_ACCESS_KEY_ID, WD_ALIYUN_ACCESS_KEY_SECRET_FILE and WD_SMTP_FROM (the DirectMail sender address)")
        if mail_provider == "aliyun_dm" and "@" not in parseaddr(smtp_from)[1]:
            # the DirectMail AccountName is the address part of WD_SMTP_FROM; a bare display name would only fail inside create_app
            raise ConfigError('WD_MAIL_PROVIDER=aliyun_dm needs WD_SMTP_FROM to contain the DirectMail sender address, e.g. "word-Dance <noreply@mail.example.com>"')

        # third-party sign-in (docs/AUTH_SIGNUP_DESIGN.md §5.3, slice 2-A): the same startup-time preconditions as the SMS provider —
        # an appid without its secret file / callback would otherwise surface as 502 provider_error on the first scan / callback
        dev = flag("WD_DEV", False)

        def secret_file(name: str) -> str:
            """A 0600 secret file path (the WD_ALIYUN_ACCESS_KEY_SECRET_FILE rule): must exist and be readable now; the first line is
            read at call time by the delivery module; group/other-readable only warns."""
            path_text = text(name, "")
            if not path_text:
                return ""
            path = Path(path_text).expanduser()
            if not path.is_file():
                raise ConfigError(f"{name} must name an existing regular file, got {path_text!r}")
            if not os.access(path, os.R_OK):
                raise ConfigError(f"{name} is not readable by this user: {path_text!r}")
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                log.warning("%s %s is readable by group/others (mode %o); chmod 600 it", name, path_text, mode)
            return path_text

        def callback_url(name: str) -> str:
            """A registered OAuth callback: https:// with a host (http:// only under WD_DEV=1 — the fake consent flow on a laptop)."""
            url = text(name, "").strip()
            if not url:
                return ""
            lower = url.lower()
            if not lower.startswith(("http://", "https://")) or origin_of(url) is None:
                raise ConfigError(f"{name} must be an https:// URL naming a host, got {url!r}")
            if lower.startswith("http://") and not dev:
                raise ConfigError(f"{name} must start with https:// (http:// is accepted only with WD_DEV=1), got {url!r}")
            return url

        # 百炼 cloud TTS (wd/audio.py `bailian`, slice server-audio-2): the same startup-time preconditions as the SMS provider — a
        # missing key file or workspace id would otherwise surface as 503 `failed` at the first tap. Everything stays dark unless
        # WD_AUDIO_PROVIDER=bailian; the key FILE path is not a secret (the key itself is read at call time, audio.read_key)
        bailian_key_file = secret_file("WD_BAILIAN_API_KEY_FILE")
        bailian_workspace_id = text("WD_BAILIAN_WORKSPACE_ID", "")
        bailian_region = choice("WD_BAILIAN_REGION", "cn-beijing", BAILIAN_REGIONS)
        bailian_tts_url = text("WD_BAILIAN_TTS_URL", "").rstrip("/")
        if bailian_tts_url:
            # the WD_AI_FALLBACK_BASE_URL rule: a scheme-less value would fail every synthesis as a soft `failed`; plain http:// to a
            # host other than loopback (a local mock) would send the bearer key in cleartext
            if not bailian_tts_url.lower().startswith(("http://", "https://")) or origin_of(bailian_tts_url) is None:
                raise ConfigError(f"WD_BAILIAN_TTS_URL must start with http:// or https:// and name a host, got {bailian_tts_url!r}")
            if bailian_tts_url.lower().startswith("http://") and not is_loopback_url(bailian_tts_url):
                log.warning("WD_BAILIAN_TTS_URL=%s uses plain http:// to a non-loopback host; the API key travels in cleartext", bailian_tts_url)
        elif bailian_workspace_id:
            bailian_tts_url = bailian_endpoint(bailian_workspace_id, bailian_region)
        bailian_tts_voices = text("WD_BAILIAN_TTS_VOICES", DEFAULT_BAILIAN_TTS_VOICES)
        bailian_voices = parse_cache_voices(bailian_tts_voices, name="WD_BAILIAN_TTS_VOICES")
        if audio_provider == "bailian":
            if not bailian_key_file:
                raise ConfigError("WD_AUDIO_PROVIDER=bailian needs WD_BAILIAN_API_KEY_FILE (a 0600 file whose first line is the 百炼 API key, sk-…)")
            if not bailian_workspace_id:
                raise ConfigError("WD_AUDIO_PROVIDER=bailian needs WD_BAILIAN_WORKSPACE_ID (the 业务空间 id the TTS host is built from — 百炼控制台 → 业务空间管理)")
            if set(bailian_voices) != set(AUDIO_ACCENTS):
                raise ConfigError(
                    "WD_AUDIO_PROVIDER=bailian needs WD_BAILIAN_TTS_VOICES naming both accents, e.g. `en-US=loongabby_v3;en-GB=loongemily_v3` "
                    "(voices of the model in WD_BAILIAN_TTS_MODEL — the 百炼 音色列表 page)"
                )

        wechat_appid = text("WD_WECHAT_APPID", "")
        wechat_secret_file = secret_file("WD_WECHAT_SECRET_FILE")
        if wechat_appid and not wechat_secret_file:
            raise ConfigError("WD_WECHAT_APPID needs WD_WECHAT_SECRET_FILE (a 0600 file whose first line is the mini program's AppSecret)")
        qq_appid = text("WD_QQ_APPID", "")
        qq_key_file = secret_file("WD_QQ_KEY_FILE")
        qq_callback_url = callback_url("WD_QQ_CALLBACK_URL")
        if qq_appid and not (qq_key_file and qq_callback_url):
            raise ConfigError("WD_QQ_APPID needs WD_QQ_KEY_FILE (a 0600 file whose first line is the APP Key) and WD_QQ_CALLBACK_URL (the registered callback)")
        apple_client_id = text("WD_APPLE_CLIENT_ID", "")
        apple_callback_url = callback_url("WD_APPLE_CALLBACK_URL")
        if apple_client_id and not apple_callback_url:
            raise ConfigError("WD_APPLE_CLIENT_ID needs WD_APPLE_CALLBACK_URL (the Return URL registered for the Services ID)")
        auth_fake_providers = flag("WD_AUTH_FAKE_PROVIDERS", False)
        if auth_fake_providers and not dev:
            # unlike WD_SMOKE_MOCK_HTTP (ignored with a warning) this is refused: the fake consent pages would sign anyone in as anyone
            raise ConfigError("WD_AUTH_FAKE_PROVIDERS=1 needs WD_DEV=1 (a production instance never installs the fake WeChat / QQ / Apple providers)")

        return cls(
            data_dir=data_dir,
            db_path=db_path,
            host=text("WD_HOST", "0.0.0.0"),
            port=integer("WD_PORT", 8000, 1, 65535),
            public_url=public_url,
            seed_path=seed_path,
            frontend_dist=frontend_dist,
            trust_proxy=flag("WD_TRUST_PROXY", False),
            cookie_secure=choice("WD_COOKIE_SECURE", "auto", COOKIE_SECURE_MODES),
            dev=dev,
            secret_key=secret_key,
            tz=tz,
            registration_mode=choice("WD_REGISTRATION_MODE", "invite", REGISTRATION_MODES),
            session_days=integer("WD_SESSION_DAYS", 30, 1, 3650),
            max_body_bytes=integer("WD_MAX_BODY_BYTES", 1_048_576, 1024, 1 << 30),
            worker_enabled=flag("WD_WORKER_ENABLED", True),
            tick_seconds=integer("WD_TICK_SECONDS", 60, 1, 3600),
            prebuild_hours=integer("WD_PREBUILD_HOURS", 3, 0, 23),
            contact_email=text("WD_CONTACT_EMAIL", ""),
            claude_bin=claude_bin,
            claude_home=text("WD_CLAUDE_HOME", ""),
            claude_path=text("WD_CLAUDE_PATH", "/home/sqin/.local/bin:/usr/local/bin:/usr/bin:/bin"),
            claude_cwd=claude_cwd,
            ai_enabled=flag("WD_AI_ENABLED", True),
            ai_model=text("WD_AI_MODEL", "sonnet"),
            ai_cli_fallback_model=text("WD_AI_CLI_FALLBACK_MODEL", ""),
            ai_extra_args=text("WD_AI_EXTRA_ARGS", ""),
            ai_batch_size=clamped("WD_AI_BATCH_SIZE", 10, 1, 12),
            ai_concurrency=clamped("WD_AI_CONCURRENCY", 1, 1, 3),
            ai_timeout_content_sec=integer("WD_AI_TIMEOUT_CONTENT_SEC", 180, 5, 3600),
            ai_timeout_lookup_sec=integer("WD_AI_TIMEOUT_LOOKUP_SEC", 120, 5, 3600),
            ai_timeout_consolidate_sec=integer("WD_AI_TIMEOUT_CONSOLIDATE_SEC", 240, 5, 3600),
            ai_timeout_svg_sec=integer("WD_AI_TIMEOUT_SVG_SEC", 120, 5, 3600),
            ai_timeout_dance_sec=integer("WD_AI_TIMEOUT_DANCE_SEC", 120, 5, 3600),
            ai_budget_content=money("WD_AI_BUDGET_CONTENT", 0.25),
            ai_budget_lookup=money("WD_AI_BUDGET_LOOKUP", 0.15),
            ai_budget_consolidate=money("WD_AI_BUDGET_CONSOLIDATE", 0.40),
            ai_budget_svg=money("WD_AI_BUDGET_SVG", 0.10),
            ai_budget_dance=money("WD_AI_BUDGET_DANCE", 0.25),
            ai_daily_budget_usd=money("WD_AI_DAILY_BUDGET_USD", 3.00),
            ai_monthly_budget_usd=money("WD_AI_MONTHLY_BUDGET_USD", 40.00),
            ai_prewarm_daily_budget_usd=money("WD_AI_PREWARM_DAILY_BUDGET_USD", 1.00),
            ai_hourly_call_cap=integer("WD_AI_HOURLY_CALL_CAP", 60, 1, 100_000),
            ai_svg_daily_budget_usd=money("WD_AI_SVG_DAILY_BUDGET_USD", 0.50),
            ai_dance_daily_budget_usd=money("WD_AI_DANCE_DAILY_BUDGET_USD", 0.50),
            ai_user_daily_words=integer("WD_AI_USER_DAILY_WORDS", 80, 0, 100_000),
            ai_log_keep_days=integer("WD_AI_LOG_KEEP_DAYS", 14, 0, 3650),
            ai_provider=ai_provider,
            ai_fallback_kind=fallback_kind,
            ai_fallback_base_url=fallback_base_url,
            ai_fallback_api_key=fallback_key,
            ai_fallback_api_key_file=fallback_key_file,
            ai_fallback_model=fallback_model,
            ai_fallback_dialect=choice("WD_AI_FALLBACK_DIALECT", "auto", FALLBACK_DIALECTS),
            ai_fallback_json_mode=choice("WD_AI_FALLBACK_JSON_MODE", "auto", FALLBACK_JSON_MODES),
            ai_fallback_thinking=choice("WD_AI_FALLBACK_THINKING", "off", FALLBACK_THINKING_MODES),
            ai_fallback_timeout_scale=number("WD_AI_FALLBACK_TIMEOUT_SCALE", 1.5, 0.5, 5.0),
            ai_fallback_max_output_tokens=integer("WD_AI_FALLBACK_MAX_OUTPUT_TOKENS", 0, 0, 131_072),
            ai_fallback_hourly_call_cap=integer("WD_AI_FALLBACK_HOURLY_CALL_CAP", 40, 1, 100_000),
            ai_fallback_batch_size=clamped("WD_AI_FALLBACK_BATCH_SIZE", 5, 1, 12),
            ai_fallback_kinds=tuple(fallback_kinds),
            ai_fallback_prewarm=flag("WD_AI_FALLBACK_PREWARM", False),
            ai_fallback_price_json=price_json,
            ai_cny_per_usd=number("WD_AI_CNY_PER_USD", 7.2, 0.01, 1000.0),
            ai_failover_cooldown_min=integer("WD_AI_FAILOVER_COOLDOWN_MIN", 30, 1, 1440),
            ai_failover_probe_every_min=integer("WD_AI_FAILOVER_PROBE_EVERY_MIN", 30, 1, 1440),
            ai_failover_overloaded_after=integer("WD_AI_FAILOVER_OVERLOADED_AFTER", 3, 1, 100),
            ai_failover_timeout_after=integer("WD_AI_FAILOVER_TIMEOUT_AFTER", 2, 1, 100),
            ai_failover_network_after=integer("WD_AI_FAILOVER_NETWORK_AFTER", 2, 1, 100),
            ecdict_db_path=ecdict_db_path,
            images_enabled=flag("WD_IMAGES_ENABLED", True),
            image_providers=tuple(providers),
            image_kid_stages=tuple(kid_stages),
            svg_via_claude=flag("WD_SVG_VIA_CLAUDE", True),
            image_max_bytes=integer("WD_IMAGE_MAX_BYTES", 8_000_000, 10_000, 1 << 30),
            image_max_edge=integer("WD_IMAGE_MAX_EDGE", 800, 100, 4096),
            wikimedia_min_interval_ms=integer("WD_WIKIMEDIA_MIN_INTERVAL_MS", 1000, 0, 600_000),
            wikimedia_daily_limit=integer("WD_WIKIMEDIA_DAILY_LIMIT", 2000, 0, 1_000_000),
            openverse_minute_limit=integer("WD_OPENVERSE_MINUTE_LIMIT", 15, 0, 100_000),
            openverse_daily_limit=integer("WD_OPENVERSE_DAILY_LIMIT", 160, 0, 1_000_000),
            openverse_client_id=text("WD_OPENVERSE_CLIENT_ID", ""),
            openverse_client_secret=text("WD_OPENVERSE_CLIENT_SECRET", ""),
            pixabay_key=pixabay_key,
            pexels_key=pexels_key,
            audio_provider=audio_provider,
            audio_say_voice=text("WD_AUDIO_SAY_VOICE", ""),
            audio_cache_voices=audio_cache_voices,
            audio_cache_mb=integer("WD_AUDIO_CACHE_MB", 256, 16, 1_000_000),
            bailian_api_key_file=bailian_key_file,
            bailian_workspace_id=bailian_workspace_id,
            bailian_region=bailian_region,
            bailian_tts_url=bailian_tts_url,
            bailian_tts_model=text("WD_BAILIAN_TTS_MODEL", DEFAULT_BAILIAN_TTS_MODEL),
            bailian_tts_voices=bailian_tts_voices,
            mail_provider=mail_provider,
            smtp_host=text("WD_SMTP_HOST", ""),
            smtp_port=integer("WD_SMTP_PORT", 587, 1, 65535),
            smtp_user=text("WD_SMTP_USER", ""),
            smtp_password=text("WD_SMTP_PASSWORD", ""),
            smtp_from=smtp_from,
            smtp_tls=choice("WD_SMTP_TLS", "starttls", SMTP_TLS_MODES),
            sms_provider=sms_provider,
            aliyun_access_key_id=aliyun_key_id,
            aliyun_access_key_secret_file=aliyun_secret_file,
            aliyun_sms_sign_name=aliyun_sign_name,
            sms_daily_cap=integer("WD_SMS_DAILY_CAP", 200, 0, 100_000),
            sms_hourly_cap=integer("WD_SMS_HOURLY_CAP", 40, 0, 100_000),
            code_ip_hourly=integer("WD_CODE_IP_HOURLY", 20, 1, 100_000),
            phone_stale_days=integer("WD_PHONE_STALE_DAYS", 90, 1, 3650),
            captcha=choice("WD_CAPTCHA", "on", CAPTCHA_MODES),
            wechat_appid=wechat_appid,
            wechat_secret_file=wechat_secret_file,
            wechat_env=choice("WD_WECHAT_ENV", "release", WECHAT_ENVS),
            wechat_page=text("WD_WECHAT_PAGE", "pages/confirm/confirm"),
            qq_appid=qq_appid,
            qq_key_file=qq_key_file,
            qq_callback_url=qq_callback_url,
            apple_client_id=apple_client_id,
            apple_app_id=text("WD_APPLE_APP_ID", ""),
            apple_callback_url=apple_callback_url,
            auth_fake_providers=auth_fake_providers,
            log_level=log_level,
            log_format=choice("WD_LOG_FORMAT", "json", LOG_FORMATS),
            log_file=text("WD_LOG_FILE", ""),
            backup_keep_daily=integer("WD_BACKUP_KEEP_DAILY", 14, 0, 10_000),
            backup_keep_weekly=integer("WD_BACKUP_KEEP_WEEKLY", 8, 0, 10_000),
            admin_username=text("WD_ADMIN_USERNAME", ""),
            admin_password=text("WD_ADMIN_PASSWORD", ""),
            dev_real_claude=flag("WD_DEV_REAL_CLAUDE", False),
            smoke_mock_http=flag("WD_SMOKE_MOCK_HTTP", False),
            env_sources=present,
        )

    # --------------------------------------------------------------------- reporting
    def entries(self) -> list[dict[str, Any]]:
        """``[{key, value, source}]`` for ``GET /api/admin/config`` (API.md 73); secrets masked as ``***``."""
        out: list[dict[str, Any]] = []
        for f in fields(self):
            if f.name == "env_sources":
                continue
            key = "WD_" + f.name.upper()
            value = getattr(self, f.name)
            if key in SECRET_KEYS:
                shown: Any = "***" if value else ""
            elif isinstance(value, Path):
                shown = str(value)
            elif isinstance(value, tuple):
                shown = ",".join(value)
            elif isinstance(value, bool):
                shown = "1" if value else "0"
            elif value is None:
                shown = ""
            else:
                shown = str(value)
            out.append({"key": key, "value": shown, "source": "env" if key in self.env_sources else "default"})
        return out


def origin_of(url: str) -> str | None:
    """``scheme://host[:port]`` of a URL (lower-case), or None when it has no host."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url.strip())
    except ValueError:  # e.g. an unbalanced IPv6 bracket: "no origin", never an exception out of Settings.from_env
        return None
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def is_loopback_url(url: str) -> bool:
    """True when the URL's host is this machine (``localhost``, ``127.0.0.0/8``, ``::1``) — plain ``http://`` is fine there."""
    from urllib.parse import urlsplit

    try:
        host = (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:  # malformed IPv6 bracket: not loopback (and origin_of() already refuses it)
        return False
    return host == "localhost" or host == "::1" or host.startswith("127.")


def ensure_dirs(cfg: Settings, mode: int = 0o700) -> None:
    """Create the data dir and its runtime subdirectories (0700, DEPLOY §1). Idempotent."""
    for d in cfg.runtime_dirs():
        d.mkdir(parents=True, exist_ok=True, mode=mode)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True, mode=mode)


_cached: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    """Process-wide settings built from ``os.environ`` on first use (the app stores its own copy on ``app.state``)."""
    global _cached
    if _cached is None or refresh:
        _cached = Settings.from_env()
    return _cached
