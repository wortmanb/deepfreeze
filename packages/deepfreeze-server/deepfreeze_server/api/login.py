"""Elasticsearch-based login endpoint.

Users authenticate with their ES credentials.  The server validates them
by creating a temporary ES client and calling ``security.authenticate()``.
On success a short-lived session token is returned and cached in memory.
"""

import collections
import logging
import secrets
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from deepfreeze_core.esclient import create_es_client

logger = logging.getLogger("deepfreeze.server.login")

router = APIRouter()

# In-memory session store: token → {username, authenticated_at, expires_at}
_sessions: dict[str, dict] = {}

SESSION_TTL = 8 * 60 * 60  # 8 hours

# Per-IP login rate limiting
_LOGIN_WINDOW = 60  # seconds
_LOGIN_MAX_ATTEMPTS = 5  # max attempts per window per IP
_login_attempts: dict[str, collections.deque] = {}


def _check_rate_limit(ip: str) -> bool:
    """Return True if the request should be allowed, False if rate-limited."""
    now = time.monotonic()
    if ip not in _login_attempts:
        _login_attempts[ip] = collections.deque()
    window = _login_attempts[ip]
    # Evict timestamps outside the window
    while window and window[0] < now - _LOGIN_WINDOW:
        window.popleft()
    if len(window) >= _LOGIN_MAX_ATTEMPTS:
        return False
    window.append(now)
    return True


class LoginRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    api_key: str | None = None  # ES API key (id:key or encoded)


class LoginResponse(BaseModel):
    token: str
    username: str
    expires_in: int = SESSION_TTL


class UserInfo(BaseModel):
    username: str
    authenticated: bool = True


def _purge_expired() -> None:
    """Remove expired sessions."""
    now = time.time()
    expired = [k for k, v in _sessions.items() if v["expires_at"] < now]
    for k in expired:
        del _sessions[k]


def get_session(token: str) -> dict | None:
    """Look up a session by token, returning None if missing or expired."""
    _purge_expired()
    return _sessions.get(token)


def remove_session(token: str) -> None:
    """Remove a session."""
    _sessions.pop(token, None)


def _build_es_kwargs(raw_config: dict) -> dict:
    """Extract connection kwargs (hosts, TLS) from server config."""
    es_section = raw_config.get("elasticsearch", {})
    kwargs: dict = {}
    if "hosts" in es_section:
        kwargs["hosts"] = es_section["hosts"]
    if "cloud_id" in es_section:
        kwargs["cloud_id"] = es_section["cloud_id"]
    if "ca_certs" in es_section:
        kwargs["ca_certs"] = es_section["ca_certs"]
    if "verify_certs" in es_section:
        kwargs["verify_certs"] = es_section["verify_certs"]
    return kwargs


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    """Authenticate against Elasticsearch and return a session token.

    Accepts either username/password or an ES API key.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        logger.warning("Login rate limit exceeded for %s", client_ip)
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many login attempts. Try again later."},
            headers={"Retry-After": str(_LOGIN_WINDOW)},
        )

    raw_config: dict = request.app.state.raw_config
    es_kwargs = _build_es_kwargs(raw_config)

    # Determine auth method
    identity_label = "unknown"
    if body.api_key:
        es_kwargs["api_key"] = body.api_key
        identity_label = "api_key"
    elif body.username and body.password:
        es_kwargs["basic_auth"] = (body.username, body.password)
        identity_label = body.username
    else:
        return JSONResponse(
            status_code=400,
            content={"detail": "Provide username/password or api_key"},
        )

    try:
        client = create_es_client(**es_kwargs)
        info = client.security.authenticate()
        # Prefer full_name or email over the raw username (which may be
        # an opaque ID for SAML/OIDC users).
        es_username = (
            info.get("full_name")
            or info.get("email")
            or info.get("username")
            or identity_label
        )
        client.close()
    except Exception as e:
        logger.info("Login failed for '%s': %s", identity_label, e)
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid Elasticsearch credentials"},
        )

    # Create session
    token = f"dfs_{secrets.token_urlsafe(32)}"
    now = time.time()
    _sessions[token] = {
        "username": es_username,
        "authenticated_at": now,
        "expires_at": now + SESSION_TTL,
    }
    _purge_expired()

    logger.info("User '%s' logged in successfully", es_username)
    return LoginResponse(token=token, username=es_username)


@router.get("/auth/me", response_model=UserInfo)
async def me(request: Request):
    """Return info about the currently authenticated user."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        session = get_session(token)
        if session:
            return UserInfo(username=session["username"])

    # Check if request was authenticated by token middleware
    auth_name = getattr(request.state, "auth_name", None)
    if auth_name:
        return UserInfo(username=auth_name)

    return JSONResponse(status_code=401, content={"detail": "Not authenticated"})


@router.post("/auth/logout")
async def logout(request: Request):
    """Invalidate the current session."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        remove_session(token)
    return {"status": "ok"}
