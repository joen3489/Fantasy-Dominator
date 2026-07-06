from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

import httpx
import jwt
from fastapi import HTTPException, Request

from . import db


JWKS_PROVIDER: Callable[[], dict[str, Any]] | None = None
_JWKS_CACHE: dict[str, Any] | None = None
_JWKS_FETCHED_AT = 0.0
_UNKNOWN_KID_REFRESHED_AT = 0.0
_JWKS_LOCK = threading.Lock()


def verify_session_token(token: str, jwks_provider: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=401, detail="missing session token")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid session token") from exc

    kid = header.get("kid")
    key = _key_for_kid(str(kid or ""), jwks_provider)
    if key is None:
        key = _key_for_kid(str(kid or ""), jwks_provider, force_refresh=True)
    if key is None:
        raise HTTPException(status_code=401, detail="unknown token key")

    issuer = os.environ.get("CLERK_ISSUER", "")
    try:
        # SECURITY: RS256 signature verification rejects forged tokens signed without Clerk's private key.
        # SECURITY: The issuer check rejects validly signed tokens from the wrong Clerk instance.
        # SECURITY: PyJWT validates exp/nbf with leeway so expired or not-yet-valid sessions cannot be replayed.
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            issuer=issuer,
            leeway=60,
            options={"require": ["sub", "exp"], "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid session token") from exc

    authorized_parties = _authorized_parties()
    azp = claims.get("azp")
    # SECURITY: Clerk's azp claim, when present, prevents a cross-app browser session from being reused here.
    if azp and authorized_parties and str(azp) not in authorized_parties:
        raise HTTPException(status_code=401, detail="unauthorized token presenter")

    return dict(claims)


def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get("__session") or _bearer_token(request.headers.get("authorization", ""))
    try:
        claims = verify_session_token(token or "")
    except HTTPException as exc:
        if request.url.path.startswith("/api/"):
            raise exc
        raise HTTPException(status_code=303, headers={"Location": "/login"}, detail="login required") from exc
    return db.get_or_create_user(str(claims["sub"]))


def _key_for_kid(
    kid: str,
    jwks_provider: Callable[[], dict[str, Any]] | None = None,
    force_refresh: bool = False,
) -> Any | None:
    jwks = _jwks(jwks_provider, force_refresh=force_refresh)
    for raw_key in jwks.get("keys", []):
        if str(raw_key.get("kid") or "") == kid:
            return jwt.PyJWK.from_dict(raw_key).key
    return None


def _jwks(jwks_provider: Callable[[], dict[str, Any]] | None = None, force_refresh: bool = False) -> dict[str, Any]:
    provider = jwks_provider or JWKS_PROVIDER
    if provider is not None:
        return provider()

    global _JWKS_CACHE, _JWKS_FETCHED_AT, _UNKNOWN_KID_REFRESHED_AT
    now = time.monotonic()
    with _JWKS_LOCK:
        should_refresh = _JWKS_CACHE is None or now - _JWKS_FETCHED_AT > 3600
        if force_refresh:
            should_refresh = now - _UNKNOWN_KID_REFRESHED_AT >= 300
            if should_refresh:
                _UNKNOWN_KID_REFRESHED_AT = now
        if should_refresh:
            url = os.environ.get("CLERK_JWKS_URL", "")
            if not url:
                raise HTTPException(status_code=401, detail="auth is not configured")
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            _JWKS_CACHE = response.json()
            _JWKS_FETCHED_AT = now
        return _JWKS_CACHE or {}


def _authorized_parties() -> set[str]:
    raw = os.environ.get("CLERK_AUTHORIZED_PARTIES", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _bearer_token(value: str) -> str:
    prefix = "Bearer "
    return value[len(prefix) :].strip() if value.startswith(prefix) else ""
