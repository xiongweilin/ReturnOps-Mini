from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from returnops.domain.states import Role
from returnops.models import Base, Membership, Organization, User
from returnops.security import hash_token
from returnops.services.tenancy import TenantContext


@dataclass
class SeededOrg:
    organization: Organization
    users: dict[Role, list[User]]
    contexts: dict[Role, list[TenantContext]]
    tokens: dict[Role, list[str]]


def _enable_sqlite_fk(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _enable_sqlite_fk)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def db(session_factory) -> Session:
    with session_factory() as session:
        yield session
        session.rollback()


def seed_organization(db: Session, name: str = "Acme") -> SeededOrg:
    organization = Organization(name=name)
    db.add(organization)
    db.flush()
    users: dict[Role, list[User]] = {role: [] for role in Role}
    contexts: dict[Role, list[TenantContext]] = {role: [] for role in Role}
    tokens: dict[Role, list[str]] = {role: [] for role in Role}
    role_counts = {Role.CUSTOMER_SERVICE: 1, Role.WAREHOUSE: 1, Role.FINANCE: 2, Role.ADMIN: 1}
    for role, count in role_counts.items():
        for index in range(count):
            token = f"token-{name}-{role.value}-{index}"
            user = User(email=f"{role.value}-{index}@{name.lower()}.test", display_name=f"{role.value}-{index}", api_token_hash=hash_token(token))
            db.add(user)
            db.flush()
            db.add(Membership(organization_id=organization.id, user_id=user.id, role=role))
            users[role].append(user)
            contexts[role].append(TenantContext(organization_id=organization.id, user_id=user.id, role=role))
            tokens[role].append(token)
    db.flush()
    return SeededOrg(organization=organization, users=users, contexts=contexts, tokens=tokens)


@pytest.fixture
def seeded(db) -> SeededOrg:
    return seed_organization(db)
