from __future__ import annotations

from fastapi.testclient import TestClient

from returnops.db import get_session
from returnops.domain.states import Role
from returnops.main import create_app
from tests.conftest import seed_organization


def _app(session_factory):
    app = create_app()

    def override_session():
        with session_factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_session] = override_session
    return app


def test_api_auth_tenant_isolation_and_idempotent_create(session_factory) -> None:
    with session_factory() as db:
        acme = seed_organization(db, "AcmeApi")
        beta = seed_organization(db, "BetaApi")
        db.commit()
        acme_org = acme.organization.id
        beta_org = beta.organization.id
        acme_token = acme.tokens[Role.CUSTOMER_SERVICE][0]
        beta_token = beta.tokens[Role.ADMIN][0]
    client = TestClient(_app(session_factory))
    headers = {
        "Authorization": f"Bearer {acme_token}",
        "X-Organization-ID": str(acme_org),
        "Idempotency-Key": "create-one",
    }
    body = {
        "external_order_ref": "ORDER-API",
        "customer_ref": "CUSTOMER-API",
        "reason": "broken",
        "requested_amount_minor": 1200,
        "currency": "USD",
    }
    first = client.post("/v1/returns", headers=headers, json=body)
    second = client.post("/v1/returns", headers=headers, json=body)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["replayed"] is False
    assert second.json()["replayed"] is True
    assert first.json()["result"]["id"] == second.json()["result"]["id"]
    case_id = first.json()["result"]["id"]
    outsider = client.get(
        f"/v1/returns/{case_id}",
        headers={"Authorization": f"Bearer {beta_token}", "X-Organization-ID": str(beta_org)},
    )
    assert outsider.status_code == 404


def test_api_rejects_same_idempotency_key_for_different_body(session_factory) -> None:
    with session_factory() as db:
        seeded = seed_organization(db, "IdemApi")
        db.commit()
        org = seeded.organization.id
        token = seeded.tokens[Role.CUSTOMER_SERVICE][0]
    client = TestClient(_app(session_factory))
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": str(org),
        "Idempotency-Key": "conflict-key",
    }
    base = {
        "external_order_ref": "ORDER",
        "customer_ref": "C",
        "reason": "broken",
        "requested_amount_minor": 100,
        "currency": "USD",
    }
    assert client.post("/v1/returns", headers=headers, json=base).status_code == 201
    response = client.post(
        "/v1/returns", headers=headers, json={**base, "requested_amount_minor": 101}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"


def test_root_console_is_served(session_factory) -> None:
    client = TestClient(_app(session_factory))
    response = client.get("/")
    assert response.status_code == 200
    assert "ReturnOps Mini" in response.text
    assert "工程判断" in response.text
