from sqlalchemy.engine import Engine
from sqlalchemy import inspect

from app.db.session import Base, engine


def initialize_database(database_engine: Engine = engine) -> None:
    """Import the model registry and create missing tables."""
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=database_engine)
    _migrate_sqlite_columns(database_engine)


def _migrate_sqlite_columns(database_engine: Engine) -> None:
    """Add fields introduced after the initial SQLite schema was created."""
    if database_engine.dialect.name != "sqlite":
        return

    inspector = inspect(database_engine)
    migrations = {
        "agencies": {"is_demo": "BOOLEAN NOT NULL DEFAULT 0"},
        "tickets": {
            "region": "VARCHAR(80)",
            "check_in_at": "DATETIME",
            "departure_at": "DATETIME",
            "resolved_at": "DATETIME",
        },
        "users": {"password_hash": "VARCHAR(512)"},
        "assignments": {
            "routing_score": "INTEGER",
            "routing_workload": "INTEGER",
            "routing_explanation": "TEXT",
        },
    }
    for table_name, columns in migrations.items():
        if not inspector.has_table(table_name):
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                with database_engine.begin() as connection:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                    )
        if table_name == "tickets":
            with database_engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS ix_tickets_region ON tickets (region)"
                )
