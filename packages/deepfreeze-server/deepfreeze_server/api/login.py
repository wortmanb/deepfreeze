"""Elasticsearch-based login endpoint.

Users authenticate with their ES credentials.  The server validates them
by creating a temporary ES client and calling ``security.authenticate()``.
On success a short-lived session token is returned and cached in memory.
"""

import logging
import secrets
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from deepfreeze_core.esclient import create_es_client

logger = logging.getLogger("deepfreeze.server.login")

router = APIRouter()

# In-memory session store: token → {username, authenticated_at, expires_at}
_sessions: dict[str, dict] = {}

SESSION_TTL = 8 * 60 * 60  # 8 hours


class LoginRequest(BaseModel):
    username: str
    password: str


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


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    """Authenticate against Elasticsearch and return a session token."""
    # Build ES connection config from the server's raw config, but
    # substitute the user-supplied credentials.
    raw_config: dict = request.app.state.raw_config
    es_section = raw_config.get("elasticsearch", {})

    es_kwargs: dict = {}
    if "hosts" in es_section:
        es_kwargs["hosts"] = es_section["hosts"]
    if "cloud_id" in es_section:
        es_kwargs["cloud_id"] = es_section["cloud_id"]
    if "ca_certs" in es_section:
        es_kwargs["ca_certs"] = es_section["ca_certs"]
    if "verify_certs" in es_section:
        es_kwargs["verify_certs"] = es_section["verify_certs"]

    # Use the provided credentials
    es_kwargs["basic_auth"] = (body.username, body.password)

    try:
        client = create_es_client(**es_kwargs)
        info = client.security.authenticate()
        es_username = info.get("username", body.username)
        client.close()
    except Exception as e:
        logger.info("Login failed for user '%s': %s", body.username, e)
        from fastapi.responses import JSONResponse
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

    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=401, content={"detail": "Not authenticated"})


@router.post("/auth/logout")
async def logout(request: Request):
    """Invalidate the current session."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        remove_session(token)
    return {"status": "ok"}
