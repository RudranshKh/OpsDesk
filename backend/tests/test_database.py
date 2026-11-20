import asyncio

from sqlalchemy import inspect

from app.main import app
from app.db.session import engine


def test_backend_startup_initializes_database():
    async def run_startup():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(run_startup())
    assert "tickets" in inspect(engine).get_table_names()


def test_initialization_creates_all_tables(database_engine):
    table_names = set(inspect(database_engine).get_table_names())

    assert table_names == {
        "agencies",
        "agent_profiles",
        "login_rate_limits",
        "revoked_tokens",
        "users",
        "tickets",
        "assignments",
        "ticket_links",
        "conversations",
        "activity_logs",
        "ticket_slas",
        "sla_escalations",
    }
