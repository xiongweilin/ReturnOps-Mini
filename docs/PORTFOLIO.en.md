# Portfolio case: ReturnFlow

## Business context

Live demo: [play the 4–5 minute Chinese video](assets/returnflow-demo.mp4) · [Chinese subtitles](assets/returnflow-demo.zh-CN.srt) · [recording walkthrough](RECORDING.en.md). For the interview outline, see [interview pitch](INTERVIEW-PITCH.en.md).

Simulate a small or medium-sized e-commerce merchant. Returns and refunds require support eligibility confirmation, warehouse receipt and inspection, and finance approval and reconciliation; the actual payment state may also be uncertain when a timeout occurs or a webhook is delayed.

## Original problem

Cross-team information is easily scattered across spreadsheets, chat logs, and the payment back office; duplicate entry creates duplicate cases; a refund-response timeout treated as a failure and retried directly may cause a duplicate refund; finance struggles to determine the provider's true outcome from local state.

## Solution

Use n8n to receive external return events and call the ReturnOps API to create cases; the API stores the single business state, tenant permissions, approvals, audit, and Outbox refund intents; a React workspace shows support, warehouse, and finance their real to-dos and allowed actions. `REFUND_UNKNOWN` does not retry automatically; finance first recovers the facts through an authoritative Fake Payment query, then reconciles and closes.

## Actual implementation

- **Business state and permissions:** [`states.py`](../src/returnops/domain/states.py), [`routes.py`](../src/returnops/api/routes.py), and [`returns.py`](../src/returnops/services/returns.py) implement state gates, tenant isolation, service identities, and business operations; [`operator_queries.py`](../src/returnops/services/operator_queries.py) provides the real operations overview, role to-dos, and exception list.
- **Refund reliability:** [`outbox.py`](../src/returnops/services/outbox.py), [`worker.py`](../src/returnops/services/worker.py), [`payments.py`](../src/returnops/services/payments.py), [`webhooks.py`](../src/returnops/services/webhooks.py), and [`reconciliation.py`](../src/returnops/services/reconciliation.py) preserve stable refund intents, single dispatch, webhook deduplication, external-evidence verification, and UNKNOWN recovery.
- **Operations console:** [`frontend/src/App.tsx`](../frontend/src/App.tsx) and [`api.ts`](../frontend/src/api.ts) implement the Chinese overview, list/search/filter, detail, role-allowed actions, minor-unit amount submission, and exception/reconciliation center.
- **Peripheral automation:** [`01-return-intake.json`](../n8n/workflows/01-return-intake.json) receives requests and passes a stable idempotency key; [`02-operations-digest.json`](../n8n/workflows/02-operations-digest.json) summarizes the API's real to-dos and responsible roles and sends an informational digest to Mailpit.
- **Deployment and reproduction:** [`docker-compose.yml`](../docker-compose.yml) orchestrates PostgreSQL, API, worker, frontend, Fake Payment, n8n, and Mailpit; [`scripts/`](../scripts/) provides start, seed, verify, stop, reset, and UNKNOWN demo commands.

## Verifiable results

- The full local Compose stack runs; the full Python test suite is **49 passed**, including PostgreSQL integration tests; Ruff, the frontend production build, lint, and E2E type checking pass.
- Playwright completes the normal refund loop, different-approver high-value verification, UNKNOWN authoritative-query recovery, and browser/API acceptance that support cannot approve, through the local console.
- Both n8n **2.42.5** workflows are automatically upserted, bound to local credentials, and published by `start-demo.ps1`; a fresh volume no longer requires manual owner/import/bind/publish. The Production Intake webhook integration check measured: no Basic Auth returns 401, invalid request returns 400, a valid request creates a `requested` case, replaying the same event returns the same case, and changing content under the same idempotency key returns 409.
- The updated Digest manual execution succeeded; then the daily 09:00 Schedule Trigger actually fired at 2026-10-10 09:00:53 (Asia/Shanghai), and n8n execution record ID `20` shows Succeeded (110 ms). The latest Mailpit email contains the API-summarized pending cases, responsible roles, and next actions.
- After restarting the entire long-running Compose stack without deleting volumes, API cases, Fake Payment's authoritative refund records (`post_count=1`), n8n publication state, and Mailpit email were all preserved; the post-restart Intake integration check and manual Digest send still succeeded.
- UI and workflow screenshots: [overview](assets/returnflow-overview.png), [normal loop](assets/returnflow-closed-case.png), [high-value second approver](assets/returnflow-second-approver.png), [UNKNOWN paused](assets/returnflow-unknown-before-reconcile.png), [recovery evidence](assets/returnflow-unknown-recovered.png), [n8n Intake](assets/n8n-01-return-intake.png), [n8n Digest](assets/n8n-02-operations-digest.png), [n8n scheduled execution succeeded](assets/n8n-02-scheduled-execution.png), [Mailpit inbox](assets/mailpit-summary-inbox.png).

For per-item test commands, persistent demo data, and evidence boundaries, see [`TEST-EVIDENCE.en.md`](TEST-EVIDENCE.en.md).

## Unverified effects and limitations

- There is no real enterprise customer trial data, so no claim can be made about saved hours, lower finance error rates, higher adoption, or validated long-term maintenance cost.
- No real payment, SMTP, ERP, or customer personal information is connected; Fake Payment and Mailpit are local demos only.
- The daily email uses ordinary SMTP/Mailpit and does not promise exactly-once delivery. The scheduled trigger has been observed once; a single observation does not prove long-term scheduling reliability.
- Demo Mode is only for an isolated local demo, not production-grade authentication. Playwright and n8n integration checks leave synthetic cases in the persistent demo database.

## Design tradeoffs

1. **n8n does not own business authorization.** It performs mapping, idempotent requests, read-only summaries, and notifications; state transitions, role permissions, refund calls, and audit are executed only by the ReturnOps API.
2. **Keep the Outbox and `REFUND_UNKNOWN`.** After an external call occurs, a client timeout does not prove that the payment failed. The system pauses first, and finance verifies with the provider's authoritative record instead of replaying an uncertain refund.
3. **A high-value refund still requires different finance users to approve the same amount.** The threshold comes from a configurable rule and is only this demo merchant's policy, not a universal enterprise standard.
4. **Do not introduce an AIOS-wide runtime or a separate workflow engine.** The existing ReturnOps already owns the reliable business core; new components serve only real frontend and peripheral automation needs.

## Demo narrative sequence

First show the overview and real to-dos, then complete a normal case through support/warehouse/finance; next show the high-value second-person approval; finally run `scripts/run-unknown-demo.ps1` to show UNKNOWN after a single dispatch, the authoritative payment query, reconciliation, and closing, and finish with both n8n workflows and Mailpit. See [`DEMO.en.md`](DEMO.en.md) for exact steps.
