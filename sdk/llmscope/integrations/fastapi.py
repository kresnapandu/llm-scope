"""
FastAPI middleware for llm-scope.
Automatically injects request metadata (user_id, route, etc.) into trace context.
"""

from __future__ import annotations

import uuid
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..context import trace_context


class LLMScopeMiddleware(BaseHTTPMiddleware):
    """
    Starlette/FastAPI middleware that injects per-request context into
    all LLM spans created during request handling.

    Usage:
        app = FastAPI()
        app.add_middleware(
            LLMScopeMiddleware,
            user_id_extractor=lambda req: req.headers.get("X-User-Id"),
            session_id_extractor=lambda req: req.headers.get("X-Session-Id"),
        )

    Args:
        user_id_extractor: Async or sync callable that takes a Request and
                           returns the user ID string (or None).
        session_id_extractor: Async or sync callable that takes a Request and
                              returns the session ID string (or None).
    """

    def __init__(
        self,
        app,
        user_id_extractor: Optional[Callable] = None,
        session_id_extractor: Optional[Callable] = None,
    ) -> None:
        super().__init__(app)
        self._user_id_extractor = user_id_extractor
        self._session_id_extractor = session_id_extractor

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        import inspect

        # Extract user_id
        user_id: Optional[str] = None
        if self._user_id_extractor:
            result = self._user_id_extractor(request)
            if inspect.isawaitable(result):
                user_id = await result
            else:
                user_id = result

        # Extract session_id
        session_id: Optional[str] = None
        if self._session_id_extractor:
            result = self._session_id_extractor(request)
            if inspect.isawaitable(result):
                session_id = await result
            else:
                session_id = result

        # Generate a request ID for correlation
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        route = request.url.path

        with trace_context(
            user_id=user_id,
            session_id=session_id,
            feature=route,
            tags={
                "http.route": route,
                "http.method": request.method,
                "http.request_id": request_id,
            },
        ):
            response = await call_next(request)

        return response
