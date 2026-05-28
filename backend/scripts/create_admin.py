"""Create or update an admin user.

Run from the `backend/` directory:

    python -m scripts.create_admin --username alice --password 'secret'

Or via environment variables:

    ADMIN_USERNAME=alice ADMIN_PASSWORD=secret python -m scripts.create_admin

If neither flags nor env vars are supplied, the script prompts interactively.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from getpass import getpass
from typing import Optional

from app.core.security import hash_password
from app.db.session import get_session_factory
from app.models.user import User, UserRole
from sqlalchemy import select


async def upsert_admin(
    username: str,
    password: str,
    email: Optional[str] = None,
) -> str:
    session_factory = get_session_factory()
    async with session_factory() as session:
        username = username.strip().lower()
        result = await session.execute(select(User).where(User.username == username))
        existing = result.scalar_one_or_none()
        if existing is None:
            session.add(
                User(
                    username=username,
                    email=email,
                    password_hash=hash_password(password),
                    role=UserRole.ADMIN.value,
                    is_active=True,
                )
            )
            action = "created"
        else:
            existing.password_hash = hash_password(password)
            existing.role = UserRole.ADMIN.value
            existing.is_active = True
            if email is not None:
                existing.email = email
            action = "updated"
        await session.commit()
    return action


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update an admin user.")
    parser.add_argument("--username", default=os.environ.get("ADMIN_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL"))
    args = parser.parse_args()

    username = args.username or input("Username: ").strip()
    password = args.password or getpass("Password: ")

    if not username or not password:
        print("Username and password are required.", file=sys.stderr)
        return 2

    action = asyncio.run(upsert_admin(username, password, args.email))
    print(f"Admin user '{username}' {action}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
