import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt


class AuthError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(
    user_id: str,
    role: str,
    secret_key: str,
    algorithm: str,
    expires_minutes: int,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes)
    payload = {
        "sub": user_id,
        "role": role,
        "jti": str(uuid.uuid4()),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def verify_access_token(token: str, secret_key: str, algorithm: str) -> dict:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        if payload.get("type") != "access" or not payload.get("sub"):
            raise AuthError("Token invalido")
        return payload
    except jwt.PyJWTError as exc:
        raise AuthError("Token invalido o expirado") from exc


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_refresh_token(redis, user_id: str, refresh_days: int) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(token)
    ttl_seconds = refresh_days * 24 * 60 * 60
    await redis.setex(f"refresh:{token_hash}", ttl_seconds, user_id)
    return token


async def consume_refresh_token(redis, refresh_token: str) -> str | None:
    token_hash = hash_refresh_token(refresh_token)
    key = f"refresh:{token_hash}"
    user_id = await redis.get(key)
    if not user_id:
        return None
    await redis.delete(key)
    return user_id


async def revoke_refresh_token(redis, refresh_token: str) -> None:
    token_hash = hash_refresh_token(refresh_token)
    await redis.delete(f"refresh:{token_hash}")


async def blacklist_access_token(redis, token_payload: dict) -> None:
    jti = token_payload.get("jti")
    exp = token_payload.get("exp")
    if not jti or not exp:
        return

    now_ts = int(datetime.now(timezone.utc).timestamp())
    ttl = max(1, int(exp) - now_ts)
    await redis.setex(f"blacklist:{jti}", ttl, "1")


async def is_blacklisted(redis, jti: str) -> bool:
    return bool(await redis.exists(f"blacklist:{jti}"))
