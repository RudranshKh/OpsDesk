from collections.abc import Generator
from dataclasses import dataclass
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import Assignment, RevokedToken, Ticket, User
from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: User
    claims: dict


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthContext:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = decode_access_token(credentials.credentials)
        user_id = int(claims["sub"])
        token_id = claims["jti"]
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized

    if db.get(RevokedToken, token_id) is not None:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return AuthContext(user=user, claims=claims)


def get_current_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user


def require_roles(*roles: str) -> Callable:
    def role_dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return role_dependency


def get_ticket_for_user(
    ticket_id: int,
    user: User,
    db: Session,
    *,
    write: bool = False,
) -> Ticket:
    ticket = db.scalar(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.agency_id == user.agency_id)
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if write and user.role == "agent":
        assigned_to_user = db.scalar(
            select(Assignment.id).where(
                Assignment.ticket_id == ticket.id,
                Assignment.user_id == user.id,
                Assignment.unassigned_at.is_(None),
            )
        )
        if assigned_to_user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agents can update only tickets assigned to them",
            )
    return ticket
