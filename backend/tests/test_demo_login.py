import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.init import initialize_database
from app.db.models import Agency, Ticket, User
from app.db.session import create_database_engine
from app.main import app
from app.services.demo_workspace import DEMO_AGENCY_SLUG, DEMO_USER_EMAIL


@pytest.fixture
def demo_client(database_engine, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "demo_login_enabled", True)
    monkeypatch.setattr(main_module, "initialize_database", lambda: initialize_database(database_engine))
    monkeypatch.setattr(main_module, "_cleanup_auth_records", lambda: None)
    monkeypatch.setattr(main_module, "_run_sla_sweep", lambda: None)

    def override_get_db():
        with Session(database_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _create_non_demo_records(database_engine) -> tuple[int, int]:
    with Session(database_engine) as db:
        agency = Agency(name="Private Test Agency", slug="private-test-agency")
        db.add(agency)
        db.flush()
        user = User(
            agency_id=agency.id,
            full_name="Private Test User",
            email="private-user@example.test",
            role="agent",
        )
        db.add(user)
        db.flush()
        ticket = Ticket(
            reference="PRIVATE-TEST-001",
            agency_id=agency.id,
            created_by_id=user.id,
            subject="Private agency test ticket",
            status="open",
            priority="normal",
        )
        db.add(ticket)
        db.commit()
        return agency.id, ticket.id


def test_existing_sqlite_agency_table_gets_demo_marker_migration(tmp_path):
    legacy_engine = create_database_engine(f"sqlite:///{tmp_path / 'legacy_opsdesk.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE agencies (id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, "
            "slug VARCHAR(80) NOT NULL UNIQUE, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        ))

    initialize_database(legacy_engine)
    assert "is_demo" in {column["name"] for column in inspect(legacy_engine).get_columns("agencies")}
    legacy_engine.dispose()


def test_demo_login_provisions_restricted_isolated_workspace_and_workflows(
    demo_client, database_engine
):
    private_agency_id, private_ticket_id = _create_non_demo_records(database_engine)

    response = demo_client.post("/api/auth/demo")
    assert response.status_code == 200
    login_user = response.json()["user"]
    assert login_user["role"] == "escalation_manager"
    assert login_user["is_demo"] is True
    assert login_user["agency_id"] != private_agency_id
    assert login_user["email"] == DEMO_USER_EMAIL
    assert login_user["role"] != "admin"
    demo_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"

    ticket_response = demo_client.get("/api/tickets")
    assert ticket_response.status_code == 200
    tickets = ticket_response.json()
    assert len(tickets) == 6
    assert all(ticket["agency_id"] == login_user["agency_id"] for ticket in tickets)
    assert {ticket["status"] for ticket in tickets} >= {"open", "pending", "resolved"}

    first = next(ticket for ticket in tickets if ticket["reference"] == "PUBDEMO-001")
    second = next(ticket for ticket in tickets if ticket["reference"] == "PUBDEMO-002")
    assert demo_client.get(f"/api/tickets/{private_ticket_id}").status_code == 404
    assert demo_client.get(
        f"/api/insights?agency_id={private_agency_id}"
    ).status_code == 403
    assert demo_client.post(
        f"/api/tickets/{first['id']}/links", json={"linked_ticket_id": private_ticket_id}
    ).status_code == 404

    related = demo_client.get(f"/api/tickets/{first['id']}/related").json()
    assert any(match["id"] == second["id"] and match["match_type"] == "booking_reference" for match in related)
    assert demo_client.post(
        f"/api/tickets/{first['id']}/links", json={"linked_ticket_id": second["id"]}
    ).status_code == 201
    linked = demo_client.get(f"/api/tickets/{first['id']}/related").json()
    assert any(match["id"] == second["id"] and match["is_linked"] for match in linked)

    routing = demo_client.post(f"/api/tickets/{first['id']}/assign")
    assert routing.status_code == 200
    assert routing.json()["candidate_scores"]
    assert all(candidate["agent_role"] != "admin" for candidate in routing.json()["candidate_scores"])

    insights = demo_client.get("/api/insights")
    assert insights.status_code == 200
    assert insights.json()["agency_id"] == login_user["agency_id"]
    assert insights.json()["total_tickets"] == 6
    assert insights.json()["resolved_tickets"] == 3

    created = demo_client.post(
        "/api/tickets",
        json={"subject": "Demo workflow ticket", "priority": "normal"},
    )
    assert created.status_code == 201
    assert created.json()["agency_id"] == login_user["agency_id"]


def test_demo_user_cannot_use_user_management_or_admin_ticket_operations(demo_client):
    response = demo_client.post("/api/auth/demo")
    assert response.status_code == 200
    demo_user_id = response.json()["user"]["id"]
    demo_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    ticket_id = demo_client.get("/api/tickets").json()[0]["id"]

    assert demo_client.get("/api/users").status_code == 403
    assert demo_client.get(f"/api/users/{demo_user_id}/routing-profile").status_code == 403
    assert demo_client.put(
        f"/api/users/{demo_user_id}/routing-profile",
        json={"regions": ["Global"], "is_available": True},
    ).status_code == 403
    assert demo_client.delete(f"/api/tickets/{ticket_id}").status_code == 403


def test_demo_endpoint_obeys_toggle_and_requires_auth_for_application_data(
    demo_client, database_engine, monkeypatch
):
    assert demo_client.get("/api/tickets").status_code == 401

    monkeypatch.setattr(settings, "demo_login_enabled", False)
    assert demo_client.post("/api/auth/demo").status_code == 404
    with Session(database_engine) as db:
        assert db.scalar(select(Agency.id).where(Agency.slug == DEMO_AGENCY_SLUG)) is None


def test_demo_workspace_can_be_provisioned_in_production_with_valid_jwt_config(
    demo_client, monkeypatch
):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "jwt_secret_key", secrets.token_hex(32))
    monkeypatch.setattr(settings, "jwt_secret_configured", True)
    settings.validate_startup()

    response = demo_client.post("/api/auth/demo")
    assert response.status_code == 200
    assert response.json()["user"]["is_demo"] is True


def test_existing_non_demo_agency_at_reserved_slug_is_never_adopted(
    demo_client, database_engine
):
    with Session(database_engine) as db:
        db.add(Agency(name="Existing Workspace", slug=DEMO_AGENCY_SLUG, is_demo=False))
        db.commit()
    response = demo_client.post("/api/auth/demo")
    assert response.status_code == 503
    with Session(database_engine) as db:
        agency = db.scalar(select(Agency).where(Agency.slug == DEMO_AGENCY_SLUG))
        assert agency.is_demo is False
        assert db.scalar(select(User.id).where(User.email == DEMO_USER_EMAIL)) is None


def test_demo_login_has_no_password_credential_path(demo_client):
    demo_response = demo_client.post("/api/auth/demo")
    assert demo_response.status_code == 200
    demo_user = demo_response.json()["user"]
    login_response = demo_client.post(
        "/api/auth/login",
        json={"email": demo_user["email"], "password": "any-password-value"},
    )
    assert login_response.status_code == 401
