from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from returnops.config import Settings
from returnops.db import get_session
from returnops.domain.states import RefundAttemptStatus, Role
from returnops.models import Membership, RefundAttempt, User
from returnops.main import create_app
from returnops.security import hash_token
from returnops.services.demo_auth import DEMO_SESSION_COOKIE
from returnops.services.payments import mark_dispatching, mark_success, mark_unknown
from returnops.services.refunds import approve_refund
from tests.conftest import seed_organization
from tests.helpers import create_inspected_case, create_pending_refund


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
    whoami = client.get("/v1/me", headers=headers)
    assert whoami.status_code == 200
    assert whoami.json()["role"] == Role.CUSTOMER_SERVICE.value
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


def test_operator_queries_include_counts_search_detail_and_finance_exceptions(
    session_factory,
) -> None:
    with session_factory() as db:
        seeded = seed_organization(db, "OpsApi")
        in_progress = create_pending_refund(db, seeded)
        unknown = create_pending_refund(db, seeded, amount=2000)
        unknown_attempt = db.execute(
            select(RefundAttempt).where(RefundAttempt.return_case_id == unknown.id)
        ).scalar_one()
        mark_dispatching(db, unknown_attempt)
        mark_unknown(db, unknown_attempt, error="provider response timed out")
        create_inspected_case(db, seeded, requested_amount=3000)
        refunded = create_pending_refund(db, seeded, amount=4000)
        refunded_attempt = db.execute(
            select(RefundAttempt).where(RefundAttempt.return_case_id == refunded.id)
        ).scalar_one()
        mark_success(
            db,
            refunded_attempt,
            provider_ref="rf-reconciled-later",
            evidence={"amount_minor": 4000, "currency": "USD", "status": "succeeded"},
            evidence_source="test_fixture",
        )
        db.commit()
        org_id = seeded.organization.id
        service_token = seeded.tokens[Role.CUSTOMER_SERVICE][0]
        finance_token = seeded.tokens[Role.FINANCE][0]
        in_progress_id = in_progress.id
        in_progress_ref = in_progress.case_ref

    client = TestClient(_app(session_factory))
    service_headers = {
        "Authorization": f"Bearer {service_token}",
        "X-Organization-ID": str(org_id),
    }
    finance_headers = {
        "Authorization": f"Bearer {finance_token}",
        "X-Organization-ID": str(org_id),
    }

    listed = client.get("/v1/returns?limit=1", headers=service_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 4
    assert len(listed.json()["items"]) == 1

    searched = client.get(f"/v1/returns?q={in_progress_ref}", headers=service_headers)
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["caseRef"] == in_progress_ref

    detail = client.get(f"/v1/returns/{in_progress_id}", headers=service_headers)
    assert detail.status_code == 200
    assert len(detail.json()["approvals"]) == 2
    assert len(detail.json()["refundAttempts"]) == 1
    assert detail.json()["refundAttempts"][0]["status"] == RefundAttemptStatus.PLANNED.value
    assert detail.json()["auditEvents"]

    summary = client.get("/v1/overview", headers=service_headers)
    assert summary.status_code == 200
    assert summary.json()["total"] == 4
    assert summary.json()["pendingFinance"] == 1
    assert summary.json()["refundProcessing"] == 1
    assert summary.json()["refundExceptions"] == 2
    attention = {item["caseRef"]: item for item in summary.json()["attentionItems"]}
    assert attention[unknown.case_ref]["ownerRole"] == "财务"
    assert attention[unknown.case_ref]["nextAction"] == "查询支付方状态"
    assert attention[refunded.case_ref]["nextAction"] == "完成退款对账"

    exceptions = client.get("/v1/returns/exceptions", headers=finance_headers)
    assert exceptions.status_code == 200
    exception_statuses = {item["status"] for item in exceptions.json()["items"]}
    assert exception_statuses == {"refund_unknown", "refunded"}
    refunded_detail = next(
        item for item in exceptions.json()["items"] if item["status"] == "refunded"
    )
    assert "mark_reconciled" in refunded_detail["allowedActions"]

    denied = client.get("/v1/returns/exceptions", headers=service_headers)
    assert denied.status_code == 403


def test_demo_identity_is_disabled_outside_demo_environment_and_uses_server_cookie(
    session_factory, monkeypatch
) -> None:
    with session_factory() as db:
        seeded = seed_organization(db, "Demo Store")
        db.commit()
        org_id = seeded.organization.id

    monkeypatch.setattr(
        "returnops.services.demo_auth.get_settings",
        lambda: Settings(environment="dev", demo_mode=False),
    )
    client = TestClient(_app(session_factory))
    denied = client.post("/v1/demo/session", json={"role": Role.CUSTOMER_SERVICE.value})
    assert denied.status_code == 403
    client.cookies.set(DEMO_SESSION_COOKIE, "unissued-demo-token")
    unauthenticated = client.get("/v1/returns", headers={"X-Organization-ID": str(org_id)})
    assert unauthenticated.status_code == 401

    monkeypatch.setattr(
        "returnops.services.demo_auth.get_settings",
        lambda: Settings(environment="demo", demo_mode=True),
    )
    client.cookies.clear()
    logged_in = client.post("/v1/demo/session", json={"role": Role.CUSTOMER_SERVICE.value})
    assert logged_in.status_code == 200
    assert "httponly" in logged_in.headers["set-cookie"].lower()
    assert logged_in.json()["organizationId"] == str(org_id)
    assert logged_in.json()["role"] == Role.CUSTOMER_SERVICE.value

    created = client.post(
        "/v1/returns",
        headers={
            "X-Organization-ID": str(org_id),
            "Idempotency-Key": "demo-create-one",
        },
        json={
            "external_order_ref": "DEMO-ORDER-1",
            "customer_ref": "DEMO-CUSTOMER-1",
            "reason": "虚构的演示申请",
            "requested_amount_minor": 12900,
            "currency": "CNY",
        },
    )
    assert created.status_code == 201

    client.delete("/v1/demo/session")
    logged_out = client.get("/v1/returns", headers={"X-Organization-ID": str(org_id)})
    assert logged_out.status_code == 401


def test_automation_identity_can_create_and_read_but_cannot_advance_business_state(
    session_factory,
) -> None:
    with session_factory() as db:
        seeded = seed_organization(db, "AutomationApi")
        automation = User(
            email="automation@automationapi.test",
            display_name="ReturnFlow Automation",
            api_token_hash=hash_token("automation-token"),
        )
        db.add(automation)
        db.flush()
        db.add(
            Membership(
                organization_id=seeded.organization.id,
                user_id=automation.id,
                role=Role.AUTOMATION,
            )
        )
        db.commit()
        org_id = seeded.organization.id

    client = TestClient(_app(session_factory))
    headers = {
        "Authorization": "Bearer automation-token",
        "X-Organization-ID": str(org_id),
        "Idempotency-Key": "automation-intake-001",
    }
    created = client.post(
        "/v1/returns",
        headers=headers,
        json={
            "external_order_ref": "ORDER-AUTO-1",
            "customer_ref": "CUSTOMER-AUTO-1",
            "reason": "演示数据",
            "requested_amount_minor": 5500,
            "currency": "CNY",
        },
    )
    assert created.status_code == 201
    case_id = created.json()["result"]["id"]

    assert client.get("/v1/overview", headers=headers).status_code == 200
    assert client.get("/v1/returns", headers=headers).status_code == 200
    forbidden = client.post(
        f"/v1/returns/{case_id}/authorize",
        headers={**headers, "Idempotency-Key": "automation-cannot-authorize"},
        json={"expected_version": 1, "rationale": "not allowed"},
    )
    assert forbidden.status_code == 403
    assert client.get(f"/v1/returns/{case_id}", headers=headers).json()["status"] == "requested"
    assert client.get("/v1/returns/exceptions", headers=headers).status_code == 403


def test_high_value_second_approval_is_visible_only_to_a_distinct_finance_user(
    session_factory,
) -> None:
    with session_factory() as db:
        seeded = seed_organization(db, "FourEyesApi")
        case = create_inspected_case(db, seeded, requested_amount=70_000)
        first_context = seeded.contexts[Role.FINANCE][0]
        case, second_required = approve_refund(
            db,
            context=first_context,
            case_id=case.id,
            expected_version=case.version,
            approved_amount_minor=60_000,
            rationale="first approval",
        )
        assert second_required is True
        db.commit()
        org_id = seeded.organization.id
        case_id = case.id
        version = case.version
        finance_a_token = seeded.tokens[Role.FINANCE][0]
        finance_b_token = seeded.tokens[Role.FINANCE][1]

    client = TestClient(_app(session_factory))
    finance_a_headers = {
        "Authorization": f"Bearer {finance_a_token}",
        "X-Organization-ID": str(org_id),
    }
    finance_b_headers = {
        "Authorization": f"Bearer {finance_b_token}",
        "X-Organization-ID": str(org_id),
    }
    detail_a = client.get(f"/v1/returns/{case_id}", headers=finance_a_headers)
    detail_b = client.get(f"/v1/returns/{case_id}", headers=finance_b_headers)
    assert "approve_refund" not in detail_a.json()["allowedActions"]
    assert "approve_refund" in detail_b.json()["allowedActions"]

    second_approval = client.post(
        f"/v1/returns/{case_id}/approve-refund",
        headers={**finance_b_headers, "Idempotency-Key": "second-distinct-approver"},
        json={
            "expected_version": version,
            "approved_amount_minor": 60_000,
            "rationale": "second independent approval",
        },
    )
    assert second_approval.status_code == 200
    assert second_approval.json()["result"]["secondApprovalRequired"] is False
