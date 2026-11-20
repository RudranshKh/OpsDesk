from datetime import datetime, timedelta, timezone
import secrets

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import LoginRateLimit, RevokedToken, User
from app.main import app
from app.services.auth_security import cleanup_expired_auth_records
from app.services.auth_security import record_login_attempt


def test_login_rate_limit_blocks_repeated_attempts_without_account_detail(api_client):
    payload = {"email": "erin@northstar.example", "password": "wrong password"}
    responses = [api_client.post("/api/auth/login", json=payload) for _ in range(5)]
    blocked = api_client.post("/api/auth/login", json=payload)

    assert all(response.status_code == 401 for response in responses)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.json() == {"detail": "Too many login attempts. Try again later."}


def test_login_rate_limit_expires_and_success_clears_account_counter(
    api_client, database_session
):
    payload = {"email": "erin@northstar.example", "password": "wrong password"}
    for _ in range(4):
        assert api_client.post("/api/auth/login", json=payload).status_code == 401

    assert api_client.post(
        "/api/auth/login",
        json={"email": "erin@northstar.example", "password": "Travel-test-password!45"},
    ).status_code == 200
    assert api_client.post("/api/auth/login", json=payload).status_code == 401

    limiter = database_session.query(LoginRateLimit).filter_by(attempts=1).one()
    limiter.window_started_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    database_session.commit()

    assert api_client.post("/api/auth/login", json=payload).status_code == 401
    refreshed = database_session.query(LoginRateLimit).filter_by(attempts=1).one()
    assert refreshed.attempts == 1
    refreshed_window = refreshed.window_started_at
    if refreshed_window.utcoffset() is None:
        refreshed_window = refreshed_window.replace(tzinfo=timezone.utc)
    assert refreshed_window > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_login_rate_limit_also_caps_attempts_across_many_accounts(database_session):
    for attempt in range(100):
        blocked, _ = record_login_attempt(
            database_session, "192.0.2.10", f"user-{attempt}@example.test"
        )
        assert not blocked

    blocked, retry_after = record_login_attempt(
        database_session, "192.0.2.10", "another@example.test"
    )
    assert blocked
    assert retry_after > 0


def test_expired_revocations_are_cleaned_but_active_revocations_are_retained(
    api_client, database_session
):
    user_id = database_session.query(User).filter_by(email="erin@northstar.example").one().id
    now = datetime.now(timezone.utc)
    database_session.add_all(
        [
            RevokedToken(jti="expired-token-id", user_id=user_id, expires_at=now - timedelta(seconds=1)),
            RevokedToken(jti="active-token-id", user_id=user_id, expires_at=now + timedelta(hours=1)),
            LoginRateLimit(
                key_hash="a" * 64,
                window_started_at=now - timedelta(minutes=16),
                attempts=2,
            ),
            LoginRateLimit(
                key_hash="b" * 64,
                window_started_at=now,
                attempts=2,
            ),
        ]
    )
    database_session.commit()

    removed = cleanup_expired_auth_records(database_session, now=now)

    assert removed == 1
    assert database_session.get(RevokedToken, "expired-token-id") is None
    assert database_session.get(RevokedToken, "active-token-id") is not None
    assert database_session.get(LoginRateLimit, "a" * 64) is None
    assert database_session.get(LoginRateLimit, "b" * 64) is not None


@pytest.mark.parametrize(
    "secret,configured",
    [("", False), ("x" * 64, True), ("short", True), ("0123456789abcdef" * 4, True)],
)
def test_production_startup_rejects_missing_or_weak_jwt_secrets(
    monkeypatch, secret, configured
):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret_key", secret)
    monkeypatch.setattr(settings, "jwt_secret_configured", configured)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        with TestClient(app):
            pass


@pytest.mark.parametrize(
    "secret",
    [
        "0123456789abcdef" * 4,
        "deadbeef" * 8,
        "0" * 64,
        "g" * 64,
        "A" * 64,
    ],
)
def test_production_rejects_predictable_or_wrong_format_jwt_secrets(monkeypatch, secret):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret_key", secret)
    monkeypatch.setattr(settings, "jwt_secret_configured", True)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        settings.validate_startup()


def test_production_accepts_generated_hex_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret_key", secrets.token_hex(32))
    monkeypatch.setattr(settings, "jwt_secret_configured", True)

    settings.validate_startup()


def test_development_keeps_automatic_jwt_secret_configuration(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "jwt_secret_key", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "jwt_secret_configured", False)

    settings.validate_startup()


def test_security_headers_and_auth_response_no_store(api_client):
    health = api_client.get("/api/health")
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"
    assert health.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in health.headers["Permissions-Policy"]
    assert "default-src 'none'" in health.headers["Content-Security-Policy"]

    login = api_client.post(
        "/api/auth/login",
        json={"email": "erin@northstar.example", "password": "Travel-test-password!45"},
    )
    assert login.headers["Cache-Control"] == "no-store"
    assert login.headers["Pragma"] == "no-cache"

    secure_health = api_client.get("https://testserver/api/health")
    assert secure_health.headers["Strict-Transport-Security"].startswith("max-age=")
