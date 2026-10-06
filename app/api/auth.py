import hashlib
import secrets
from typing import Annotated, Literal

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.editorial import EditorialError
from app.infrastructure.db.models import ApiUser
from app.infrastructure.db.session import get_db

Role = Literal["viewer", "editor", "reviewer", "publisher"]
bearer = HTTPBearer(auto_error=False)


def create_user(session: Session, name: str, roles: list[str]) -> tuple[ApiUser, str]:
    if (
        not name.strip()
        or len(name) > 100
        or not roles
        or not set(roles) <= {"viewer", "editor", "reviewer", "publisher"}
    ):
        raise EditorialError("USER_CONFIGURATION_INVALID", 422)
    if session.scalar(select(ApiUser).where(ApiUser.name == name)):
        raise EditorialError("USER_ALREADY_EXISTS")
    token = secrets.token_urlsafe(48)
    user = ApiUser(
        name=name,
        roles=list(dict.fromkeys(roles)),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        active=True,
    )
    session.add(user)
    session.flush()
    return user, token


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_db)],
) -> ApiUser:
    if credentials is None:
        raise HTTPException(401, "AUTHENTICATION_REQUIRED", headers={"WWW-Authenticate": "Bearer"})
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    user = session.scalar(
        select(ApiUser).where(ApiUser.token_hash == digest, ApiUser.active.is_(True))
    )
    if user is None:
        raise HTTPException(401, "AUTHENTICATION_FAILED", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_role(user: ApiUser, role: Role) -> None:
    if role not in user.roles:
        raise EditorialError("ROLE_REQUIRED", 403)
