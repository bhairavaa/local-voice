"""Request-scoped dependency resolution and authentication."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.runtime.context import EngineContext, context_of
from app.runtime.services import Services

_bearer_scheme = HTTPBearer(auto_error=False)


def get_context(request: Request) -> EngineContext:
    """Return the engine context attached to the application at startup."""
    return context_of(request.app)


ContextDep = Annotated[EngineContext, Depends(get_context)]


def get_services(context: ContextDep) -> Services:
    """Return the long-lived services assembled at startup."""
    return context.services


ServicesDep = Annotated[Services, Depends(get_services)]


def require_token(
    context: ContextDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> None:
    """Reject any request not bearing this session's engine token.

    The token is minted per launch and handed to the desktop shell over the startup
    handshake, so another local process cannot drive the engine even though the listener
    is reachable on loopback.
    """
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, context.auth_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing engine token",
            headers={"WWW-Authenticate": "Bearer"},
        )
