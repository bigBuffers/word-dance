"""``/api/auth/fake/*`` — the dev-only fake consent pages of the QQ / Apple flows (slice 2-A, PLAN §5.2; API.md §3.3), included by
``main.py`` ONLY when ``WD_AUTH_FAKE_PROVIDERS=1`` (which itself needs ``WD_DEV=1``), so ``make smoke`` and a developer's browser can run
the three third-party flows end to end without any credentials. Never part of a production instance.

* ``GET /api/auth/fake/qq?state=`` → an HTML page 「假 QQ 登录」 with a 「同意」 link to ``/api/auth/qq/callback?code=qq-code-<random>&state=
  <state>`` and a 「取消」 link (``usercancel=1``) — what ``delivery.qq.FakeQQClient.authorize_url`` points at; the random code becomes the
  openid ``qq_<random>`` through the fake client, so every consent is a new fake QQ account;
* ``GET /api/auth/fake/apple?state=&nonce=`` → an HTML page whose form posts to ``/api/auth/apple/callback`` (``<form method=post>`` with a
  「同意」 submit button; the ``id_token`` is minted here with ``delivery.apple.fake_id_token`` — ``sub = "apple_" + random``, the nonce
  from the query, ``aud = cfg.apple_client_id or delivery.apple.FAKE_AUDIENCE``) and a 「取消」 form (``error=user_cancelled_authorize``).

The pages carry the CSP of the app (no inline script — the form is submitted by the user's click, nothing auto-runs; the inline style is
allowed by ``style-src 'unsafe-inline'``) and the zh copy lives in the templates here (the one place outside ``zh.ts`` / ``errors.CATALOGUE``
the contract allows it for the fake UI). The state and the nonce are echoed only inside HTML-escaped attribute values.
"""

from __future__ import annotations

import html
import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from ..config import Settings
from ..delivery.apple import FAKE_AUDIENCE, FAKE_SUB_PREFIX, fake_id_token
from ..delivery.qq import FAKE_CODE_PREFIX

log = logging.getLogger("wd.routers.auth_fake")

router = APIRouter()

QQ_CALLBACK_PATH = "/api/auth/qq/callback"
APPLE_CALLBACK_PATH = "/api/auth/apple/callback"
APPLE_CANCELLED = "user_cancelled_authorize"
STATE_MAX_LEN = 4096
NONCE_MAX_LEN = 128

_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;color:#222}"
    "h1{font-size:1.4rem}p.note{color:#666}.row{display:flex;gap:1rem;align-items:center;margin-top:1.5rem}"
    "a.btn,button{font:inherit;padding:.6rem 1.4rem;border-radius:.5rem;border:1px solid #888;background:#fff;color:#222;text-decoration:none;cursor:pointer}"
    "a.primary,button.primary{background:#1e66d0;border-color:#1e66d0;color:#fff}"
)


def _page(title: str, body: str) -> HTMLResponse:
    document = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>{body}"
        "<p class='note'>仅开发环境（WD_AUTH_FAKE_PROVIDERS=1）可见：这里不会连接任何第三方，也不会离开本机。</p>"
        "</body></html>"
    )
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})


@router.get("/api/auth/fake/qq", response_class=HTMLResponse, include_in_schema=False)
def fake_qq_consent(state: str = Query(..., min_length=1, max_length=STATE_MAX_LEN)):
    code = FAKE_CODE_PREFIX + secrets.token_hex(8)
    accept = f"{QQ_CALLBACK_PATH}?{urlencode({'code': code, 'state': state})}"
    cancel = f"{QQ_CALLBACK_PATH}?{urlencode({'usercancel': '1', 'state': state})}"
    log.info("fake qq consent page served", extra={"event": "fake_qq_consent"})
    return _page(
        "假 QQ 登录",
        "<p>这是开发用的假 QQ 互联授权页。点「同意」会以一个随机的假 QQ 身份完成登录 / 绑定，点「取消」则像在 QQ 里取消授权一样返回。</p>"
        f"<div class='row'><a class='btn primary' href='{html.escape(accept, quote=True)}'>同意</a>"
        f"<a class='btn' href='{html.escape(cancel, quote=True)}'>取消</a></div>",
    )


@router.get("/api/auth/fake/apple", response_class=HTMLResponse, include_in_schema=False)
def fake_apple_consent(request: Request, state: str = Query(..., min_length=1, max_length=STATE_MAX_LEN), nonce: str = Query(..., min_length=1, max_length=NONCE_MAX_LEN)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    sub = FAKE_SUB_PREFIX + secrets.token_hex(8)
    id_token = fake_id_token(sub, aud=cfg.apple_client_id or FAKE_AUDIENCE, nonce=nonce, now=now)
    hidden_state = f"<input type='hidden' name='state' value='{html.escape(state, quote=True)}'>"
    log.info("fake apple consent page served", extra={"event": "fake_apple_consent"})
    return _page(
        "假 Apple 登录",
        "<p>这是开发用的假「通过 Apple 登录」页。点「同意」会把一枚用测试密钥签名的 id_token 以表单方式提交到回调地址（和 Apple 的 form_post 一样），点「取消」则像在 Apple 的弹窗里取消一样返回。</p>"
        f"<div class='row'><form method='post' action='{APPLE_CALLBACK_PATH}'>{hidden_state}"
        f"<input type='hidden' name='id_token' value='{html.escape(id_token, quote=True)}'>"
        f"<input type='hidden' name='code' value='{html.escape('fake-code-' + secrets.token_hex(4), quote=True)}'>"
        "<button class='primary' type='submit'>同意</button></form>"
        f"<form method='post' action='{APPLE_CALLBACK_PATH}'>{hidden_state}<input type='hidden' name='error' value='{APPLE_CANCELLED}'>"
        "<button type='submit'>取消</button></form></div>",
    )
