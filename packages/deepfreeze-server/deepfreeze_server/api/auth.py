"""Authentication middleware stub.

Phase 5 will implement token-based auth with roles (admin, operator, viewer).
For now this is a no-op pass-through to establish the middleware hook point.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("deepfreeze.server.auth")


class AuthMiddleware(BaseHTTPMiddleware):
    """Placeholder auth middleware. Currently passes all requests through."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Phase 5: Extract Bearer token, validate against config, check roles
        return await call_next(request)
