"""Set or reset a user's password from a trusted local terminal."""

import getpass
import sys

from sqlalchemy import func, select

from app.core.security import hash_password
from app.db.init import initialize_database
from app.db.models import User
from app.db.session import SessionLocal


def set_password(email: str) -> None:
    password = getpass.getpass("New password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters.")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    initialize_database()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(func.lower(User.email) == email.casefold()))
        if user is None:
            raise SystemExit("No user has that email address.")
        user.password_hash = hash_password(password)
        session.commit()
    print(f"Password set for {email.casefold()}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.db.set_password user@example.com")
    set_password(sys.argv[1].strip())
