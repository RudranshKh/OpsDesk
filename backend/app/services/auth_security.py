from datetime import datetime, timedelta, timezone
import hmac
from hashlib import sha256

from sqlalchemy import case, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import LoginRateLimit, RevokedToken
from app.core.config import settings

LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_ATTEMPT_LIMIT = 5
IP_LOGIN_ATTEMPT_LIMIT = 100


def _rate_limit_key(scope: str, material: str) -> str:
    material = f"{scope}\0{material}".encode("utf-8")
    return hmac.new(settings.jwt_secret_key.encode("utf-8"), material, sha256).hexdigest()


def _consume_bucket(db: Session, key: str, now: datetime, limit: int) -> tuple[int, int]:
    reset_before = now - LOGIN_WINDOW
    expired_window = LoginRateLimit.window_started_at <= reset_before
    statement = sqlite_insert(LoginRateLimit).values(
        key_hash=key,
        window_started_at=now,
        attempts=1,
    ).on_conflict_do_update(
        index_elements=[LoginRateLimit.key_hash],
        set_={
            "window_started_at": case(
                (expired_window, now), else_=LoginRateLimit.window_started_at
            ),
            "attempts": case(
                (expired_window, 1),
                (LoginRateLimit.attempts >= limit + 1, limit + 1),
                else_=LoginRateLimit.attempts + 1,
            ),
        },
    )
    db.execute(statement)
    row = db.execute(
        select(LoginRateLimit.attempts, LoginRateLimit.window_started_at).where(
            LoginRateLimit.key_hash == key
        )
    ).one()
    started_at = row.window_started_at
    if started_at.utcoffset() is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    retry_after = max(1, int((started_at + LOGIN_WINDOW - now).total_seconds()))
    return row.attempts, retry_after


def record_login_attempt(
    db: Session, client_ip: str, email: str, *, now: datetime | None = None
) -> tuple[bool, int]:
    """Atomically consume per-account/IP and per-IP attempt buckets."""
    now = now or datetime.now(timezone.utc)
    account_key = _rate_limit_key("account", f"{client_ip}\0{email.casefold()}")
    ip_key = _rate_limit_key("ip", client_ip)
    account_count, account_retry = _consume_bucket(db, account_key, now, LOGIN_ATTEMPT_LIMIT)
    ip_count, ip_retry = _consume_bucket(db, ip_key, now, IP_LOGIN_ATTEMPT_LIMIT)
    db.commit()
    account_blocked = account_count > LOGIN_ATTEMPT_LIMIT
    ip_blocked = ip_count > IP_LOGIN_ATTEMPT_LIMIT
    return (
        account_blocked or ip_blocked,
        max(
            account_retry if account_blocked else 0,
            ip_retry if ip_blocked else 0,
        ),
    )


def clear_login_attempts(db: Session, client_ip: str, email: str) -> None:
    db.execute(
        delete(LoginRateLimit).where(
            LoginRateLimit.key_hash
            == _rate_limit_key("account", f"{client_ip}\0{email.casefold()}")
        )
    )
    db.commit()


def cleanup_expired_auth_records(db: Session, *, now: datetime | None = None) -> int:
    """Remove only expired token revocations and elapsed rate-limit windows."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.utcoffset() is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    expired_login_windows = current_time - LOGIN_WINDOW
    revoked_result = db.execute(
        delete(RevokedToken).where(RevokedToken.expires_at <= current_time)
    )
    db.execute(
        delete(LoginRateLimit).where(
            LoginRateLimit.window_started_at <= expired_login_windows
        )
    )
    db.commit()
    return revoked_result.rowcount or 0
