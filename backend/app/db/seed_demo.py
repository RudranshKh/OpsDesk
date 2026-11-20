"""Compatibility command for seeding the full local OpsDesk demo workspace."""

from app.db.seed_demo_data import seed_demo_data


def seed_demo_workspace() -> None:
    seed_demo_data()


if __name__ == "__main__":
    seed_demo_workspace()
