from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import AuthContext, get_auth_context, get_current_user, get_db
from app.api.schemas.auth import AuthUserRead, LoginRequest, LoginResponse
from app.core.security import create_access_token, verify_password
from app.db.models import RevokedToken, User
from app.services.auth_security import (
    clear_login_attempts,
    record_login_attempt,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _user_read(user: User) -> AuthUserRead:
    return AuthUserRead(
        id=user.id,
        agency_id=user.agency_id,
        agency_name=user.agency.name,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    client_ip = request.client.host if request.client is not None else "unknown"
    is_rate_limited, retry_after = record_login_attempt(db, client_ip, payload.email)
    if is_rate_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.scalar(
        select(User)
        .where(func.lower(User.email) == payload.email)
        .options(joinedload(User.agency))
    )
    password_hash = user.password_hash if user else None
    password_valid = verify_password(payload.password, password_hash)
    if user is None or not password_valid or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clear_login_attempts(db, client_ip, payload.email)
    token, expires_at, _token_id = create_access_token(user.id)
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=_user_read(user),
    )


@router.get("/me", response_model=AuthUserRead)
def current_user(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AuthUserRead:
    user = db.scalar(select(User).where(User.id == user.id).options(joinedload(User.agency)))
    return _user_read(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> Response:
    expires_at = datetime.fromtimestamp(int(context.claims["exp"]), tz=timezone.utc)
    db.add(
        RevokedToken(
            jti=context.claims["jti"],
            user_id=context.user.id,
            expires_at=expires_at,
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
