import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.security import hash_password
from app.db.init import initialize_database
from app.db.session import create_database_engine
from app.main import app
from app.db.models import AgentProfile, Agency, User

TEST_PASSWORD = "Travel-test-password!45"


@pytest.fixture
def database_engine(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'test_opsdesk.db'}")
    initialize_database(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def database_session(database_engine):
    with Session(database_engine) as session:
        yield session


@pytest.fixture
def api_client(database_engine):
    with Session(database_engine) as session:
        agency = Agency(name="Northstar Travel", slug="northstar")
        other_agency = Agency(name="Southwind Travel", slug="southwind")
        session.add_all([agency, other_agency])
        session.flush()
        agent = User(
            agency_id=agency.id,
            full_name="Alex Morgan",
            email="alex@northstar.example",
            role="agent",
        )
        agent.agent_profile = AgentProfile(regions=["North America"], is_available=True)
        manager = User(
            agency_id=agency.id,
            full_name="Erin Manager",
            email="erin@northstar.example",
            role="escalation_manager",
        )
        manager.agent_profile = AgentProfile(regions=["North America", "Europe"], is_available=True)
        admin = User(
            agency_id=agency.id,
            full_name="Nora Admin",
            email="nora@northstar.example",
            role="admin",
        )
        other_admin = User(
            agency_id=other_agency.id,
            full_name="Owen Admin",
            email="owen@southwind.example",
            role="admin",
        )
        for user in (agent, manager, admin, other_admin):
            user.password_hash = hash_password(TEST_PASSWORD)
        session.add_all([agent, manager, admin, other_admin])
        session.commit()

    def override_get_db():
        with Session(database_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/login",
                json={"email": "erin@northstar.example", "password": TEST_PASSWORD},
            )
            assert response.status_code == 200
            client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def login_as(api_client):
    def login(email: str):
        response = api_client.post(
            "/api/auth/login", json={"email": email, "password": TEST_PASSWORD}
        )
        if response.status_code == 200:
            api_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        else:
            api_client.headers.pop("Authorization", None)
        return response

    return login
