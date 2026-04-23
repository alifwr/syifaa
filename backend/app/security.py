"""Password hashing and JWT helpers.

Password note: bcrypt truncates inputs past 72 bytes. We pre-hash the
plaintext with SHA-256 so passphrases of any length (and multi-byte
unicode) hash without silent collisions. Hashes produced this way are
NOT interchangeable with plain `bcrypt.hashpw(plain_bytes, salt)`; if
we ever need to migrate, re-hash on next successful login.

JWT note: `decode_jwt` preserves the underlying PyJWT error message in
`InvalidToken`. That message is useful for server-side logs but MUST NOT
be echoed verbatim to HTTP responses — callers should surface a uniform
"invalid or expired token" message to clients.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
import jwt
import bcrypt
from app.config import get_settings

class InvalidToken(Exception):
    pass

def _prehash(plain: str) -> bytes:
    # SHA-256 digest is always 32 bytes — well under bcrypt's 72-byte limit.
    return sha256(plain.encode("utf-8")).digest()

def hash_password(plain: str) -> str:
    # gensalt() default cost is 12 rounds (OWASP 2024 baseline).
    return bcrypt.hashpw(_prehash(plain), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))

def make_jwt(claims: dict[str, Any], ttl: timedelta) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {**claims, "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp())}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")

def decode_jwt(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise InvalidToken(str(e)) from e


from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    return Fernet(get_settings().fernet_key.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
