"""Create or update a staff (admin) account from the command line.

The ad-hoc counterpart to the ``DRCPAY_ADMIN_USERNAME``/``_PASSWORD`` bootstrap: use this to add
an operator or reset a password against a deployed database without holding a standing credential
in the environment. Same create-or-update semantics as the bootstrap (idempotent by username), so
re-running it on an existing account resets that account's password rather than duplicating it.

    python -m drc_pay_api.create_staff --username alice
    python -m drc_pay_api.create_staff --username alice --password 's3kr!t...'   # non-interactive

Omit ``--password`` to be prompted, which keeps the secret out of your shell history and out of
the process list. Requires ``DRCPAY_DATABASE_URL`` — this writes to the real database.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Sequence

from .application.staff_accounts import (
    InvalidStaffAccount,
    LastStaffAccount,
    StaffNotFound,
    remove_staff,
    upsert_staff,
)
from .domains.staff.models import ROLE_ADMIN, ROLES_HELP


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m drc_pay_api.create_staff",
        description="Create or update a staff (admin) account in the configured database.",
    )
    parser.add_argument("--username", required=True, help="login handle (3-32 chars)")
    parser.add_argument(
        "--password",
        default=None,
        help="omit to be prompted (keeps the secret out of shell history and the process list)",
    )
    parser.add_argument("--role", default=ROLE_ADMIN, help=ROLES_HELP)
    parser.add_argument(
        "--remove",
        action="store_true",
        help="delete this account and revoke its sessions instead of creating it "
        "(refuses to remove the last remaining staff account)",
    )
    args = parser.parse_args(argv)

    from sqlalchemy.orm import sessionmaker

    from .adapters.sql import SqlStaffCredentialStore, SqlStaffSessionStore, make_engine
    from .config import settings

    if not settings.database_url:
        print(
            "error: DRCPAY_DATABASE_URL is not set. This command writes to the database; "
            "point it at the deployment you mean to change.",
            file=sys.stderr,
        )
        return 2

    session_factory = sessionmaker(make_engine(settings.database_url))
    store = SqlStaffCredentialStore(session_factory)

    if args.remove:
        try:
            revoked = remove_staff(
                store, SqlStaffSessionStore(session_factory), username=args.username
            )
        except StaffNotFound:
            print(f"error: no staff account named {args.username!r}.", file=sys.stderr)
            return 2
        except LastStaffAccount:
            print(
                f"error: {args.username!r} is the only staff account left. Create another one "
                "first, or nobody could sign in to approve merchants.",
                file=sys.stderr,
            )
            return 2
        print(f"staff account removed: {args.username} ({revoked} session(s) revoked)")
        return 0

    password = args.password
    if password is None:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            print("error: passwords did not match.", file=sys.stderr)
            return 2

    existed = store.get_by_username(args.username) is not None
    try:
        credential = upsert_staff(store, username=args.username, password=password, role=args.role)
    except InvalidStaffAccount as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verb = "updated (password reset)" if existed else "created"
    print(f"staff account {verb}: {credential.username} (role {credential.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
