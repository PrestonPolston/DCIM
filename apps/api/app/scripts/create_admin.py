"""Bootstrap the first admin: python -m app.scripts.create_admin --email you@example.com

Prompts for the password (or reads it from stdin with --password-stdin). No default credentials exist.
"""
import argparse
import getpass
import sys

from sqlmodel import Session, select

import app.models  # noqa: F401
from app.db import engine
from app.modules.audit.service import record_audit
from app.modules.auth.models import UserRow
from app.modules.auth.passwords import hash_password, password_problems
from app.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)
    email = args.email.strip().lower()
    password = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Password: ")
    problems = password_problems(password, email, get_settings().password_min_length)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    with Session(engine) as session:
        if session.exec(select(UserRow).where(UserRow.email == email)).first():
            print(f"User {email} already exists", file=sys.stderr)
            return 1
        user = UserRow(email=email, display_name=args.display_name, role="admin",
                       password_hash=hash_password(password))
        session.add(user)
        session.flush()
        record_audit(session, None, "user.create", "user", user.id, after={"email": email, "role": "admin", "via": "create_admin"})
        session.commit()
    print(f"Created admin {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
