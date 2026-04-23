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
