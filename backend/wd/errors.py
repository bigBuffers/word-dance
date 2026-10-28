"""API error envelope (Phase 0, frozen contract — API.md §1 / §1.1).

Every error — including Pydantic validation, which FastAPI would report as 422 — is returned as::

    {"error": {"code": "invalid_word", "message": "只能包含英文字母…", "details": {"input": "abc123"}}}

:class:`ApiError` is raised by routers/services; :func:`install_handlers` registers the
FastAPI handlers that turn ``ApiError``, ``RequestValidationError`` (→ 400 ``validation_error``
with ``details.fields``), Starlette ``HTTPException`` and unexpected exceptions (→ 500
``internal_error``, logged with the request id) into that envelope.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("wd.errors")

# code → (HTTP status, default Simplified-Chinese message). API.md §1.1 verbatim, plus the two transport-level
# codes every web app needs (``method_not_allowed`` 405, ``payload_too_large`` 413 for WD_MAX_BODY_BYTES).
CATALOGUE: dict[str, tuple[int, str]] = {
    "validation_error": (400, "请求参数无效"),
    "invalid_word": (400, "只能包含英文字母、空格、连字符、撇号和缩写点"),
    "too_many_words": (400, "一次最多添加 50 个单词"),
    "invalid_grade": (400, "该卡片不支持此评分"),
    "weak_password": (400, "密码至少 8 位，不能与用户名相同，也不能是常见密码"),
    "invalid_code": (400, "验证码错误或已过期"),
    "import_too_large": (400, "导入文件过大或无法解析（最多 2000 行）"),
    "unauthorized": (401, "请先登录"),
    "invalid_credentials": (401, "用户名或密码错误"),
    "forbidden": (403, "没有权限执行此操作"),
    "account_disabled": (403, "账号已被停用"),
    "registration_closed": (403, "当前不开放注册"),
    "invalid_invite": (403, "邀请码无效或已用完"),
    "csrf_rejected": (403, "请求来源校验失败，请刷新页面后重试"),
    "not_found": (404, "资源不存在"),
    "word_not_found": (404, "找不到该单词"),
    "batch_not_found": (404, "找不到该学习批次"),
    "method_not_allowed": (405, "不支持的请求方法"),
    "username_taken": (409, "用户名已被使用"),
    "email_taken": (409, "该邮箱已被使用"),
    "onboarding_required": (409, "请先完成初始设置"),
    "invalid_transition": (409, "当前状态不允许此操作"),
    "item_already_graded": (409, "该卡片已经评分"),
    "batch_not_ready": (409, "请先生成今日词汇"),
    "ambiguous_form": (409, "该词形对应多个单词，请选择"),
    "budget_exhausted": (409, "今日 AI 额度已用完，例句将在明天补齐"),
    "email_not_verified": (409, "请先验证邮箱"),
    "smtp_unconfigured": (409, "服务器未配置邮件发送"),
    "webhook_unconfigured": (409, "尚未配置 Webhook"),
    "already_resolved": (409, "该建议已处理"),
    "undo_expired": (409, "撤销时限已过"),
    "last_admin": (409, "不能停用、降级或删除最后一位管理员"),
    "payload_too_large": (413, "请求体过大"),
    "account_locked": (423, "登录失败次数过多，账号已暂时锁定"),
    "rate_limited": (429, "操作过于频繁，请稍后再试"),
    "internal_error": (500, "服务器内部错误"),
    "ai_disabled": (503, "AI 功能当前不可用"),
    "email_send_failed": (503, "邮件发送失败，请稍后重试"),
}

_STATUS_TO_CODE = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "invalid_transition",
    413: "payload_too_large",
    423: "account_locked",
    429: "rate_limited",
    500: "internal_error",
    503: "ai_disabled",
}


class ApiError(Exception):
    """An error with a stable ``code``; ``status`` and ``message_zh`` default from :data:`CATALOGUE`."""

    def __init__(
        self,
        code: str,
        status: int | None = None,
        message_zh: str | None = None,
        details: Mapping[str, Any] | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ):
        default_status, default_message = CATALOGUE.get(code, (500, "服务器内部错误"))
        self.code = code
        self.status = status if status is not None else default_status
        self.message_zh = message_zh if message_zh is not None else default_message
        self.details: dict[str, Any] | None = dict(details) if details else None
        self.headers: dict[str, str] = dict(headers) if headers else {}
        super().__init__(f"{self.status} {self.code}: {self.message_zh}")

    def to_body(self) -> dict[str, Any]:
        return envelope(self.code, self.message_zh, self.details)

    def to_response(self) -> JSONResponse:
        headers = dict(self.headers)
        retry = (self.details or {}).get("retry_after_s")
        if self.code in ("rate_limited", "account_locked") and retry is not None and "Retry-After" not in headers:
            headers["Retry-After"] = str(int(retry))
        return JSONResponse(status_code=self.status, content=self.to_body(), headers=headers)


def envelope(code: str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = dict(details)
    return body


def error_response(code: str, status: int | None = None, message_zh: str | None = None, details: Mapping[str, Any] | None = None) -> JSONResponse:
    """Build an envelope response directly (used by middleware, which cannot raise into FastAPI)."""
    return ApiError(code, status, message_zh, details).to_response()


def _validation_fields(exc: RequestValidationError) -> dict[str, str]:
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path", "header", "cookie")]
        key = ".".join(loc) if loc else "body"
        msg = str(err.get("msg", "invalid"))
        fields.setdefault(key, msg)
    return fields


def install_handlers(app: FastAPI) -> None:
    """Register the envelope handlers on ``app`` (called by ``main.create_app``)."""

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:  # pragma: no cover - trivial glue
        return exc.to_response()

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response("validation_error", details={"fields": _validation_fields(exc)})

    @app.exception_handler(ResponseValidationError)
    async def _response_validation(request: Request, exc: ResponseValidationError) -> JSONResponse:
        log.error("response validation failed: %s", exc, extra={"request_id": getattr(request.state, "request_id", None)})
        return error_response("internal_error")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:  # an envelope raised through HTTPException
            return JSONResponse(status_code=exc.status_code, content=detail, headers=exc.headers or {})
        code = _STATUS_TO_CODE.get(exc.status_code, "http_error")
        _, default_msg = CATALOGUE.get(code, (exc.status_code, "请求失败"))
        message = default_msg if code != "http_error" else (str(detail) if detail else "请求失败")
        return JSONResponse(status_code=exc.status_code, content=envelope(code, message), headers=exc.headers or {})

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        rid = getattr(request.state, "request_id", None)
        log.exception("unhandled error (request %s)", rid, extra={"request_id": rid, "path": request.url.path})
        return error_response("internal_error", details={"request_id": rid} if rid else None)
