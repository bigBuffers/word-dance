"""wd/rsa_verify.py — the dependency-free RSASSA-PKCS1-v1_5 / SHA-256 check behind Apple's id_token (API.md §3.3 endpoint 121): a good
signature verifies, a flipped bit / the wrong key / a wrong length / bad padding are False (never an exception), a modulus shorter than
2048 bits or an exponent that is even or below 3 (e = 1 would accept the encoded message itself as a signature) is refused with
ValueError, and the base64url helpers decode what Apple's JWKS carries."""

from __future__ import annotations

import base64
import hashlib

import pytest

from wd import rsa_verify
from wd.delivery.apple import FAKE_KEY_D, FAKE_KEY_E, FAKE_KEY_N, fake_sign

# a second 2048-bit key and a 1024-bit key, generated once with the same throwaway Miller-Rabin script as the fake Apple key (never real keys)
SECOND_N = 21309607285713903866968167996361124222419920357825422932524560177744309311923095823673679061530086707882503297979768325449698818910825067481591283460545126542122361644907823969396134398310222929154423276327953239282083055998983488330069363869396453051878461818447918507751940966071494608967289285761735999980755840156724871680898552522960224352734887454145888590387321780966730562077201091805888611462883171713378757248165203757249018465017758921779280491579455435548391939958041600332022194042653024030537107504190235592565055713863746425027182078870581098922820005257397645207789328914253673018474688407760067570541
SECOND_E = 65537
SECOND_D = 2862085398029742135175863355752776381079325327214685277138323539749299581013398083737913568203506503569872967249682099313206454808090238342307961530747262464034004574345635191336453057166580096405839789493838997825208898479745066300766789113316064648609139730860936428046134586090343064555629981775123071025955346738640249694894001198263409798218646671370335588212335871553786472103872407578752393193436350201276048903256121196794074848643460492531799328997516404075748733609953142192049313409131029281094300262369618308440079173399683496719486054183574257557191794040135730434080037416698975895687421717429405357569
SHORT_N = 134459699995874575686553203266964593619056946129311559476648366606875194652412089548648004942906867646718732374456450070083483350426205082566792688773503024431699385679433873726220931415429776741748280166804031520331749940270623841018993809063280285517327788227847939654304066043920111431467860423058885534807
SHORT_E = 65537
SHORT_D = 63960528363693637136705923552308180204679803707543645065909529410399227814653507052185811893970148143589979428012875641772626050163067327601503914926132658774449912050084729467467431785453231242187297746688560409032127239653762753434269122050886198555284617345560720421307454652124829079591625610812000886473

MESSAGE = b"eyJhbGciOiJSUzI1NiIsImtpZCI6ImZha2UtYXBwbGUta2V5LTEifQ.eyJzdWIiOiJhcHBsZV94In0"


def _sign(message: bytes, *, n: int, d: int, em: bytes | None = None) -> bytes:
    """``fake_sign`` with an optional hand-built encoded message (for the padding tests)."""
    if em is None:
        return fake_sign(message, n=n, d=d)
    k = rsa_verify.modulus_bytes(n)
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def test_the_fixed_test_keys_have_the_promised_shape():
    assert FAKE_KEY_N.bit_length() == 2048 and SECOND_N.bit_length() == 2048 and SHORT_N.bit_length() == 1024
    assert FAKE_KEY_E == SECOND_E == SHORT_E == 65537
    assert rsa_verify.modulus_bytes(FAKE_KEY_N) == 256 and rsa_verify.modulus_bytes(SHORT_N) == 128 and rsa_verify.modulus_bytes(1) == 1
    for n, e, d in ((FAKE_KEY_N, FAKE_KEY_E, FAKE_KEY_D), (SECOND_N, SECOND_E, SECOND_D), (SHORT_N, SHORT_E, SHORT_D)):
        m = 123456789
        assert pow(pow(m, d, n), e, n) == m  # the private exponent inverts the public one


def test_a_good_signature_verifies_under_its_own_key_only():
    signature = _sign(MESSAGE, n=FAKE_KEY_N, d=FAKE_KEY_D)
    assert len(signature) == 256
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, signature, n=FAKE_KEY_N, e=FAKE_KEY_E) is True
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, signature, n=SECOND_N, e=SECOND_E) is False  # the wrong key
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE + b"x", signature, n=FAKE_KEY_N, e=FAKE_KEY_E) is False  # another message
    second = _sign(MESSAGE, n=SECOND_N, d=SECOND_D)
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, second, n=SECOND_N, e=SECOND_E) is True
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, second, n=FAKE_KEY_N, e=FAKE_KEY_E) is False


def test_a_flipped_bit_anywhere_in_the_signature_is_false():
    signature = bytearray(_sign(MESSAGE, n=FAKE_KEY_N, d=FAKE_KEY_D))
    for index in (0, 1, 100, 255):
        tampered = bytearray(signature)
        tampered[index] ^= 0x01
        assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, bytes(tampered), n=FAKE_KEY_N, e=FAKE_KEY_E) is False, index


def test_wrong_lengths_and_out_of_range_representatives_are_false():
    signature = _sign(MESSAGE, n=FAKE_KEY_N, d=FAKE_KEY_D)
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, signature[:-1], n=FAKE_KEY_N, e=FAKE_KEY_E) is False
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, signature + b"\x00", n=FAKE_KEY_N, e=FAKE_KEY_E) is False
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, b"", n=FAKE_KEY_N, e=FAKE_KEY_E) is False
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, FAKE_KEY_N.to_bytes(256, "big"), n=FAKE_KEY_N, e=FAKE_KEY_E) is False  # s == n


def test_padding_mismatches_are_false_even_when_signed_with_the_right_key():
    """RFC 8017 §9.2: the encoded message must be exactly 00 01 FF…FF 00 DigestInfo(SHA-256) || hash — anything else is forged structure."""
    k = 256
    digest = hashlib.sha256(MESSAGE).digest()
    good_t = rsa_verify.SHA256_DIGEST_INFO + digest
    good_em = b"\x00\x01" + b"\xff" * (k - 3 - len(good_t)) + b"\x00" + good_t
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, _sign(MESSAGE, n=FAKE_KEY_N, d=FAKE_KEY_D, em=good_em), n=FAKE_KEY_N, e=FAKE_KEY_E) is True
    sha1_info = bytes.fromhex("3021300906052b0e03021a05000414")
    bad_ems = [
        b"\x00\x02" + b"\xff" * (k - 3 - len(good_t)) + b"\x00" + good_t,  # block type 2 (encryption padding)
        b"\x00\x01" + b"\xff" * (k - 4 - len(good_t)) + b"\x00\x00" + good_t,  # a zero inside the FF run
        b"\x00\x01" + b"\xff" * (k - 3 - len(good_t)) + b"\x01" + good_t,  # no separator
        b"\x00\x01" + b"\xff" * (k - 3 - 20 - len(sha1_info)) + b"\x00" + sha1_info + hashlib.sha1(MESSAGE).digest(),  # SHA-1 DigestInfo
        b"\x00\x01" + b"\xff" * (k - 3 - len(digest)) + b"\x00" + digest,  # the bare hash without DigestInfo
        b"\x00\x01" + b"\xff" * (k - 3 - len(good_t)) + b"\x00" + rsa_verify.SHA256_DIGEST_INFO + hashlib.sha256(b"other").digest(),  # another hash
        b"\x00\x01" + b"\xff" * (k - 5 - len(good_t)) + b"\x00" + good_t + b"\x00\x00",  # the hash not at the end (Bleichenbacher-style)
    ]
    for em in bad_ems:
        assert len(em) == k
        assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, _sign(MESSAGE, n=FAKE_KEY_N, d=FAKE_KEY_D, em=em), n=FAKE_KEY_N, e=FAKE_KEY_E) is False


def test_short_moduli_and_bad_exponents_are_refused_not_merely_false():
    signature = _sign(MESSAGE, n=SHORT_N, d=SHORT_D)
    assert len(signature) == 128
    with pytest.raises(ValueError, match="2048"):
        rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, signature, n=SHORT_N, e=SHORT_E)  # a valid signature under a 1024-bit key is still refused
    with pytest.raises(ValueError):
        rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, b"\x00" * 256, n=2**2047 - 1, e=65537)  # 2047 bits
    for e in (0, -3, 1, 2, 4, 65536):  # RFC 8017: e is odd and at least 3
        with pytest.raises(ValueError, match="exponent"):
            rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, b"\x00" * 256, n=FAKE_KEY_N, e=e)
    # e = 1 is the dangerous one: pow(s, 1, n) == s, so the encoded message itself would "verify" — refused before any arithmetic
    k = 256
    em = b"\x00\x01" + b"\xff" * (k - 3 - 19 - 32) + b"\x00" + rsa_verify.SHA256_DIGEST_INFO + hashlib.sha256(MESSAGE).digest()
    with pytest.raises(ValueError, match="exponent"):
        rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, em, n=FAKE_KEY_N, e=1)
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, em, n=FAKE_KEY_N, e=3) is False  # an odd e >= 3 is a key, and this is not its signature
    assert rsa_verify.verify_pkcs1_v15_sha256(MESSAGE, _sign(MESSAGE, n=FAKE_KEY_N, d=FAKE_KEY_D), n=FAKE_KEY_N, e=FAKE_KEY_E) is True
    assert rsa_verify.MIN_MODULUS_BITS == 2048
    assert rsa_verify.SHA256_DIGEST_INFO == bytes.fromhex("3031300d060960864801650304020105000420") and len(rsa_verify.SHA256_DIGEST_INFO) == 19


def test_base64url_helpers_decode_jwk_integers():
    n_b64 = base64.urlsafe_b64encode(FAKE_KEY_N.to_bytes(256, "big")).rstrip(b"=").decode("ascii")
    assert "=" not in n_b64 and rsa_verify.b64url_to_int(n_b64) == FAKE_KEY_N
    assert rsa_verify.b64url_to_int("AQAB") == 65537  # Apple's `e`
    assert rsa_verify.b64url_decode("YQ") == b"a" and rsa_verify.b64url_decode("YQ==") == b"a" and rsa_verify.b64url_decode(" YWI ") == b"ab"
    assert rsa_verify.b64url_decode("-_8") == b"\xfb\xff" and rsa_verify.b64url_decode("YQ=") == b"a"  # the url-safe alphabet; padding optional
    for bad in ("###", "a", "é", "YQ==YQ", "YW+", "YW/"):  # outside the alphabet (the standard alphabet included), a length no encoding produces
        with pytest.raises(ValueError):
            rsa_verify.b64url_decode(bad)
    with pytest.raises(ValueError):
        rsa_verify.b64url_to_int("")
    with pytest.raises(ValueError):
        rsa_verify.b64url_decode(None)  # type: ignore[arg-type]
