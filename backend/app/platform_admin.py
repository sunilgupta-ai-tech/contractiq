"""
Create or reset a platform admin from the command line (Phase 18).

The console has no public sign-up: the first super admin is created here, by
someone with shell access to the deployment, and adds the others in the
console.

    python -m app.platform_admin create --email ops@docunexa.ai --name "Ops" [--role SUPPORT]
    python -m app.platform_admin reset-password --email ops@docunexa.ai

The password is read from PLATFORM_ADMIN_PASSWORD, or asked for (never a
command-line argument, which would end up in shell history and `ps`).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.database import Database
from app.db.models import PlatformAdmin, PlatformAuditLog, PlatformRole
from app.schemas.auth import PASSWORD_MAX_BYTES, PASSWORD_MIN_CHARS


def _password() -> str:
    password = os.environ.get("PLATFORM_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < PASSWORD_MIN_CHARS or len(password.encode()) > PASSWORD_MAX_BYTES:
        sys.exit(f"The password must be {PASSWORD_MIN_CHARS}-{PASSWORD_MAX_BYTES} characters.")
    return password


async def _run(args: argparse.Namespace) -> None:
    db = Database(get_settings())
    email = args.email.strip().lower()
    try:
        async with db.session_factory() as session:
            existing = (
                await session.execute(
                    select(PlatformAdmin).where(func.lower(PlatformAdmin.email) == email)
                )
            ).scalar_one_or_none()
            if args.command == "create":
                if existing is not None:
                    sys.exit(f"{email} is already a platform admin.")
                admin = PlatformAdmin(
                    email=email,
                    full_name=args.name,
                    password_hash=hash_password(_password()),
                    role=PlatformRole(args.role),
                )
                session.add(admin)
                await session.flush()
                action = "platform_admin.create_cli"
            else:
                if existing is None:
                    sys.exit(f"{email} is not a platform admin.")
                admin = existing
                admin.password_hash = hash_password(_password())
                admin.is_active = True
                action = "platform_admin.reset_password_cli"
            session.add(
                PlatformAuditLog(
                    actor_id=None,
                    action=action,
                    target_type="platform_admin",
                    target_id=admin.id,
                    details={"role": admin.role.value},
                )
            )
            await session.commit()
            print(f"{action.split('.')[1]}: {email} ({admin.role.value})")
    finally:
        await db.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.platform_admin")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Add a platform admin")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument(
        "--role", choices=[r.value for r in PlatformRole], default=PlatformRole.SUPER_ADMIN.value
    )
    reset = commands.add_parser("reset-password", help="Set a new password and re-enable")
    reset.add_argument("--email", required=True)
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
