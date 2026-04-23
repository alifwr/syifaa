import pytest
from datetime import timedelta
from app.security import hash_password, verify_password, make_jwt, decode_jwt, InvalidToken

def test_hash_and_verify_password_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False

def test_hash_password_not_plaintext():
    h = hash_password("secret")
    assert "secret" not in h

def test_jwt_roundtrip():
    tok = make_jwt({"sub": "u1", "kind": "access"}, ttl=timedelta(minutes=5))
    payload = decode_jwt(tok)
    assert payload["sub"] == "u1"
    assert payload["kind"] == "access"

def test_jwt_invalid_signature_rejected():
    tok = make_jwt({"sub": "u1"}, ttl=timedelta(minutes=5))
    tampered = tok[:-2] + ("AB" if tok[-2:] != "AB" else "CD")
    with pytest.raises(InvalidToken):
        decode_jwt(tampered)

def test_jwt_expired_rejected():
    tok = make_jwt({"sub": "u1"}, ttl=timedelta(seconds=-1))
    with pytest.raises(InvalidToken):
        decode_jwt(tok)

def test_hash_password_no_collision_past_72_bytes():
    # Two passwords identical in their first 72 bytes but differing after
    # must hash to distinguishable digests — and verify correctly against
    # themselves only. This guards against bcrypt's native 72-byte truncation.
    a = "A" * 72 + "alpha-suffix"
    b = "A" * 72 + "beta-suffix"
    ha, hb = hash_password(a), hash_password(b)
    assert ha != hb
    assert verify_password(a, ha) is True
    assert verify_password(b, ha) is False
    assert verify_password(a, hb) is False
    assert verify_password(b, hb) is True

def test_hash_password_unicode_does_not_truncate():
    # Emoji are 4 bytes each in UTF-8; a string that is byte-long past 72
    # must still verify correctly.
    pw = "🔒" * 25  # 100 UTF-8 bytes
    h = hash_password(pw)
    assert verify_password(pw, h) is True
    assert verify_password("🔒" * 24, h) is False
