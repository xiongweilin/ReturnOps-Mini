from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from returnops.models import Base


@pytest.fixture
def pg_factory():
    url = os.environ.get("RETURNOPS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("RETURNOPS_TEST_DATABASE_URL is not set")
    admin = create_engine(url, pool_pre_ping=True)
    schema = f"returnops_it_{uuid.uuid4().hex[:10]}"
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, pool_pre_ping=True, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
