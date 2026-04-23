from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
import bcrypt
from app.config import get_settings

class InvalidToken(Exception):
    pass

def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode(), salt).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

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
