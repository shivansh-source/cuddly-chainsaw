"""Email + password login with HS256 JWT (stdlib only).

Role (buyer | seller) and company_id come from the signed token, never from
the request body, so a caller cannot claim to be another company.
"""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.config import settings

TOKEN_TTL_SECONDS = 12 * 3600


class AuthError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(signing_input: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())


def create_token(claims: dict, secret: str | None = None, ttl: int = TOKEN_TTL_SECONDS) -> str:
    secret = secret or settings.jwt_secret
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({**claims, "exp": int(time.time()) + ttl},
                           separators=(",", ":")).encode())
    return f"{header}.{body}.{_sign(f'{header}.{body}', secret)}"


def decode_token(token: str, secret: str | None = None) -> dict:
    secret = secret or settings.jwt_secret
    try:
        header, body, signature = token.split(".")
        head = json.loads(_unb64(header))
        if head.get("alg") != "HS256":  # never trust the token's own algorithm choice
            raise AuthError("unsupported algorithm")
        if not hmac.compare_digest(signature, _sign(f"{header}.{body}", secret)):
            raise AuthError("bad signature")
        claims = json.loads(_unb64(body))
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError("malformed token") from exc
    if claims.get("exp", 0) < time.time():
        raise AuthError("token expired")
    return claims


@dataclass(frozen=True)
class User:
    email: str
    role: str          # "buyer" | "seller"
    company_id: str


def current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        claims = decode_token(authorization.split(" ", 1)[1].strip())
        return User(claims["sub"], claims["role"], claims["company_id"])
    except (AuthError, KeyError) as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc
