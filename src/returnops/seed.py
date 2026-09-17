from __future__ import annotations

from sqlalchemy import select

from returnops.db import SessionLocal
from returnops.domain.states import Role
from returnops.models import Membership, Organization, User
from returnops.security import hash_token, issue_token


DEMO_USERS = (
    ("service@example.test", "Customer Service", Role.CUSTOMER_SERVICE),
    ("warehouse@example.test", "Warehouse", Role.WAREHOUSE),
    ("finance-a@example.test", "Finance A", Role.FINANCE),
    ("finance-b@example.test", "Finance B", Role.FINANCE),
    ("admin@example.test", "Administrator", Role.ADMIN),
)


def main() -> None:
    with SessionLocal() as db:
        existing = db.execute(select(Organization).where(Organization.name == "Demo Store")).scalar_one_or_none()
        if existing is not None:
            print(f"Demo Store already exists: organization_id={existing.id}")
            return

        organization = Organization(name="Demo Store")
        db.add(organization)
        db.flush()
        print(f"organization_id={organization.id}")
        for email, display_name, role in DEMO_USERS:
            token = issue_token()
            user = User(
                email=email,
                display_name=display_name,
                api_token_hash=hash_token(token),
            )
            db.add(user)
            db.flush()
            db.add(Membership(organization_id=organization.id, user_id=user.id, role=role))
            print(f"{role.value:16} {email:28} token={token}")
        db.commit()


if __name__ == "__main__":
    main()
