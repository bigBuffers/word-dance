"""wd/captcha.py (API.md 79): a 4-digit PNG data URI with a signed, time-limited, single-use token; wrong / expired / tampered /
reused answers are 400 invalid_captcha."""

from __future__ import annotations

import base64
import io
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from wd import captcha
from wd.errors import ApiError
from wd.schemas import CaptchaChallenge, CaptchaToken

NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
KEY = "test-secret-key-not-for-production"


def token(payload: dict, answer: str) -> dict:
    return {"id": payload["id"], "exp": payload["exp"], "sig": payload["sig"], "answer": answer}


def test_new_challenge_shape_and_image():
    payload, answer = captcha.new_challenge(KEY, NOW)
    CaptchaChallenge.model_validate(payload)
    assert set(payload) == {"id", "image", "exp", "sig", "expires_in_s"}
    assert len(answer) == 4 and answer.isdigit() and payload["expires_in_s"] == 120 and payload["exp"] == int(NOW.timestamp()) + 120
    assert payload["sig"] == captcha.signature(KEY, payload["id"], payload["exp"], answer) and len(payload["sig"]) == 64
    assert payload["image"].startswith("data:image/png;base64,")
    img = Image.open(io.BytesIO(base64.b64decode(payload["image"].split(",", 1)[1])))
    assert img.format == "PNG" and img.size == (captcha.WIDTH, captcha.HEIGHT)
    assert answer not in payload["id"] and answer not in payload["sig"] and len(payload["image"]) < 16000
    other, _ = captcha.new_challenge(KEY, NOW)
    assert other["id"] != payload["id"] and other["image"] != payload["image"]


def test_verify_round_trip_single_use_and_refusals(conn: sqlite3.Connection):
    payload, answer = captcha.new_challenge(KEY, NOW)
    captcha.verify(conn, KEY, token(payload, " " + answer[:2] + " " + answer[2:] + " "), NOW + timedelta(seconds=30))  # whitespace tolerated
    assert conn.execute("SELECT count FROM auth_throttle WHERE key = ?", (f"captcha:{payload['id']}",)).fetchone()[0] == 1
    with pytest.raises(ApiError) as e:
        captcha.verify(conn, KEY, token(payload, answer), NOW + timedelta(seconds=31))  # reuse
    assert e.value.code == "invalid_captcha" and e.value.status == 400
    # a wrong answer burns the challenge too (four digits must not be brute-forceable within the two minutes)
    payload2, answer2 = captcha.new_challenge(KEY, NOW)
    wrong = "0000" if answer2 != "0000" else "1111"
    with pytest.raises(ApiError):
        captcha.verify(conn, KEY, token(payload2, wrong), NOW)
    with pytest.raises(ApiError):
        captcha.verify(conn, KEY, token(payload2, answer2), NOW)
    # expired: nothing is written to auth_throttle
    payload3, answer3 = captcha.new_challenge(KEY, NOW)
    with pytest.raises(ApiError):
        captcha.verify(conn, KEY, token(payload3, answer3), NOW + timedelta(seconds=120))
    assert conn.execute("SELECT COUNT(*) FROM auth_throttle WHERE key = ?", (f"captcha:{payload3['id']}",)).fetchone()[0] == 0
    captcha.verify(conn, KEY, token(payload3, answer3), NOW + timedelta(seconds=119))
    # tampering: another key, another id, a forged exp, a far-future exp
    payload4, answer4 = captcha.new_challenge(KEY, NOW)
    for bad in (
        {**token(payload4, answer4), "sig": captcha.signature("other", payload4["id"], payload4["exp"], answer4)},
        {**token(payload4, answer4), "id": "x" + payload4["id"][1:]},
        {**token(payload4, answer4), "exp": payload4["exp"] + 1},
        {**token(payload4, answer4), "exp": payload4["exp"] + 86400},
        {**token(payload4, answer4), "exp": "soon"},
        {"id": "", "exp": payload4["exp"], "sig": payload4["sig"], "answer": answer4},
    ):
        with pytest.raises(ApiError) as e:
            captcha.verify(conn, KEY, bad, NOW)
        assert e.value.code == "invalid_captcha"
    # the pydantic request model works as the token too
    payload5, answer5 = captcha.new_challenge(KEY, NOW)
    captcha.verify(conn, KEY, CaptchaToken(id=payload5["id"], exp=payload5["exp"], sig=payload5["sig"], answer=answer5), NOW)
    # the single-use throttle outlives the TTL
    with pytest.raises(ApiError):
        captcha.verify(conn, KEY, token(payload5, answer5), NOW + timedelta(seconds=60))
