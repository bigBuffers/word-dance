"""Pydantic models for every request and response of API.md §2–§9 (Phase 0, frozen contract).

Rules
* every model forbids unknown fields (``extra='forbid'``) — a typo in a client field is a 400
  ``validation_error`` (errors.py converts FastAPI's 422);
* model names mirror the TypeScript interfaces of API.md §9 (``frontend/src/api/types.ts``) so the
  contract audit (``scripts/check_contract.py``) can diff property names; endpoint-specific bodies
  that have no TS interface are named ``<Endpoint>Request`` / ``<Endpoint>Response``;
* ``current_stage`` is the ``Stage`` string on the wire everywhere; the server maps it to the 1–5
  column with :func:`stage_to_index` / :func:`index_to_stage` (API.md §9.1);
* timestamps are ``str`` (UTC ISO-8601 ``YYYY-MM-DDTHH:MM:SSZ``), local dates ``str`` ``YYYY-MM-DD``.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .clock import PUSH_TIME_RE, is_valid_timezone

# ------------------------------------------------------------------------------------- enums
Stage = Literal["xs", "zk", "gk", "cet4", "cet6"]
StageIndex = Literal[1, 2, 3, 4, 5]
UserState = Literal["new", "learning", "mastered", "known", "removed"]
Origin = Literal["browse", "custom", "screen", "push", "import"]
MarkAction = Literal["unfamiliar", "known", "mastered", "remove", "reset", "restore"]
Grade = Literal["again", "hard", "good", "master", "skip"]
ScreenVerdict = Literal["known", "unfamiliar", "skip"]
ContentState = Literal["none", "queued", "ready", "failed"]
ImageState = Literal["none", "queued", "ready", "failed"]
ItemKind = Literal["review", "new", "screen", "extra"]
WordKind = Literal["word", "phrase", "abbreviation", "proper_noun"]
ReportReason = Literal["wrong_meaning", "unnatural_example", "bad_translation", "irrelevant_image", "inappropriate_image", "other"]
WebhookFormat = Literal["generic", "wecom", "feishu", "serverchan", "bark"]
WebhookTestReason = Literal["dns_failed", "host_not_public", "connect_failed", "timeout", "tls_failed", "http_error", "invalid_url"]  # API.md 17; delivery.webhook.REASONS
Role = Literal["user", "admin"]
OnboardingState = Literal["pending", "screen", "done"]
RegistrationMode = Literal["open", "invite", "closed", "verified"]  # verified = a phone / e-mail code creates the account (docs/AUTH_SIGNUP_DESIGN.md)
WordSource = Literal["seed", "ecdict", "claude", "user"]
BatchStatus = Literal["building", "ready", "published"]
SuggestionType = Literal["fix_spelling", "lemmatize", "merge_duplicate", "invalid_word", "split_phrase", "confusable_group", "fill_data", "difficulty"]
SuggestionStatus = Literal["open", "accepted", "rejected", "expired", "auto", "undone"]
ImageProviderName = Literal["wikimedia", "openverse", "pixabay", "pexels", "claude_svg", "card_svg"]
Difficulty = Literal[1, 2, 3, 4, 5]
FlagTier = Literal[0, 1]
AiProvider = Literal["claude", "fallback"]  # ai_calls.provider: the Claude CLI or ai/providers/openai_http.py (CLAUDE_INTEGRATION §10)
DanceMode = Literal["full", "form_only", "off"]  # user_settings.dance_mode — 单词之舞 (docs/WORD_DANCE_DESIGN.md §6.3): full = + semantic dance, form_only = spelling + stress only
DancePrimitive = Literal["rise", "fall", "hop", "grow", "shrink", "dash", "creep", "enter", "exit", "arc", "onto", "under", "behind", "between", "split", "join", "shiver", "shimmer", "wave", "droop", "stretch", "squash", "thud", "float", "spin", "repeat", "multiply", "dim", "glow", "color"]  # the semantic dance library (WORD_DANCE_DESIGN §4.3), mirrored by dance_v1.json
DanceColor = Literal["red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "black", "white", "grey"]  # the only colours the `color` primitive may name
# sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.1; the same order as API.md §9 — check_contract diffs the unions in order)
AgeBand = Literal["u14", "14plus", "adult"]  # users.age_band — the learner's own declaration, never verified
AGE_BAND_U14_ZH = "未满 14 周岁的同学请由家长注册"  # endpoint 89 keeps refusing u14: child accounts are created by a guardian (endpoint 95, slice 1-B)
CodeChannel = Literal["phone", "email"]  # login_codes.channel (endpoints 80, 81, 85)
IdentityProvider = Literal["phone", "wechat_mini", "qq", "apple"]  # identities.provider — only `phone` is issued in slice 1-A
AccountKind = Literal["learner", "guardian"]  # users.account_kind (slice 1-B) — a guardian creates, switches into and manages child accounts (endpoints 94–105)
GUARDIAN_ADULT_ZH = "家长请选择「我是成人」"  # endpoints 89 / 110: a guardian declares the `adult` band (details.fields.age_band)
GATE_ONE_OF_ZH = "PIN、密码和验证码必须且只能提供一个"  # the 家长门 bodies of endpoints 102 / 105 (details.fields.body)
# third-party sign-in (docs/AUTH_SIGNUP_DESIGN.md §5.3, API.md §3.3 — slice 2-A)
ThirdPartyProvider = Literal["wechat_mini", "qq", "apple"]  # identities.provider values of slice 2-A (phone is 1-A's); subject = openid / openid / Apple sub, never shown
WechatTicketKind = Literal["login", "bind"]  # wechat_tickets.kind (endpoints 112 / 115)
WechatTicketState = Literal["pending", "scanned", "confirmed", "cancelled", "expired"]  # WechatTicketStatus.status (113; `expired` is computed from expires_at, `consumed` rows answer 404)
WechatScanAccount = Literal["bound", "new", "closed", "self", "other"]  # WechatScanInfo.account (115)
WECHAT_SCAN_ONE_OF_ZH = "请提供小程序码场景值或配对码"  # endpoint 115: exactly one of ticket / pairing_code (details.fields.body)

# The stage enum lives HERE and nowhere else (DESIGN §0.3, API.md §9.1): seed.py, services/*, ai/prewarm.py and the
# frontend's StageChips mirror this tuple (scripts/check_contract.py diffs the Stage/StageIndex unions against types.ts
# in order). Index = position + 1 (xs=1 … cet6=5; migration 0011 renumbered the stored 1..4 to 2..5). STAGE_INDEX is
# written out rather than derived so that inserting a stage later fails the position test in test_api_schemas instead
# of silently renumbering every stored stage_min / current_stage.
STAGE_ORDER: tuple[str, ...] = ("xs", "zk", "gk", "cet4", "cet6")
STAGE_INDEX: dict[str, int] = {"xs": 1, "zk": 2, "gk": 3, "cet4": 4, "cet6": 5}  # == STAGE_ORDER.index(s) + 1 (test_api_schemas pins it)
STAGE_NAMES_ZH: dict[str, str] = {"xs": "小学", "zk": "初中", "gk": "高中", "cet4": "四级", "cet6": "六级"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_一-龥]{2,32}$")
# a username that `security.normalize_phone` would read as a mainland mobile number — within USERNAME_RE (no `+`, spaces or dashes)
# that is exactly `1…` (11 digits) with an optional `86` / `0086` prefix (test_api_schemas pins the two in step); refused
# (API.md 2 / 89), or the login identifier of endpoint 3 would resolve a number's digits to the squatter's account first
PHONE_LIKE_USERNAME_RE = re.compile(r"^(?:0086|86)?1\d{10}$")
USERNAME_RULE_ZH = "用户名为 2–32 个字母、数字、下划线或汉字"
USERNAME_PHONE_ZH = "用户名不能是手机号"


def stage_to_index(stage: str) -> int:
    """``xs→1, zk→2, gk→3, cet4→4, cet6→5`` (``user_settings.current_stage`` / ``words.stage_min``, API.md §9.1).

    Looks up the explicit :data:`STAGE_INDEX` instead of the position in :data:`STAGE_ORDER` (see the note above the
    constants); an unknown code is a ``ValueError`` so callers can turn it into a 400 or a seed-build failure.
    """
    try:
        return STAGE_INDEX[stage]
    except KeyError:
        raise ValueError(f"unknown stage {stage!r}") from None


def index_to_stage(index: int) -> str:
    """Inverse of :func:`stage_to_index`; ``ValueError`` outside ``1..len(STAGE_ORDER)`` (a stored index from a newer schema)."""
    if not 1 <= int(index) <= len(STAGE_ORDER):
        raise ValueError(f"stage index out of range: {index!r}")
    return STAGE_ORDER[int(index) - 1]


def _check_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("must be a UUID") from None


def _unique_stages(stages: list[str]) -> list[str]:
    if not stages:
        raise ValueError("stages must not be empty")
    seen: list[str] = []
    for s in stages:
        if s not in seen:
            seen.append(s)
    return seen


class Model(BaseModel):
    """Base for every DTO: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


T = TypeVar("T")


class Page(Model, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int


# ------------------------------------------------------------------------------ error envelope
class ApiErrorBody(Model):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiErrorEnvelope(Model):
    error: ApiErrorBody


# --------------------------------------------------------------------------- health (endpoint 1)
class HealthResponse(Model):
    status: Literal["ok"]
    version: str
    registration_mode: RegistrationMode
    needs_setup: bool
    sms_enabled: bool  # Settings.sms_configured — the login page shows the 手机号 entry (endpoints 80, 81)
    email_enabled: bool  # Settings.email_configured — the 邮箱 entry
    captcha: bool  # WD_CAPTCHA=on — the public code sends need a captcha token (endpoint 79)
    # third-party sign-in (slice 2-A): Settings.<provider>_configured or auth_fake_providers — the login page's 「其他方式登录」 row
    wechat_enabled: bool  # the WeChat mini-program bridge (endpoints 112–116)
    qq_enabled: bool  # QQ 互联 login (118 / 119)
    apple_enabled: bool  # Sign in with Apple, web redirect flow (120 / 121)
    time: str


class DegradedResponse(Model):
    status: Literal["degraded"]
    version: str | None = None
    time: str | None = None


# ----------------------------------------------------------------------------- users / settings
class User(Model):
    id: int
    username: str
    display_name: str
    email: str | None
    email_verified: bool
    role: Role
    onboarding_state: OnboardingState
    created_at: str
    has_password: bool  # users.password_set_at IS NOT NULL — false for a code-created account until it sets one (endpoint 89 / 7)
    phone_masked: str | None  # the live phone identity with its middle digits hidden (`138****8000`); null without one
    needs_profile: bool  # a code-created account that has not saved its nickname + age band yet (endpoint 89)
    age_band: AgeBand | None  # null = not declared
    # guardian + child accounts (slice 1-B, docs/AUTH_SIGNUP_DESIGN.md §5.1); security.user_dto always emits the three
    account_kind: AccountKind  # 'guardian' unlocks 我的孩子 (endpoints 94–104); chosen at /welcome step 0 (89), the legacy prompt (110) or by a claim (109)
    is_child: bool  # users.guardian_user_id IS NOT NULL — account / identity changes only through the guardian (403 guardian_required, API.md §1)
    needs_profile_prompt: bool  # a pre-1-A account that has not declared its kind / age band and was not snoozed in the last 30 days (111; API.md §9.1)
    providers: list[ThirdPartyProvider]  # the third-party identities bound to the account (sorted) — security.user_dto always emits it (third_party.providers_of)


class ServerFlags(Model):
    version: str
    registration_mode: RegistrationMode
    email_configured: bool
    ai_enabled: bool
    images_enabled: bool
    dev: bool
    needs_setup: bool
    audio: bool
    audio_key: str  # fingerprint of the provider + voice behind GET /media/audio (empty without a provider): the client appends it to clip URLs
    audio_zh: bool  # GET /media/audio also speaks Chinese (accent zh-CN): the provider is `say` and its Chinese voice is resolved — or not resolved yet, the seconds after a start (wd.audio.speaks_zh) — 磨耳朵 (endpoint 123)
    sms_enabled: bool  # WD_SMS_PROVIDER is not off: phone verification codes can be sent (endpoints 80, 85)
    # third-party sign-in (slice 2-A): Settings.<provider>_configured or auth_fake_providers (routers/auth.server_flags)
    wechat_enabled: bool  # the WeChat mini-program bridge is configured (endpoints 112–116) — the login page shows 微信, settings offers 绑定微信
    qq_enabled: bool  # QQ 互联 login is configured (118 / 119)
    apple_enabled: bool  # Sign in with Apple (web redirect flow) is configured (120 / 121)


class Counters(Model):
    suggestions_open: int
    attention: int


class SessionGuardian(Model):
    """``SessionInfo.guardian``: the guardian who switched this device into a child account (``sessions.actor_user_id``, endpoint 104)."""

    id: int
    display_name: str


class SessionInfo(Model):
    """``GET /api/auth/me`` → ``session`` (API.md §9, slice 1-B): the guardian behind a switched child session (the SPA shows 「切回家长」
    → endpoint 105), and for a guardian's own session until when the 家长门 is passed (``sessions.guardian_gate_at`` + 10 min, endpoints
    102 / 105; ``null`` = not passed / not a guardian)."""

    guardian: SessionGuardian | None
    gate_until: str | None


class Settings(Model):
    """The user settings DTO (API.md §9 ``Settings``; not to be confused with ``wd.config.Settings``)."""

    timezone: str
    push_time: str
    push_enabled: bool
    daily_new_count: int
    daily_screen_count: int
    max_reviews: int
    stages: list[Stage]
    current_stage: Stage
    show_images: bool
    zh_examples: Literal["tap", "always"]
    auto_pronounce: bool
    accent: Literal["en-US", "en-GB"]
    dance_mode: DanceMode
    image_word: bool
    email_enabled: bool
    webhook_enabled: bool
    webhook_url: str | None
    webhook_format: WebhookFormat
    next_push_at: str | None
    email_verified: bool
    updated_at: str


# ------------------------------------------------ third-party sign-in: the WeChat bridge DTOs (API.md §3.3 / §9, slice 2-A)
class WechatTicket(Model):
    """Endpoint 112 (201): the 26-char scene of the 小程序码 (also the poll path of 113 / 114), the 6-digit pairing code for the mobile
    path, the seconds the ticket lives (180) and the PNG URL (114). The poll secret travels in the HttpOnly cookie ``wd_wxt``."""

    ticket: str
    pairing_code: str
    expires_in_s: int
    qr_url: str


class WechatTicketStatus(Model):
    """Endpoint 113 (polled every 2 s with the ``wd_wxt`` cookie): ``user`` / ``settings`` / ``created`` are set only for a confirmed
    ticket — a login ticket brings the session cookie with the same response (201 when the account was created), a bind ticket
    ``user`` = the bound account with ``settings`` null and ``created`` false."""

    status: WechatTicketState
    user: User | None
    settings: Settings | None
    created: bool | None


class WechatScanInfo(Model):
    """Endpoint 115 (the mini program's confirmation page): ``mp_token`` proves the scan to endpoint 116 for 5 minutes; ``account``
    tells the page what confirming would do (login: ``bound`` / ``new`` / ``closed``; bind: ``self`` / ``other`` / ``new``); the
    initiating browser is described by its masked IP (``203.0.113.*``) and a UA summary (``Chrome · macOS``)."""

    mp_token: str
    kind: WechatTicketKind
    account: WechatScanAccount
    bind_display_name: str | None
    web_ip_masked: str
    web_ua_summary: str
    created_at: str
    expires_in_s: int


class WechatConfirmResult(Model):
    """Endpoint 116: the mini program's confirm / cancel outcome (``created`` = the confirmation created the account). The mini
    program never receives a session — the web poll (113) does."""

    status: Literal["confirmed", "cancelled"]
    created: bool


def validate_username(v: str) -> str:
    """The endpoint 2 / 89 username rule: ``USERNAME_RE`` after stripping, and never a value that reads as a mainland mobile number
    (:data:`PHONE_LIKE_USERNAME_RE`, the digits-only subset of ``security.normalize_phone``)."""
    v = v.strip()
    if not USERNAME_RE.match(v):
        raise ValueError(USERNAME_RULE_ZH)
    if PHONE_LIKE_USERNAME_RE.match(v):
        raise ValueError(USERNAME_PHONE_ZH)
    return v


class RegisterRequest(Model):
    username: str
    password: str
    display_name: str | None = None
    email: str | None = None
    invite_code: str | None = None

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not 8 <= len(v) <= 64:
            raise ValueError("密码长度为 8–64 个字符")
        return v

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 32:
            raise ValueError("昵称不超过 32 个字符")
        return v or None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _clean_email(v)

    @field_validator("invite_code")
    @classmethod
    def _invite(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


def _clean_email(v: str | None) -> str | None:
    """The one e-mail normalisation every writer applies (NFKC, stripped, lower-cased — endpoints 2, 6, 80, 81 compare
    ``users.email`` with a code's target, docs/AUTH_SIGNUP_DESIGN.md §5.2): ``None`` for an empty value, zh ``ValueError`` for a
    malformed one."""
    if v is None:
        return None
    v = unicodedata.normalize("NFKC", v).strip().lower()
    if not v:
        return None
    if len(v) > 254 or "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
        raise ValueError("邮箱格式无效")
    return v


class LoginRequest(Model):
    """Endpoint 3: ``username`` is an identifier — a username, a mainland phone number or a verified e-mail (API.md 3)."""

    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=64)


class AuthResponse(Model):
    user: User
    settings: Settings


class MeResponse(Model):
    user: User
    settings: Settings
    server: ServerFlags
    counters: Counters
    session: SessionInfo  # slice 1-B: the switched-in guardian (if any) and the 家长门 stamp of this session (routers/auth.session_info)


class UserResponse(Model):
    user: User


class AccountUpdateRequest(Model):
    display_name: str | None = None
    email: str | None = None

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 32:
            raise ValueError("昵称不超过 32 个字符")
        return v or None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return _clean_email(v)


def _exactly_one(first: Any, second: Any, names_zh: str) -> None:
    """The re-authentication rule of endpoints 7 / 8 / 87: a password OR a ``reauth`` code, never both, never neither."""
    if (first is None) == (second is None):
        raise ValueError(f"{names_zh}必须且只能提供一个")


class PasswordChangeRequest(Model):
    """Endpoint 7: ``current_password`` for an account with a password, a ``reauth`` code (endpoint 85) for one without."""

    current_password: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=64)

    @model_validator(mode="after")
    def _one_factor(self) -> "PasswordChangeRequest":
        _exactly_one(self.current_password, self.code, "当前密码和验证码")
        return self


class AccountDeleteRequest(Model):
    """Endpoint 8: the same password-or-code dispatch as endpoint 7. A guardian with children must also say what happens to them:
    ``delete_children: true`` (a child with its own phone is set free, the others are deleted), else 409 ``has_children`` with
    ``details.children`` (slice 1-B)."""

    password: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    delete_children: bool | None = None

    @model_validator(mode="after")
    def _one_factor(self) -> "AccountDeleteRequest":
        _exactly_one(self.password, self.code, "密码和验证码")
        return self


class CodeSendResponse(Model):
    """Endpoints 9, 80, 82, 85, 90 — always ``sent: true``; identical for known and unknown targets (API.md §9)."""

    sent: bool
    expires_in_s: int


class EmailVerifyRequest(Model):
    code: str = Field(pattern=r"^\d{6}$")


# ---------------------------------------------- sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.2; endpoints 79–91)
def _clean_target(channel: str, target: str) -> str:
    """A code's target as the client typed it: e-mails through :func:`_clean_email` (the same rule as endpoints 2 / 6), phone
    numbers only stripped — ``security.normalize_phone`` turns them into E.164 and answers 400 ``invalid_phone`` otherwise."""
    if channel == "email":
        cleaned = _clean_email(target)
        if cleaned is None:
            raise ValueError("请输入邮箱")
        return cleaned
    target = target.strip()
    if not target:
        raise ValueError("请输入手机号")
    return target


class CaptchaChallenge(Model):
    """Endpoint 79: ``image`` is a PNG ``data:`` URI; the client returns ``id`` / ``exp`` / ``sig`` with the digits it read."""

    id: str
    image: str
    exp: int
    sig: str
    expires_in_s: int


class CaptchaToken(Model):
    """The captcha answer a public code send carries (endpoints 80, 90): the challenge's own ``id`` / ``exp`` / ``sig`` plus the digits."""

    id: str = Field(min_length=1, max_length=64)
    exp: int
    sig: str = Field(min_length=1, max_length=128)
    answer: str = Field(min_length=1, max_length=16)


class CodeSendRequest(Model):
    """Endpoint 80: send a ``login`` or ``reset_password`` code to a phone or an e-mail (consent required for ``login``)."""

    channel: CodeChannel
    target: str = Field(min_length=1, max_length=254)
    purpose: Literal["login", "reset_password"]
    consent: bool | None = None
    captcha: CaptchaToken | None = None

    @model_validator(mode="after")
    def _target(self) -> "CodeSendRequest":
        self.target = _clean_target(self.channel, self.target)
        return self


class CodeLoginRequest(Model):
    """Endpoint 81: verify a ``login`` code — log in, create the account, or receive the stale-phone challenge."""

    channel: CodeChannel
    target: str = Field(min_length=1, max_length=254)
    code: str = Field(pattern=r"^\d{6}$")
    invite_code: str | None = None

    @field_validator("invite_code")
    @classmethod
    def _invite(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @model_validator(mode="after")
    def _target(self) -> "CodeLoginRequest":
        self.target = _clean_target(self.channel, self.target)
        return self


class StaleChallenge(Model):
    """Endpoints 81–84: a phone identity unused for ``WD_PHONE_STALE_DAYS`` — the login answers this instead of a session."""

    token: str
    display_name_masked: str
    since: str
    can_password: bool
    can_email: bool
    email_masked: str | None


class CodeLoginResponse(Model):
    """Endpoint 81: ``user`` + ``settings`` when a session was issued (cookie in the same response), else the ``challenge``."""

    user: User | None
    settings: Settings | None
    created: bool
    challenge: StaleChallenge | None


class ChallengeEmailRequest(Model):
    """Endpoint 82: send the stale-phone second-factor code to the account's verified e-mail."""

    token: str = Field(min_length=1, max_length=128)


class ChallengeConfirmRequest(Model):
    """Endpoint 83: 「这是我的账号」 — the account's password or the e-mail code of endpoint 82 (neither → 403 ``second_factor_required``)."""

    token: str = Field(min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")


class ChallengeDisputeRequest(Model):
    """Endpoint 84: 「不是我的」 — the old binding is disputed and a new account is created for the phone (mode rules apply)."""

    token: str = Field(min_length=1, max_length=128)
    invite_code: str | None = None

    @field_validator("invite_code")
    @classmethod
    def _invite(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class AccountCodeRequest(Model):
    """Endpoint 85: a code for ``bind_phone`` (``target`` = the new number), ``rebind_phone`` (the bound number) or ``reauth``
    (the bound phone or the verified e-mail, by ``channel``)."""

    channel: CodeChannel
    purpose: Literal["bind_phone", "rebind_phone", "reauth"]
    target: str | None = Field(default=None, max_length=254)

    @model_validator(mode="after")
    def _target(self) -> "AccountCodeRequest":
        if self.target is not None:
            self.target = _clean_target(self.channel, self.target)
        return self


class PhoneBindRequest(Model):
    """Endpoint 86: bind the phone a ``bind_phone`` code was sent to."""

    target: str = Field(min_length=1, max_length=254)
    code: str = Field(pattern=r"^\d{6}$")

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        return _clean_target("phone", v)


class PhoneUnbindRequest(Model):
    """Endpoint 87: unbind the phone after re-authenticating like endpoint 7 (password or ``reauth`` code)."""

    password: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def _one_factor(self) -> "PhoneUnbindRequest":
        _exactly_one(self.password, self.code, "密码和验证码")
        return self


class IdentityUnbindRequest(PhoneUnbindRequest):
    """Endpoint 117 (``DELETE /api/account/identities/{provider}``, slice 2-A): unbind a WeChat / QQ / Apple identity after the endpoint-7
    re-authentication — the 87 one-of (``password`` or a ``reauth`` code of 85, never both, never neither), inherited unchanged so the
    two bodies cannot drift; the distinct name keeps the OpenAPI schema and API.md readable."""


class PhoneRebindRequest(Model):
    """Endpoint 88: replace the bound phone — a ``rebind_phone`` code on the old number and a ``bind_phone`` code on the new one."""

    code_old: str = Field(pattern=r"^\d{6}$")
    target_new: str = Field(min_length=1, max_length=254)
    code_new: str = Field(pattern=r"^\d{6}$")

    @field_validator("target_new")
    @classmethod
    def _target(cls, v: str) -> str:
        return _clean_target("phone", v)


class ProfileRequest(Model):
    """Endpoint 89: the first-time setup of a code-created account — nickname, account kind (slice 1-B: ``guardian`` needs the ``adult``
    band here, and a password unless the e-mail is verified — the router's rule), age band (``u14`` is refused with its own message:
    child accounts are created by a guardian, endpoint 95), an optional one-time username and an optional password. ``account_kind`` is
    declared before ``age_band`` so the band's validator can read it (``info.data``) and the error lands on ``details.fields.age_band``."""

    display_name: str
    account_kind: AccountKind = "learner"
    age_band: AgeBand
    username: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 32:
            raise ValueError("昵称为 1–32 个字符")
        return v

    @field_validator("age_band")
    @classmethod
    def _age_band(cls, v: str, info: ValidationInfo) -> str:
        if v == "u14":
            raise ValueError(AGE_BAND_U14_ZH)  # API.md 89: 400 validation_error, details.fields.age_band carries this text
        if info.data.get("account_kind") == "guardian" and v != "adult":
            raise ValueError(GUARDIAN_ADULT_ZH)  # API.md 89: a guardian is an adult (the claim-created guardian's row is checked by the router)
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.strip():
            return None
        return validate_username(v)


class ForgotPasswordRequest(Model):
    """Endpoint 90: send a ``reset_password`` code to the identifier's verified channel (always 202)."""

    identifier: str = Field(min_length=1, max_length=254)
    captcha: CaptchaToken | None = None

    @field_validator("identifier")
    @classmethod
    def _identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("请输入用户名、手机号或邮箱")
        return v


class ResetPasswordRequest(Model):
    """Endpoint 91: set a new password with the reset code (every session is revoked)."""

    identifier: str = Field(min_length=1, max_length=254)
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("identifier")
    @classmethod
    def _identifier(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("请输入用户名、手机号或邮箱")
        return v


# ------------------------------- guardian + child accounts (docs/AUTH_SIGNUP_DESIGN.md §5.1–5.2; endpoints 94–111, slice 1-B)
class ChildAccount(Model):
    """API.md §9 ``ChildAccount`` — a child as its guardian sees it (endpoints 94–96, 101): ``username`` is ``null`` while the account
    still carries its placeholder name, ``bank_size`` / ``streak_days`` are the ``AdminUser`` figures, ``sessions`` counts the child's
    live sessions whatever their ``actor_user_id`` (endpoint 98 revokes them)."""

    id: int
    display_name: str
    username: str | None
    has_password: bool
    phone_masked: str | None
    age_band: AgeBand | None
    onboarding_state: OnboardingState
    created_at: str
    last_login_at: str | None
    bank_size: int
    streak_days: int
    sessions: int


class ChildrenResponse(Model):
    """Endpoint 94: my children by ``created_at``, whether the 家长 PIN is set, the two-factor readiness (``ready`` = a live phone AND a
    password or a verified e-mail; ``missing`` names what is absent) and the session's gate state."""

    items: list[ChildAccount]
    pin_set: bool
    ready: bool
    missing: list[Literal["phone", "second_factor"]]
    gate_until: str | None


class ChildResponse(Model):
    """Endpoints 95, 96, 101."""

    child: ChildAccount


class ChildLoginCode(Model):
    """Endpoint 99: the 8-digit one-time code for the child's own device — shown once, never logged (10 minutes)."""

    code: str
    expires_in_s: int


class GateResponse(Model):
    """Endpoint 102: until when this session's 家长门 is passed (now + 10 min)."""

    gate_until: str


def _child_display_name(v: str) -> str:
    v = v.strip()
    if not 1 <= len(v) <= 32:
        raise ValueError("昵称为 1–32 个字符")
    return v


def _optional_username(v: str | None) -> str | None:
    """A simple login for a child (endpoints 95 / 96): the endpoint 2 rule when given, ``None`` for an empty value."""
    if v is None or not v.strip():
        return None
    return validate_username(v)


def _exactly_one_gate_factor(pin: Any, password: Any, code: Any) -> None:
    """The 家长门 rule of endpoints 102 / 105: a PIN, the password or a ``reauth`` code — exactly one of the three."""
    if sum(x is not None for x in (pin, password, code)) != 1:
        raise ValueError(GATE_ONE_OF_ZH)


class ChildCreateRequest(Model):
    """Endpoint 95: a child account — nickname, the 6-digit 家长 PIN while the guardian has none (required then, refused once set — the
    router decides), an optional simple login (``username`` and ``password`` both or neither — the router's rule)."""

    display_name: str
    pin: str | None = Field(default=None, pattern=r"^\d{6}$")
    username: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str) -> str:
        return _child_display_name(v)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        return _optional_username(v)


class ChildUpdateRequest(Model):
    """Endpoint 96: rename a child and / or set or replace its simple login — at least one field (a password needs a non-placeholder
    username, current or in this body: the router's rule)."""

    display_name: str | None = None
    username: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str | None) -> str | None:
        return None if v is None else _child_display_name(v)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        return _optional_username(v)

    @model_validator(mode="after")
    def _at_least_one(self) -> "ChildUpdateRequest":
        if self.display_name is None and self.username is None and self.password is None:
            raise ValueError("至少提供昵称、用户名或密码之一")
        return self


class ChildPhoneCodeRequest(Model):
    """Endpoint 100: send a ``bind_phone`` code to the phone the child will own (the 独立 flow)."""

    target: str = Field(min_length=1, max_length=254)

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        return _clean_target("phone", v)


class ChildEmancipateRequest(Model):
    """Endpoint 101: 独立 — the child's own phone (its ``bind_phone`` code of 100) and a new password; irreversible."""

    target: str = Field(min_length=1, max_length=254)
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=8, max_length=64)

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        return _clean_target("phone", v)


class GateRequest(Model):
    """Endpoint 102: pass the 家长门 for this session with exactly one of the PIN, the password or a ``reauth`` code (endpoint 85)."""

    pin: str | None = Field(default=None, pattern=r"^\d{6}$")
    password: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def _one_factor(self) -> "GateRequest":
        _exactly_one_gate_factor(self.pin, self.password, self.code)
        return self


class PinRequest(Model):
    """Endpoint 103: set or change the 6-digit 家长 PIN (``family.pin_problem`` refuses straights and repeats in the router)."""

    pin: str = Field(pattern=r"^\d{6}$")


class SwitchBackRequest(Model):
    """Endpoint 105: back to the guardian's session from a switched child session — the same one-of-three as :class:`GateRequest`
    (the code is a ``reauth`` code of endpoint 106)."""

    pin: str | None = Field(default=None, pattern=r"^\d{6}$")
    password: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def _one_factor(self) -> "SwitchBackRequest":
        _exactly_one_gate_factor(self.pin, self.password, self.code)
        return self


class SwitchCodeRequest(Model):
    """Endpoint 106: send a ``reauth`` code to the guardian's phone or verified e-mail from a switched child session."""

    channel: CodeChannel


class ChildLoginRequest(Model):
    """Endpoint 107: sign a child's device in with the 8-digit code of endpoint 99."""

    code: str = Field(pattern=r"^\d{8}$")


class GuardianClaimCodeRequest(Model):
    """Endpoint 108: 「这是孩子的账号」 — send a claim code to the guardian's phone."""

    target: str = Field(min_length=1, max_length=254)

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        return _clean_target("phone", v)


class GuardianClaimRequest(Model):
    """Endpoint 109: attach my account to the guardian who owns that phone (the claim code of 108) and declare the child's band."""

    target: str = Field(min_length=1, max_length=254)
    code: str = Field(pattern=r"^\d{6}$")
    age_band: Literal["u14", "14plus"]

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        return _clean_target("phone", v)


class DeclareRequest(Model):
    """Endpoint 110: the legacy 「补充信息」 prompt — 家长 / 成人学习者 / 学生（已满 14）; a guardian declares the ``adult`` band
    (``account_kind`` is declared first so the band's validator can read it and the error lands on ``details.fields.age_band``)."""

    account_kind: AccountKind
    age_band: Literal["14plus", "adult"]

    @field_validator("age_band")
    @classmethod
    def _guardian_is_adult(cls, v: str, info: ValidationInfo) -> str:
        if info.data.get("account_kind") == "guardian" and v != "adult":
            raise ValueError(GUARDIAN_ADULT_ZH)
        return v


ExportFormat = Literal["csv", "json"]


# ------------------------------------------- third-party sign-in: the WeChat bridge request bodies (API.md §3.3, slice 2-A)
class WechatTicketRequest(Model):
    """Endpoint 112: ``kind`` ``login`` (public; the SPA's login page) or ``bind`` (a session, not a child); ``invite_code`` only for a
    login ticket in ``invite`` registration mode (validated at creation, consumed by the confirmation — 116). Blank → None like the
    endpoint 2 / 81 bodies."""

    kind: WechatTicketKind
    invite_code: str | None = None

    @field_validator("invite_code")
    @classmethod
    def _invite(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class WechatScanRequest(Model):
    """Endpoint 115 (the mini program): its ``wx.login`` ``js_code`` plus exactly one of the 小程序码 scene (``ticket``, 26 base32
    chars) or the 6-digit ``pairing_code`` typed by the user — neither or both → 400 ``validation_error`` on ``details.fields.body``."""

    js_code: str = Field(min_length=1, max_length=128)
    ticket: str | None = Field(default=None, pattern=r"^[a-z2-7]{26}$")
    pairing_code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def _one_of(self) -> "WechatScanRequest":
        if (self.ticket is None) == (self.pairing_code is None):
            raise ValueError(WECHAT_SCAN_ONE_OF_ZH)
        return self


class WechatConfirmRequest(Model):
    """Endpoint 116 (the mini program): the ``mp_token`` of 115, the ticket it was issued for and the decision (``accept`` false = 取消).
    The token is verified against the ticket row and its openid by the router (401 ``invalid_identity_token``), so the body carries
    only length caps."""

    mp_token: str = Field(min_length=1, max_length=256)
    ticket: str = Field(min_length=1, max_length=64)
    accept: bool


class ExportWordRow(Model):
    """One row of ``GET /api/account/export`` (the 14 columns; CSV and ``json.words``)."""

    word: str
    phonetic: str | None = None
    translation: str | None = None
    state: UserState
    origin: Origin
    note: str | None = None
    times_added: int = 1
    added_at: str | None = None
    mastered_at: str | None = None
    ease: float | None = None
    interval_days: int | None = None
    repetitions: int | None = None
    lapses: int | None = None
    due_at: str | None = None


class ExportReviewLogRow(Model):
    created_at: str
    word: str
    action: str
    context: str
    prev_state: UserState | None = None
    new_state: UserState | None = None
    prev_interval: int | None = None
    new_interval: int | None = None


class ExportJson(Model):
    version: int
    exported_at: str
    username: str
    words: list[ExportWordRow]
    review_logs: list[ExportReviewLogRow] = Field(default_factory=list)


class OnboardingRequest(Model):
    stages: list[Stage]
    current_stage: Stage
    timezone: str
    push_time: str

    @field_validator("stages")
    @classmethod
    def _stages(cls, v: list[str]) -> list[str]:
        return _unique_stages(v)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if not is_valid_timezone(v):
            raise ValueError("未知的时区")
        return v

    @field_validator("push_time")
    @classmethod
    def _push_time(cls, v: str) -> str:
        if not PUSH_TIME_RE.match(v):
            raise ValueError("推送时间格式为 HH:MM")
        return v

    @model_validator(mode="after")
    def _current_in_stages(self) -> "OnboardingRequest":
        if self.current_stage not in self.stages:
            raise ValueError("主攻阶段必须包含在目标阶段中")
        return self


class OnboardingResponse(Model):
    settings: Settings
    onboarding_state: Literal["screen"]


class OnboardingCompleteResponse(Model):
    onboarding_state: Literal["done"]


class SettingsUpdateRequest(Model):
    """``PUT /api/settings`` — any subset of the writable ``Settings`` fields."""

    timezone: str | None = None
    push_time: str | None = None
    push_enabled: bool | None = None
    daily_new_count: int | None = Field(default=None, ge=0, le=50)
    daily_screen_count: int | None = Field(default=None, ge=0, le=50)
    max_reviews: int | None = Field(default=None, ge=0, le=300)
    stages: list[Stage] | None = None
    current_stage: Stage | None = None
    show_images: bool | None = None
    zh_examples: Literal["tap", "always"] | None = None
    auto_pronounce: bool | None = None
    accent: Literal["en-US", "en-GB"] | None = None
    dance_mode: DanceMode | None = None
    image_word: bool | None = None
    email_enabled: bool | None = None
    webhook_enabled: bool | None = None
    webhook_url: str | None = None
    webhook_format: WebhookFormat | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_timezone(v):
            raise ValueError("未知的时区")
        return v

    @field_validator("push_time")
    @classmethod
    def _push_time(cls, v: str | None) -> str | None:
        if v is not None and not PUSH_TIME_RE.match(v):
            raise ValueError("推送时间格式为 HH:MM")
        return v

    @field_validator("stages")
    @classmethod
    def _stages(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _unique_stages(v)

    @field_validator("webhook_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 2048:
            raise ValueError("Webhook 地址过长")
        return v or None

    @model_validator(mode="after")
    def _consistent(self) -> "SettingsUpdateRequest":
        if self.stages is not None and self.current_stage is not None and self.current_stage not in self.stages:
            raise ValueError("主攻阶段必须包含在目标阶段中")
        return self


class TimezonesResponse(Model):
    items: list[str]


class WebhookTestResponse(Model):
    ok: bool
    http_status: int | None
    error: str | None  # English transport diagnostic (admin ledger wording); the UI renders `reason`, never this
    reason: WebhookTestReason | None  # None when ok


class EmailTestResponse(Model):
    queued: bool


# ------------------------------------------------------------------------------ vocabulary
class StageInfo(Model):
    stage: Stage
    index: StageIndex
    name_zh: str
    total: int
    new_only_total: int
    unfamiliar: int
    known: int
    mastered: int
    unseen: int


class StagesResponse(Model):
    items: list[StageInfo]


class WordBrief(Model):
    id: int
    lemma: str
    display: str
    kind: WordKind
    phonetic: str | None
    translation_short: str
    stages: list[Stage]
    stage_min: StageIndex | None
    cet6_star: bool
    frq: int | None
    collins: int | None
    oxford: bool | None
    difficulty: int | None
    is_public: bool
    is_valid_english: bool | None
    my_state: UserState | None
    content_state: ContentState
    image_state: ImageState


class VocabQuery(Model):
    """Query parameters of ``GET /api/vocab`` (endpoint 20); ``/vocab/letters`` uses the same minus ``letter``/``q``."""

    stage: Literal["all", "xs", "zk", "gk", "cet4", "cet6"] = "all"
    new_only: Literal[0, 1] = 0
    q: str | None = Field(default=None, max_length=64)
    status: Literal["all", "unmarked", "unfamiliar", "known", "mastered"] = "all"
    sort: Literal["freq", "alpha", "difficulty"] = "freq"
    letter: str | None = Field(default=None, pattern=r"^[a-z]$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def _new_only_needs_stage(self) -> "VocabQuery":
        if self.new_only == 1 and self.stage == "all":
            raise ValueError("new_only 需要指定具体阶段")
        return self


class LetterCount(Model):
    letter: str
    count: int


class LettersResponse(Model):
    items: list[LetterCount]


class Srs(Model):
    ease: float
    interval_days: int
    step: Literal[0, 1]
    repetitions: int
    lapses: int
    consecutive_good: int
    due_at: str | None
    last_graded_at: str | None
    mastery_suggested: bool


class UserWord(Model):
    id: int
    word_id: int
    state: UserState
    origin: Origin
    priority: int
    note: str | None
    input_text: str | None
    needs_attention: bool
    attention_msg: str | None
    suggested_word: WordBrief | None
    srs: Srs
    times_pushed: int
    times_added: int
    added_at: str
    first_added_at: str
    mastered_at: str | None


class Example(Model):
    en: str
    zh: str


class Content(Model):
    word: str
    valid: bool
    meaning_zh: str
    meaning_en: str
    examples: list[Example]
    collocations: list[str]
    mnemonic_zh: str
    image_keywords: list[str]
    image_alt_zh: str
    difficulty: Difficulty
    version: int
    prompt_version: str
    model: str
    created_at: str


class Attribution(Model):
    title: str | None
    creator: str | None
    creator_url: str | None
    license: str
    license_url: str | None
    landing_url: str | None
    text: str


class ImageMeta(Model):
    """API.md §9 ``ImageMeta``. ``word_layer`` / ``hook_zh`` / ``note_zh`` describe a 记忆图卡 (docs/MEMORY_CARDS_DESIGN.md §3.3;
    ``images.memo.is_memo``): ``url + '?plain=1'`` is the same picture without the word (endpoint 52), and the hook is what the
    记忆 section shows instead of ``content.mnemonic_zh``. Photos, older drawings and the template card: ``false`` / ``null`` / ``null``."""

    id: int | None
    url: str
    kind: Literal["photo", "svg", "card"]
    provider: ImageProviderName
    mime: Literal["image/jpeg", "image/svg+xml"]
    width: int | None
    height: int | None
    alt_zh: str | None
    attribution: Attribution | None
    word_layer: bool
    dancing: bool
    hook_zh: str | None
    note_zh: str | None


class WordForm(Model):
    form: str
    kind: str


class DanceMarks(Model):
    """Letter indexes into the display form (API.md §9 ``DanceSpec.marks``): doubled letters jump together, silent letters stay."""

    double: list[tuple[int, int]]
    silent: list[int]


class DanceParams(Model):
    """Parameters of a semantic primitive (API.md §9 ``DanceSpec.semantic.params``): ``n`` copies for ``multiply``, the colour for ``color``."""

    n: int | None = None
    color: DanceColor | None = None


class DanceSemantic(Model):
    """The one meaning motion of a word (WORD_DANCE_DESIGN §4.3), chosen by Claude from the closed ``DancePrimitive`` list."""

    primitive: DancePrimitive
    params: DanceParams


class DanceSpec(Model):
    """API.md §9 ``DanceSpec`` — the 「单词之舞」 data: syllable chunks (``"".join(letters) == display``), the primary-stressed chunk,
    letter marks and the optional semantic dance. ``source="rule"`` = ``wd.dance.rule_spec`` at serialisation time (P1, no semantic);
    ``source="claude"`` = the word has a stored ``word_dances`` row: its semantic, and its chunks and stress where the model corrected
    the rule suggestion (``word_dances.corrected``), else the current rules' chunks and stress (P2 / P3b)."""

    version: Literal[1]
    letters: list[str]
    stress: int | None
    marks: DanceMarks
    semantic: DanceSemantic | None
    source: Literal["rule", "claude"]


class DemoWord(Model):
    """One item of ``GET /api/demo`` (endpoint 77): a public word with its content, card image and dance for the login page."""

    word: WordBrief
    content: Content | None
    image: ImageMeta
    dance: DanceSpec | None


class DemoResponse(Model):
    items: list[DemoWord]


class WordDetailWord(WordBrief):
    definition: str | None
    translation: str | None
    pos: str | None
    exam_tags: list[str]
    bnc: int | None
    forms: list[WordForm]
    source: WordSource
    confusables: list[str]
    dance: DanceSpec | None


class ReviewLogItem(Model):
    id: int
    created_at: str
    action: str
    context: str
    prev_state: UserState | None
    new_state: UserState | None
    prev_interval: int | None
    new_interval: int | None


class WordDetail(Model):
    word: WordDetailWord
    content: Content | None
    content_state: ContentState
    content_deferred_until: str | None
    image: ImageMeta
    mine: UserWord | None
    redirected_from: str | None
    history: list[ReviewLogItem]


class ContentResponse(Model):
    """``GET /api/words/{id}/content`` (endpoint 24)."""

    state: ContentState
    content: Content | None
    eta_s: int | None
    deferred_until: str | None


class LookupPreview(Model):
    input: str
    normalized: str | None
    valid: bool
    reason_zh: str | None
    via: Literal["exact", "form", "ambiguous", "ecdict", "none", "invalid"]
    match: WordBrief | None
    lemma_note_zh: str | None
    candidates: list[WordBrief]
    suggestions: list[WordBrief]
    mine: UserWord | None


class LookupQuery(Model):
    q: str = Field(min_length=1, max_length=200)


class MarkRequest(Model):
    action: MarkAction
    note: str | None = Field(default=None, max_length=500)
    context: Literal["browse", "detail", "bank", "today", "screen_page"] | None = None


class MarkResponse(Model):
    word_id: int
    state: UserState | None
    mine: UserWord | None
    status: Literal["added", "readded", "exists", "noop", "restored"]


class BatchMarkItem(Model):
    word_id: int
    action: Literal["unfamiliar", "known"]


class BatchMarkRequest(Model):
    items: list[BatchMarkItem] = Field(min_length=1, max_length=100)


class BatchMarkResult(Model):
    word_id: int
    ok: bool
    state: UserState | None
    error: str | None


class BatchMarkResponse(Model):
    updated: int
    results: list[BatchMarkResult]


class ReportRequest(Model):
    target: Literal["content", "image", "dictionary"]
    reason: ReportReason
    note: str | None = Field(default=None, max_length=300)


class ReportCreatedResponse(Model):
    id: int


class ImageRefreshResponse(Model):
    job_id: int
    image_state: Literal["queued"]


class ContentRequestResponse(Model):
    job_id: int | None
    state: ContentState


# -------------------------------------------------------------------------------- screening
class ScreenNextQuery(Model):
    stage: Literal["xs", "zk", "gk", "cet4", "cet6", "auto"] = "auto"
    count: int = Field(default=1, ge=1, le=50)


class ScreenWord(Model):
    word: WordBrief
    phonetic: str | None


class ScreenNextResponse(Model):
    items: list[ScreenWord]
    remaining: int


class ScreenVerdictRequest(Model):
    client_event_id: str
    word_id: int
    verdict: ScreenVerdict
    context: Literal["screen_page", "onboarding"] | None = None

    @field_validator("client_event_id")
    @classmethod
    def _uuid(cls, v: str) -> str:
        return _check_uuid(v)


class TodayCounts(Model):
    total: int
    done: int
    review: int
    review_done: int
    new: int
    new_done: int
    screen: int
    screen_done: int
    extra: int
    extra_done: int
    pending_content: int
    deferred_reviews: int


class StudyItemWord(WordBrief):
    definition: str | None
    translation: str | None
    pos: str | None
    forms: list[str]
    confusables: list[str]
    dance: DanceSpec | None


class StudyItem(Model):
    item_id: int
    kind: ItemKind
    position: int
    result: str | None
    skip_count: int
    requeue_at: str | None
    word: StudyItemWord
    mine: UserWord | None
    content: Content | None
    content_state: ContentState
    content_deferred_until: str | None
    image: ImageMeta


class ScreenResponse(Model):
    word_id: int
    verdict: ScreenVerdict
    mine: UserWord | None
    added_to_today: bool
    study_item: StudyItem | None
    today: TodayCounts | None
    duplicate: bool


# -------------------------------------------------------------------------------------- bank
class BankQuery(Model):
    state: Literal["active", "new", "learning", "mastered", "known", "removed", "attention"] = "active"
    q: str | None = Field(default=None, max_length=64)
    sort: Literal["added", "due", "alpha", "ease", "times_added"] = "added"
    origin: Origin | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class BankItem(WordBrief):
    mine: UserWord


class BankCounts(Model):
    new: int
    learning: int
    mastered: int
    known: int
    removed: int
    attention: int
    due_today: int


class BankResponse(Page[BankItem]):
    counts: BankCounts


class BankAddRequest(Model):
    text: str = Field(min_length=1, max_length=4000)
    note: str | None = Field(default=None, max_length=500)
    study_today: bool = False


class BankAddWordRequest(Model):
    word_id: int
    note: str | None = Field(default=None, max_length=500)
    study_today: bool = False


class AddResult(Model):
    input: str
    status: Literal["added", "readded", "exists", "pending_ai", "ambiguous", "invalid"]
    word: WordBrief | None
    mine: UserWord | None
    resolved_via: Literal["exact", "form", "ecdict", "provisional"] | None
    lemma_note_zh: str | None
    candidates: list[WordBrief]
    error: str | None
    message: str | None
    added_to_today: bool


class AddResponse(Model):
    results: list[AddResult]
    added: int
    readded: int
    exists: int
    pending_ai: int
    ambiguous: int
    invalid: int


class ImportRequest(Model):
    format: Literal["csv", "json"]
    data: str = Field(min_length=1)


class ImportResponse(AddResponse):
    rows: int
    skipped: int


class BankPatchRequest(Model):
    """``PATCH /api/bank/{word_id}`` — at least one of ``note`` / ``attention`` (endpoint 36)."""

    note: str | None = Field(default=None, max_length=500)
    attention: Literal["keep", "retry"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _at_least_one(cls, data: Any) -> Any:
        if isinstance(data, dict) and not ({"note", "attention"} & set(data)):
            raise ValueError("至少提供 note 或 attention 之一")
        return data


class AcceptSuggestionResponse(Model):
    removed_word_id: int
    mine: UserWord


class ConsolidateResponse(Model):
    job_id: int


class SuggestionPayload(Model):
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    note_zh: str | None = None
    confidence: float | None = None
    group: list[str] | None = None
    fields: list[str] | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


class Suggestion(Model):
    id: int
    type: SuggestionType
    status: SuggestionStatus
    user_word: BankItem | None
    target: WordBrief | None
    payload: SuggestionPayload
    created_at: str
    expires_at: str | None
    resolved_at: str | None


class SuggestionsQuery(Model):
    status: Literal["open", "all"] = "open"


class SuggestionsResponse(Model):
    items: list[Suggestion]
    open_count: int


class SuggestionResult(Model):
    applied: bool
    mine: UserWord | None
    removed_word_id: int | None
    message_zh: str


class SuggestionActionResponse(Model):
    result: SuggestionResult


class EmptyResponse(Model):
    """``{}`` (endpoint 41)."""


# ------------------------------------------------------------------------------------- today
class Batch(Model):
    id: int
    local_date: str
    timezone: str
    status: BatchStatus
    trigger: str
    gradable: bool
    counts: TodayCounts
    items: list[StudyItem]
    extra_rounds: int
    can_request_more: bool
    built_at: str
    published_at: str | None
    completed_at: str | None


class PreviousOpenBatch(Model):
    id: int
    local_date: str
    remaining: int


class TodayResponse(Model):
    status: Literal["none", "building", "ready", "published"]
    local_date: str
    push_time: str
    next_push_at: str | None
    can_build_now: bool
    batch: Batch | None
    streak_days: int
    goal_met: bool
    added: int | None
    previous_open_batch: PreviousOpenBatch | None
    suggestions_open: int


class ListenItem(Model):
    """One word of the 磨耳朵 playlist (endpoint 123, ``services/listen.py``): what a voice says for it, derived on the server so
    every client speaks the same strings — and the strings endpoint 76 accepts."""

    item_id: int
    word_id: int
    kind: ItemKind  # review | new | extra — 推荐词 are not listened to
    done: bool  # push_items.result IS NOT NULL: the item has its final grade (it is played all the same)
    display: str
    phonetic: str | None
    spoken_en: str | None  # the headword as a voice reads it (`sb.` / `sth.` spelled out); null when the English text rule refuses it
    meaning_zh: str  # shown, never spoken: content.meaning_zh, else the dictionary's main sense, else ''
    gloss_zh: str | None  # the speakable Chinese gloss: at most two senses, no part-of-speech labels, no brackets; null when none can be derived
    sentence_en: str | None  # the first example sentence the English text rule accepts; null without content
    sentence_zh: str | None  # its translation when the Chinese text rule accepts it


class ListenPlaylist(Model):
    """Endpoint 123: today's review / new / extra words in batch order, one row per word, the words that have left the bank since
    (已掌握 / 已认识 / removed) left out; ``batch_id`` null (and no items) when the user has no batch today."""

    batch_id: int | None
    local_date: str
    items: list[ListenItem]


class GradeRequest(Model):
    client_event_id: str
    grade: Literal["again", "hard", "good", "master", "skip", "known", "unfamiliar"]
    elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)

    @field_validator("client_event_id")
    @classmethod
    def _uuid(cls, v: str) -> str:
        return _check_uuid(v)


class GradeResponseItem(Model):
    item_id: int
    result: str | None
    skip_count: int
    requeue_at: str | None


class GradeResponse(Model):
    item: GradeResponseItem
    mine: UserWord | None
    next_due_zh: str
    mastery_suggested: bool
    today: TodayCounts
    duplicate: bool
    study_item: StudyItem | None


class MoreRequest(Model):
    source: Literal["new", "screen"]
    count: int = Field(default=10, ge=1, le=20)


class SessionSummary(Model):
    local_date: str
    review: int
    new: int
    extra: int
    screen: int
    again: int
    hard: int
    good: int
    mastered: int
    known: int
    unfamiliar: int
    study_minutes: int
    streak_days: int
    goal_met: bool
    next_push_at: str | None
    can_request_more: bool


class CompleteResponse(Model):
    summary: SessionSummary


# ----------------------------------------------------------------------------------- history
class HistoryQuery(Model):
    from_: str = Field(alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$")
    to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DayStats(Model):
    date: str
    graded: int
    again: int
    hard: int
    good: int
    mastered: int
    known: int
    screened: int
    added: int
    study_minutes: int
    batch_id: int | None
    batch_total: int | None
    batch_done: int | None
    offline: bool


class HistoryResponse(Model):
    days: list[DayStats]
    streak_days: int
    longest_streak: int


class BatchSummary(Model):
    id: int
    local_date: str
    status: str
    trigger: str
    counts: TodayCounts
    published_at: str | None
    completed_at: str | None


class PageQuery(Model):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class StatsToday(Model):
    done: int
    total: int


class HeatmapPoint(Model):
    date: str
    graded: int
    goal_met: bool


class Stats(Model):
    bank: BankCounts
    stages: list[StageInfo]
    custom_words: int
    streak_days: int
    longest_streak: int
    today: StatsToday | None
    total_graded: int
    total_mastered: int
    heatmap: list[HeatmapPoint]
    stubborn: list[WordBrief]


# ------------------------------------------------------------------------------------- admin
class AdminOverviewUsers(Model):
    total: int
    active_7d: int


class AdminOverviewWords(Model):
    total: int
    with_content: int
    with_photo: int
    with_claude_svg: int
    card_only: int
    user_added: int
    pending_validation: int


class AdminOverviewJobs(Model):
    queued: int
    running: int
    dead: int
    by_type: dict[str, int]


class AdminOverviewAi(Model):
    enabled: bool
    paused_until: str | None  # the CLI's automatic pause or the admin's global pause, whichever ends later (CLAUDE_INTEGRATION §10.5)
    manual_paused_until: str | None  # the admin's own pause alone (kv ai.paused_until while in the future) — what 「暂停/恢复 AI」 toggles
    flag_tier: FlagTier
    today_usd: float
    month_usd: float
    daily_budget_usd: float
    monthly_budget_usd: float
    svg_today_usd: float
    svg_daily_budget_usd: float
    dance_today_usd: float  # generate_dance (单词之舞 annotations) today, against WD_AI_DANCE_DAILY_BUDGET_USD
    dance_daily_budget_usd: float
    calls_today: int
    avg_cost_per_word_7d: float | None
    last_error: str | None
    active_provider: AiProvider  # kv ai.active_provider (CLAUDE_INTEGRATION §10)
    fallback_configured: bool  # Settings.fallback_configured
    fallback_paused_until: str | None  # kv ai.fallback.paused_until while it lies in the future
    fallback_calls_today: int  # ai_calls rows with provider='fallback' started today (WD_TZ)
    fallback_available: bool | None  # kv ai.fallback.available: None = never probed, False = marked unavailable until the next fallback success (§10.6)


class ProviderQuota(Model):
    provider: str
    minute_count: int
    day_count: int
    minute_limit: int | None
    day_limit: int | None
    cooldown_until: str | None


class AdminOverviewImages(Model):
    providers: list[ProviderQuota]


class AdminOverviewScheduler(Model):
    last_tick_at: str | None
    alive: bool


class SystemEvent(Model):
    id: int
    kind: str
    detail: dict[str, Any]
    created_at: str


class SmsUsage(Model):
    """``AdminOverview.sms`` (API.md 54): the site-wide SMS counters against the ``WD_SMS_*`` caps (WD_TZ day / current hour);
    ``registration_open`` = code sends for new accounts are still allowed (below 70 % of the day cap)."""

    provider: str
    sent_today: int
    daily_cap: int
    sent_hour: int
    hourly_cap: int
    registration_open: bool


class AdminOverview(Model):
    users: AdminOverviewUsers
    words: AdminOverviewWords
    bank_entries: int
    batches_today: int
    jobs: AdminOverviewJobs
    ai: AdminOverviewAi
    images: AdminOverviewImages
    scheduler: AdminOverviewScheduler
    sms: SmsUsage
    events_24h: list[SystemEvent]


class ClaudeBinInfo(Model):
    path: str
    version: str | None
    ok: bool
    flag_tier: FlagTier
    last_probe_at: str | None


class WorkerLeaseInfo(Model):
    instance: str
    expires_at: str


class LastBackupInfo(Model):
    file: str
    at: str
    bytes: int


class AdminHealth(Model):
    db_ok: bool
    db_size_bytes: int
    disk_free_bytes: int
    data_dir: str
    scheduler_alive: bool
    scheduler_last_tick_at: str | None
    claude_worker_alive: bool
    io_worker_alive: bool
    claude_bin: ClaudeBinInfo
    seed_version: str | None
    migrations_version: int
    worker_lease: WorkerLeaseInfo | None
    last_backup: LastBackupInfo | None


class AdminUser(User):
    is_active: bool
    last_login_at: str | None
    bank_size: int
    streak_days: int


class DisputedIdentityUser(Model):
    id: int
    username: str
    display_name: str


class DisputedIdentity(Model):
    """Endpoints 92 / 93: a phone binding the number's new owner disputed (``identities.disputed_at``); ``current_user_id`` is the
    account now holding the live binding, ``subject_masked`` the number as ``138****8000``."""

    id: int
    user: DisputedIdentityUser
    provider: IdentityProvider
    subject_masked: str
    verified_at: str
    last_login_at: str | None
    disputed_at: str
    current_user_id: int | None


class AdminUsersQuery(Model):
    q: str | None = Field(default=None, max_length=64)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class AdminUserUpdateRequest(Model):
    is_active: bool | None = None
    role: Role | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def _at_least_one(cls, data: Any) -> Any:
        if isinstance(data, dict) and not ({"is_active", "role", "new_password"} & set(data)):
            raise ValueError("至少提供一个要修改的字段")
        return data


class InviteInfo(Model):
    id: int
    max_uses: int
    uses: int
    expires_at: str | None
    note: str
    created_at: str
    created_by: int | None


class InvitesResponse(Model):
    items: list[InviteInfo]


class InviteCreateRequest(Model):
    max_uses: int = Field(default=1, ge=1, le=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    note: str | None = Field(default=None, max_length=200)


class InviteCreatedResponse(Model):
    id: int
    code: str
    expires_at: str | None


class AdminJobsQuery(Model):
    status: Literal["queued", "running", "done", "dead", "cancelled"] | None = None
    type: Literal["generate_content", "lookup_word", "consolidate_bank", "generate_svg", "fetch_image", "send_email", "send_webhook", "prewarm_plan", "generate_dance"] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class Job(Model):
    id: int
    type: str
    payload: dict[str, Any]
    dedupe_key: str | None
    priority: int
    status: str
    attempts: int
    max_attempts: int
    run_after: str
    locked_by: str | None
    last_error: str | None
    created_at: str
    finished_at: str | None


class RequeueDeadResponse(Model):
    requeued: int


class RunOnceResponse(Model):
    processed: int


class AiCall(Model):
    id: int
    kind: str
    status: str
    provider: AiProvider  # which provider served the call (migration 0010, CLAUDE_INTEGRATION §10)
    model_requested: str
    model_used: str | None
    flag_tier: FlagTier
    word_count: int
    cost_usd: float
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    error: str | None
    started_at: str


class AiCallsPage(Page[AiCall]):
    today_usd: float
    month_usd: float
    avg_cost_per_word_7d: float | None


class AiPauseRequest(Model):
    paused: bool


class AiPauseResponse(Model):
    paused: bool
    paused_until: str | None


class ProbeRequest(Model):
    """Body of ``POST /api/admin/ai/probe`` (API.md 66): which provider to probe (CLAUDE_INTEGRATION §2 / §10.6)."""

    provider: AiProvider = "claude"


class ProbeResponse(Model):
    ok: bool
    flag_tier: FlagTier
    cost_usd: float
    duration_ms: int
    model_used: str | None
    error: str | None


class PrewarmRequest(Model):
    stage: Literal["xs", "zk", "gk", "cet4", "cet6", "all"]
    limit: int = Field(ge=1, le=2000)
    max_budget_usd: float = Field(ge=0.1, le=50)


class PrewarmResponse(Model):
    job_id: int
    planned: int


class JobIdResponse(Model):
    job_id: int


class RefetchImageRequest(Model):
    provider: Literal["wikimedia", "openverse", "pixabay", "pexels", "claude_svg"] | None = None
    query: str | None = Field(default=None, max_length=100)


class ReportUser(Model):
    id: int
    username: str


class Report(Model):
    id: int
    user: ReportUser
    word: WordBrief
    target: Literal["content", "image", "dictionary"]
    reason: ReportReason
    note: str | None
    status: Literal["open", "resolved", "dismissed"]
    resolution: str | None
    created_at: str
    resolved_at: str | None


class AdminReportsQuery(Model):
    status: Literal["open", "resolved", "dismissed"] = "open"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class ReportResolveRequest(Model):
    status: Literal["resolved", "dismissed"]
    regenerate: bool = False
    refetch_image: bool = False


class ConfigEntry(Model):
    key: str
    value: Any
    source: Literal["env", "default"]


class ConfigResponse(Model):
    entries: list[ConfigEntry]


class PushRunRequest(Model):
    user_id: int


class PushRunResponse(Model):
    batch_id: int
    status: BatchStatus


# ------------------------------------------------------------------------------ catalogue
#: endpoint number → (request model | None, response model) — keeps the §2 catalogue checkable in tests
ENDPOINT_MODELS: dict[int, tuple[type[BaseModel] | None, type[BaseModel]]] = {
    1: (None, HealthResponse),
    2: (RegisterRequest, AuthResponse),
    3: (LoginRequest, AuthResponse),
    5: (None, MeResponse),
    6: (AccountUpdateRequest, UserResponse),
    7: (PasswordChangeRequest, EmptyResponse),
    8: (AccountDeleteRequest, EmptyResponse),
    9: (None, CodeSendResponse),
    10: (EmailVerifyRequest, UserResponse),
    11: (None, ExportJson),
    12: (OnboardingRequest, OnboardingResponse),
    13: (None, OnboardingCompleteResponse),
    14: (None, Settings),
    15: (SettingsUpdateRequest, Settings),
    16: (None, TimezonesResponse),
    17: (None, WebhookTestResponse),
    18: (None, EmailTestResponse),
    19: (None, StagesResponse),
    20: (VocabQuery, Page[WordBrief]),
    21: (VocabQuery, LettersResponse),
    22: (LookupQuery, LookupPreview),
    23: (None, WordDetail),
    24: (None, ContentResponse),
    25: (None, ImageMeta),
    26: (MarkRequest, MarkResponse),
    27: (BatchMarkRequest, BatchMarkResponse),
    28: (ReportRequest, ReportCreatedResponse),
    29: (None, ImageRefreshResponse),
    30: (None, ContentRequestResponse),
    31: (ScreenNextQuery, ScreenNextResponse),
    32: (ScreenVerdictRequest, ScreenResponse),
    33: (BankQuery, BankResponse),
    34: (BankAddRequest, AddResponse),
    35: (BankAddWordRequest, AddResult),
    36: (BankPatchRequest, UserWord),
    37: (None, AcceptSuggestionResponse),
    38: (None, ConsolidateResponse),
    39: (SuggestionsQuery, SuggestionsResponse),
    40: (None, SuggestionActionResponse),
    41: (None, EmptyResponse),
    42: (None, SuggestionActionResponse),
    43: (None, TodayResponse),
    44: (None, TodayResponse),
    45: (GradeRequest, GradeResponse),
    46: (MoreRequest, TodayResponse),
    47: (None, CompleteResponse),
    48: (HistoryQuery, HistoryResponse),
    49: (PageQuery, Page[BatchSummary]),
    50: (None, TodayResponse),
    51: (None, Stats),
    54: (None, AdminOverview),
    55: (None, AdminHealth),
    56: (AdminUsersQuery, Page[AdminUser]),
    57: (AdminUserUpdateRequest, AdminUser),
    58: (None, InvitesResponse),
    59: (InviteCreateRequest, InviteCreatedResponse),
    60: (AdminJobsQuery, Page[Job]),
    61: (None, Job),
    62: (None, RequeueDeadResponse),
    63: (None, RunOnceResponse),
    64: (PageQuery, AiCallsPage),
    65: (AiPauseRequest, AiPauseResponse),
    66: (ProbeRequest, ProbeResponse),
    67: (PrewarmRequest, PrewarmResponse),
    68: (None, JobIdResponse),
    69: (RefetchImageRequest, JobIdResponse),
    70: (AdminReportsQuery, Page[Report]),
    71: (ReportResolveRequest, Report),
    72: (PageQuery, Page[SystemEvent]),
    73: (None, ConfigResponse),
    74: (PushRunRequest, PushRunResponse),
    75: (ImportRequest, ImportResponse),
    # sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md; 76 /media/audio and 78 /media/demo/{id}.svg are files, not JSON)
    77: (None, DemoResponse),
    79: (None, CaptchaChallenge),
    80: (CodeSendRequest, CodeSendResponse),
    81: (CodeLoginRequest, CodeLoginResponse),
    82: (ChallengeEmailRequest, CodeSendResponse),
    83: (ChallengeConfirmRequest, AuthResponse),
    84: (ChallengeDisputeRequest, AuthResponse),
    85: (AccountCodeRequest, CodeSendResponse),
    86: (PhoneBindRequest, UserResponse),
    87: (PhoneUnbindRequest, UserResponse),
    88: (PhoneRebindRequest, UserResponse),
    89: (ProfileRequest, UserResponse),
    90: (ForgotPasswordRequest, CodeSendResponse),
    91: (ResetPasswordRequest, EmptyResponse),
    92: (PageQuery, Page[DisputedIdentity]),
    93: (None, DisputedIdentity),
    # guardian + child accounts (docs/AUTH_SIGNUP_DESIGN.md §5.1–5.2, slice 1-B)
    94: (None, ChildrenResponse),
    95: (ChildCreateRequest, ChildResponse),
    96: (ChildUpdateRequest, ChildResponse),
    97: (None, EmptyResponse),
    98: (None, EmptyResponse),
    99: (None, ChildLoginCode),
    100: (ChildPhoneCodeRequest, CodeSendResponse),
    101: (ChildEmancipateRequest, ChildResponse),
    102: (GateRequest, GateResponse),
    103: (PinRequest, EmptyResponse),
    104: (None, AuthResponse),
    105: (SwitchBackRequest, AuthResponse),
    106: (SwitchCodeRequest, CodeSendResponse),
    107: (ChildLoginRequest, AuthResponse),
    108: (GuardianClaimCodeRequest, CodeSendResponse),
    109: (GuardianClaimRequest, UserResponse),
    110: (DeclareRequest, UserResponse),
    111: (None, EmptyResponse),
    # third-party sign-in (docs/AUTH_SIGNUP_DESIGN.md §5.3, slice 2-A); 114 is a PNG and 118–122 are redirects — no JSON model
    112: (WechatTicketRequest, WechatTicket),
    113: (None, WechatTicketStatus),
    115: (WechatScanRequest, WechatScanInfo),
    116: (WechatConfirmRequest, WechatConfirmResult),
    117: (IdentityUnbindRequest, UserResponse),
    # 磨耳朵 (docs/LISTEN_MODE_DESIGN.md §4.3): today's words as a listening playlist
    123: (None, ListenPlaylist),
}
