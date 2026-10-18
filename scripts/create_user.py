"""Create a privileged or test account from the command line (bootstrap the first admin).

Usage:
    python scripts/create_user.py --role admin --email admin@pramaan.test --name "Site Admin"
    python scripts/create_user.py --role auditor --email audit@pramaan.test --name "Auditor"

The password is prompted for (hidden). For non-interactive use set PRAMAAN_NEW_PASSWORD.
Doctors are NOT created here: an admin creates them in the app so that the doctor sets their own
passwords through the activation flow. Pharmacists created here are pre-approved.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core import audit  # noqa: E402
from app.core.security import PasswordPolicyError, hash_password, validate_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import ApprovalStatus, Role, User  # noqa: E402
from app.schemas import RegisterIn  # noqa: E402
from app.services.account_service import _new_patient_code  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role", required=True, choices=["admin", "auditor", "patient", "pharmacist"]
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--license-no", default="DEMO-0001", help="pharmacists only")
    parser.add_argument("--org-name", default="Demo Pharmacy", help="pharmacists only")
    args = parser.parse_args()

    password = os.environ.get("PRAMAAN_NEW_PASSWORD") or getpass.getpass("Password: ")
    try:
        validate_password(password)
    except PasswordPolicyError as exc:
        print(f"Rejected: {exc}")
        return 1

    # Reuse the API's input validation so scripts cannot create accounts the API would refuse.
    checked = RegisterIn(
        email=args.email,
        name=args.name,
        password=password,
        role="pharmacist" if args.role == "pharmacist" else "patient",
        license_no=args.license_no if args.role == "pharmacist" else None,
        org_name=args.org_name if args.role == "pharmacist" else None,
    )

    init_db()
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == checked.email)) is not None:
            print("An account with that email already exists.")
            return 1
        role = Role(args.role)
        user = User(
            email=checked.email,
            name=checked.name,
            role=role,
            password_hash=hash_password(password),
            license_no=checked.license_no,
            org_name=checked.org_name,
            patient_code=_new_patient_code(db) if role == Role.patient else None,
            approval_status=ApprovalStatus.APPROVED,
        )
        db.add(user)
        db.flush()
        audit.append(
            db, None, "cli", "USER_REGISTER", user.public_id, {"role": role.value, "via": "cli"}
        )
        db.commit()
        print(f"Created {role.value} account for {user.email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
