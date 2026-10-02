import secrets
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.schemas import AdminPrincipal


bearer_scheme = HTTPBearer(auto_error=False)


def get_api_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_db_session(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> Iterator[Session]:
    with session_factory() as session:
        yield session


def require_admin(
    settings: Annotated[Settings, Depends(get_api_settings)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
) -> AdminPrincipal:
    configured = (
        settings.admin_api_key.get_secret_value()
        if settings.admin_api_key is not None
        else ""
    )
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin authentication is not configured",
        )
    if (
        credentials is None
        or credentials.scheme.casefold() != "bearer"
        or not secrets.compare_digest(credentials.credentials, configured)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AdminPrincipal(reviewer_identity=settings.admin_reviewer_identity)


def get_admin_principal(
    principal: Annotated[AdminPrincipal, Depends(require_admin)],
) -> AdminPrincipal:
    return principal
