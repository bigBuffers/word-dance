"""Dependency-free RSASSA-PKCS1-v1_5 / SHA-256 signature verification for Apple id_tokens (API.md §3.3 endpoint 121;
``delivery/apple.verify_id_token``).

Slice 2-A: the names and signatures here are what ``delivery/apple.py`` and ``tests/unit/test_rsa_verify.py`` (good signature, a flipped
bit, the wrong key, a modulus shorter than 2048 bits refused, a padding mismatch) build against.

Why pure Python: the box keeps its dependency list short, the CSP forbids a third-party script on the web side, and verifying is a
single modular exponentiation — ``m = pow(int(sig), e, n)``, ``EM = m.to_bytes(k)`` with ``k`` the modulus size in bytes, compared in
constant time (``hmac.compare_digest``) with ``b"\\x00\\x01" + b"\\xff" * (k - 3 - len(T)) + b"\\x00" + T`` where ``T`` is the DER
``DigestInfo`` of SHA-256 (:data:`SHA256_DIGEST_INFO` + ``sha256(message)``). Only RS256 with a modulus of at least :data:`MIN_MODULUS_BITS`
is accepted (Apple's keys are 2048-bit); signing is never implemented here — the fake provider's signer lives in ``delivery/apple.py``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re

MIN_MODULUS_BITS = 2048
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")  # DER prefix of DigestInfo(SHA-256) — RFC 8017 §9.2 note 1
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]*$")  # the RFC 7515 alphabet, padding already stripped


def b64url_decode(text: str) -> bytes:
    """Base64url (RFC 7515 alphabet, padding optional) → bytes; ``ValueError`` on a malformed string."""
    if not isinstance(text, str):
        raise ValueError("base64url input must be a string")
    body = text.strip().rstrip("=")
    if not _B64URL_RE.match(body) or len(body) % 4 == 1:  # a character outside the alphabet, or a length no encoding produces
        raise ValueError("malformed base64url")
    standard = body.replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(standard + "=" * (-len(standard) % 4), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("malformed base64url") from e


def b64url_to_int(text: str) -> int:
    """A JWK ``n`` / ``e`` parameter (base64url big-endian unsigned) → ``int``."""
    data = b64url_decode(text)
    if not data:
        raise ValueError("empty JWK integer")
    return int.from_bytes(data, "big")


def modulus_bytes(n: int) -> int:
    """``k`` — the length of the modulus in bytes (``ceil(bit_length / 8)``)."""
    return (int(n).bit_length() + 7) // 8


def verify_pkcs1_v15_sha256(message: bytes, signature: bytes, *, n: int, e: int) -> bool:
    """True when ``signature`` is a valid RSASSA-PKCS1-v1_5 SHA-256 signature of ``message`` under the public key ``(n, e)``; False on any
    mismatch (wrong key, a flipped bit, a wrong length, bad padding) — never an exception for a bad signature. A modulus shorter than
    :data:`MIN_MODULUS_BITS` or an exponent that is even or below 3 (RFC 8017: ``e`` is odd, ``e >= 3``) raises ``ValueError`` (refused,
    not merely False)."""
    n = int(n)
    e = int(e)
    if n.bit_length() < MIN_MODULUS_BITS:
        raise ValueError(f"RSA modulus of {n.bit_length()} bits refused: at least {MIN_MODULUS_BITS} bits are required")
    if e < 3 or e % 2 == 0:  # RFC 8017: e is odd and at least 3 — e = 1 would make `pow(s, 1, n) == s`, i.e. anyone could "sign" by supplying EM itself
        raise ValueError("RSA public exponent must be an odd integer of at least 3")
    k = modulus_bytes(n)
    if len(signature) != k:  # RFC 8017 §8.2.2 step 1: the signature is exactly k octets
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:  # step 2a: the representative must be in [0, n - 1]
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    if k < len(t) + 11:  # EMSA-PKCS1-v1_5: at least 8 octets of 0xff padding
        return False
    expected = b"\x00\x01" + b"\xff" * (k - 3 - len(t)) + b"\x00" + t
    return hmac.compare_digest(em, expected)


__all__ = ["MIN_MODULUS_BITS", "SHA256_DIGEST_INFO", "b64url_decode", "b64url_to_int", "modulus_bytes", "verify_pkcs1_v15_sha256"]
