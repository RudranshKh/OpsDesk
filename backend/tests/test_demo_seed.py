import importlib

import pytest
from sqlalchemy import func, or_, select
from sqlalchemy.orm import sessionmaker

from app.core.security import verify_password
from app.db.models import (
    ActivityLog,
    Agency,
    Assignment,
    Conversation,
    SLAEscalation,
    Ticket,
    TicketLink,
    TicketSLA,
    User,
)
from app.db.seed_demo_data import _get_demo_password, seed_demo_data

SEED_TEST_PASSWORD = "local-demo-test-password-45"


def test_demo_seed_is_repeatable_hashed_and_preserves_existing_data(database_engine, monkeypatch):
    monkeypatch.setenv("OPSDESK_DEMO_PASSWORD", SEED_TEST_PASSWORD)
    factory = sessionmaker(bind=database_engine, autoflush=False, autocommit=False)
    seed_demo_data(factory, database_engine)

    with factory() as session:
        assert session.scalar(select(func.count(Agency.id))) == 3
        assert session.scalar(select(func.count(User.id))) == 12
        assert session.scalar(select(func.count(Ticket.id))) == 25
        assert session.scalar(select(func.count(TicketLink.id))) == 4
        assert session.scalar(select(func.count(Conversation.id))) >= 17
        assert session.scalar(select(func.count(Assignment.id))) >= 25
        assert session.scalar(select(func.count(TicketSLA.ticket_id))) == 25
        assert session.scalar(select(func.count(Ticket.id)).where(or_(Ticket.check_in_at.is_not(None), Ticket.departure_at.is_not(None)))) >= 4
        assert session.scalar(select(func.count(ActivityLog.id))) >= 25
        assert session.scalar(select(func.count(SLAEscalation.id))) >= 3

        users = session.scalars(select(User)).all()
        assert all(user.password_hash and user.password_hash.startswith("$argon2id$") for user in users)
        assert verify_password(SEED_TEST_PASSWORD, session.scalar(select(User).where(User.email == "agent@opsdesk.local")).password_hash)

        statuses = {row[0] for row in session.execute(select(TicketSLA.sla_status)).all()}
        assert {"on_track", "approaching", "travel_urgent", "breached"}.issubset(statuses)

        # Existing user-entered values remain unchanged on the next seed run.
        agent = session.scalar(select(User).where(User.email == "agent@opsdesk.local"))
        agent.full_name = "Local Demo Agent Name"
        ticket = session.scalar(select(Ticket).where(Ticket.reference == "DEMO-OPS-004"))
        ticket.subject = "Locally edited demo ticket"
        session.commit()

    seed_demo_data(factory, database_engine)
    with factory() as session:
        assert session.scalar(select(func.count(Agency.id))) == 3
        assert session.scalar(select(func.count(User.id))) == 12
        assert session.scalar(select(func.count(Ticket.id))) == 25
        assert session.scalar(select(func.count(TicketLink.id))) == 4
        assert session.scalar(select(func.count(Conversation.id))) >= 17
        assert session.scalar(select(User.full_name).where(User.email == "agent@opsdesk.local")) == "Local Demo Agent Name"
        assert session.scalar(select(Ticket.subject).where(Ticket.reference == "DEMO-OPS-004")) == "Locally edited demo ticket"


def test_demo_password_comes_from_hidden_interactive_prompt(monkeypatch):
    monkeypatch.delenv("OPSDESK_DEMO_PASSWORD", raising=False)
    answers = iter((SEED_TEST_PASSWORD, SEED_TEST_PASSWORD))
    prompts = []
    monkeypatch.setattr(
        "app.db.seed_demo_data.getpass.getpass",
        lambda prompt: prompts.append(prompt) or next(answers),
    )

    assert _get_demo_password() == SEED_TEST_PASSWORD
    assert len(prompts) == 2


def test_demo_password_rejects_mismatch_and_short_values(monkeypatch):
    monkeypatch.delenv("OPSDESK_DEMO_PASSWORD", raising=False)
    answers = iter((SEED_TEST_PASSWORD, "a-different-password-value"))
    monkeypatch.setattr("app.db.seed_demo_data.getpass.getpass", lambda _prompt: next(answers))
    with pytest.raises(ValueError, match="do not match"):
        _get_demo_password()

    monkeypatch.setenv("OPSDESK_DEMO_PASSWORD", "short")
    with pytest.raises(ValueError, match="at least 12 characters"):
        _get_demo_password()


@pytest.mark.parametrize("app_env", ["production", "prod"])
def test_demo_seed_is_disabled_in_production_before_database_initialization(
    database_engine, monkeypatch, app_env
):
    seed_module = importlib.import_module("app.db.seed_demo_data")
    monkeypatch.setattr(seed_module.settings, "app_env", app_env)
    monkeypatch.setenv("OPSDESK_DEMO_PASSWORD", SEED_TEST_PASSWORD)

    def unexpected_database_initialization(*_args, **_kwargs):
        pytest.fail("Production guard must run before database initialization.")

    monkeypatch.setattr(seed_module, "initialize_database", unexpected_database_initialization)
    factory = sessionmaker(bind=database_engine)
    with pytest.raises(RuntimeError, match="disabled"):
        seed_demo_data(factory, database_engine)
