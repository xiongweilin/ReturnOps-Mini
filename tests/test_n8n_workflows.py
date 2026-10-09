from __future__ import annotations

import json
from pathlib import Path


WORKFLOWS = Path(__file__).resolve().parents[1] / "n8n" / "workflows"


def _workflow(name: str) -> dict:
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_intake_export_uses_authenticated_webhook_idempotent_api_and_explicit_responses() -> None:
    workflow = _workflow("01-return-intake.json")
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["name"] == "01-return-intake"
    assert workflow["active"] is False
    assert nodes["Return Intake Webhook"]["parameters"]["authentication"] == "basicAuth"
    assert nodes["Return Intake Webhook"]["parameters"]["responseMode"] == "responseNode"
    assert nodes["Validate Intake Fields"]["type"] == "n8n-nodes-base.if"
    assert nodes["Map ReturnCreate Payload"]["type"] == "n8n-nodes-base.set"

    api_request = nodes["Create Return in ReturnOps"]
    assert api_request["parameters"]["url"] == "http://api:8000/v1/returns"
    assert api_request["parameters"]["genericAuthType"] == "httpCustomAuth"
    assert (
        api_request["parameters"]["headerParameters"]["parameters"][0]["name"] == "Idempotency-Key"
    )
    assert api_request["parameters"]["options"]["response"]["response"]["neverError"] is True
    assert (
        "body?.result?.id"
        in nodes["Return Created or Replayed"]["parameters"]["conditions"]["conditions"][0][
            "leftValue"
        ]
    )
    assert nodes["Respond with Created Return"]["parameters"]["options"]["responseCode"] == 201
    assert nodes["Respond with Invalid Intake"]["parameters"]["options"]["responseCode"] == 400
    assert "upstreamStatus" in nodes["Respond with ReturnOps Error"]["parameters"]["responseBody"]
    assert "responseCode" in nodes["Respond with ReturnOps Error"]["parameters"]["options"]


def test_digest_export_reads_live_summary_and_has_schedule_and_manual_entry() -> None:
    workflow = _workflow("02-operations-digest.json")
    nodes = {node["name"]: node for node in workflow["nodes"]}

    assert workflow["name"] == "02-operations-digest"
    assert workflow["active"] is False
    assert nodes["Run Digest Manually"]["type"] == "n8n-nodes-base.manualTrigger"
    assert nodes["Every Day at 09:00"]["type"] == "n8n-nodes-base.scheduleTrigger"
    assert (
        nodes["Read Current Operations Summary"]["parameters"]["url"]
        == "http://api:8000/v1/overview"
    )
    assert nodes["Send Summary to Mailpit"]["type"] == "n8n-nodes-base.emailSend"
    digest_format = nodes["Format Daily Digest"]["parameters"]["jsonOutput"]
    assert "$json.attentionItems" in digest_format
    assert "item.ownerRole" in digest_format
    assert "item.nextAction" in digest_format


def test_exports_do_not_embed_credentials_or_direct_database_payment_nodes() -> None:
    exports = [path.read_text(encoding="utf-8") for path in WORKFLOWS.glob("*.json")]
    assert len(exports) == 2
    for content in exports:
        workflow = json.loads(content)
        serialized = json.dumps(workflow, ensure_ascii=False).lower()
        assert "bearer " not in serialized
        assert "postgres" not in serialized
        assert "payment:8090" not in serialized
        assert not any("credentials" in node for node in workflow["nodes"])
