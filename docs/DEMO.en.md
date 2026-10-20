# ReturnFlow local demo script

## 1. Start and access

In Windows PowerShell 7:

```powershell
.\scripts\start-demo.ps1
```

The first start automatically creates an ignored `.env` and random secrets, seeds demo data, initializes the n8n owner, binds credentials, and publishes both workflows; no manual import/binding in n8n is required. Docker Desktop, Node.js 24+, and npm must be installed; the first run downloads images and Playwright Chromium. All secrets exist only in ignored `.env`/`.local` files; do not copy them into browser forms, workflow JSON, or recordings. Common pages:

- Frontend: <http://127.0.0.1:4173>
- API docs: <http://127.0.0.1:8000/docs>
- n8n: <http://127.0.0.1:5678> (initialized and workflows published after first start)
- Mailpit: <http://127.0.0.1:8025>

## 2. Seed data

Demo identities are "support / warehouse / Finance A / Finance B / admin". The seed covers at least the following paths:

| Order | Initial state | Demo point |
|---|---|---|
| `DEMO-ORDER-INTAKE-001` | Awaiting support review | n8n can repeatedly deliver the same `event_id`; the API returns the same case |
| `DEMO-ORDER-REJECTED-001` | Rejected | Support rejection and reason are recorded |
| `DEMO-ORDER-WAREHOUSE-001` | Awaiting warehouse inspection | Receipt/inspection permission boundary |
| `DEMO-ORDER-FINANCE-001` | Awaiting finance approval | Normal approval path |
| `DEMO-ORDER-HIGH-VALUE-001` | First finance approval recorded | Finance A no longer sees a second "approve refund"; Finance B can approve the same amount |
| `DEMO-ORDER-CLOSED-001` | Closed | Normal refund evidence, reconciliation, and audit timeline |

`seed-demo.ps1` can be rerun. Existing samples are not duplicated indefinitely; newly created samples are still entirely synthetic.

## 3. Browser end-to-end tests

Start the ReturnFlow stack first, then:

```powershell
cd frontend
npm ci
npx playwright install chromium
$env:RETURNFLOW_FRONTEND_URL = 'http://127.0.0.1:4173'
$env:SAVE_DEMO_SCREENSHOTS = '1'
npm run e2e:typecheck
npm run test:e2e
```

The test creates a unique fictional order and completes support review, warehouse receipt and inspection, finance approval, Fake Payment, reconciliation, and closing; a second test asserts that a high-value refund requires a second approval by a different finance identity. Screenshots are saved to `docs/assets/`.

## 4. Webhook idempotency demo

After importing the Intake workflow in n8n and binding credentials, deliver the same content with the same `event_id` repeatedly. Expected:

- The same `caseRef` is returned and only one case exists in the tenant;
- Changing the request body while keeping the same idempotency key returns a conflict and does not overwrite the original business fact;
- When the API errors, n8n ends with an explicit error response and does not modify the database directly or resend refunds from n8n.

A restricted local integration check can also cover rejection, validation, creation, replay, and conflict paths at once:

```powershell
cd frontend
$env:RUN_N8N_INTEGRATION = '1'
npm run test:n8n
Remove-Item Env:RUN_N8N_INTEGRATION
```

The test always uses the synthetic event `returnflow-n8n-runtime-v1` and the loopback Production URL; repeated runs replay the same case and do not create duplicates. Invalid, conflicting, or unauthorized requests never receive a success response.

## 5. Lost ACK and UNKNOWN recovery

```powershell
.\scripts\run-unknown-demo.ps1 -OrderRef DEMO-ORDER-UNKNOWN-002
```

The command pauses the background worker and processes the specified refund with a one-off executor locked by event ID. Fake Payment has **already stored the refund**, the synchronous response is delayed past the client timeout, and no webhook is sent. The result prints the synthetic case number and `refund_unknown`, never a token.

In the Finance workspace:

1. Open "Exceptions & Reconciliation" and find the specified `DEMO-ORDER-UNKNOWN-NNN`.
2. Verify that the page shows `Payment outcome unknown`, the latest exception is a timeout, the dispatch count is 1, and there is no automatic-retry button.
3. Click "Query provider status". It should read Fake Payment's stored success record, supplement evidence using the provider reference and idempotency key, and transition to `REFUNDED`.
4. Click "Mark reconciliation complete", then "Close case". The audit records should retain `refund.outcome_unknown`, the authoritative query, `return.reconciled`, and `return.closed`.

To have the browser automatically accept the same recovery flow, start the demo stack, complete the script above, then run:

```powershell
cd frontend
$env:RETURNFLOW_FRONTEND_URL = 'http://127.0.0.1:4173'
$env:RETURNFLOW_UNKNOWN_ORDER_REF = 'DEMO-ORDER-UNKNOWN-002'
$env:RUN_FAULT_E2E = '1'
npm run test:e2e:fault
```

`-OrderRef` accepts only the `DEMO-ORDER-UNKNOWN-NNN` format, used to select a different synthetic order number across repeated runs in the isolated demo environment; it does not expose arbitrary fault parameters to the public API.

Rerunning the same `OrderRef` while it is still UNKNOWN does not dispatch again; after recovery or closing, choose a new `DEMO-ORDER-UNKNOWN-NNN` for another demo. Use the confirmed `reset-demo.ps1` only when all local samples must be erased.

## 6. Email digest and shutdown

Run the Operations Digest workflow manually in n8n, then inspect `operations@demo-store.example` in Mailpit. The workflow is published automatically by `start-demo.ps1`; the default schedule is 09:00 `Asia/Shanghai`. To verify the schedule again, keep the local stack running until 09:00, then check for a `Succeeded` execution under the workflow's **Executions** and confirm the corresponding email in Mailpit. The current local instance actually ran successfully once at 2026-10-10 09:00:53; see [`TEST-EVIDENCE.en.md`](TEST-EVIDENCE.en.md) for details. To-dos and roles in the digest come from current ReturnOps API data.

```powershell
.\scripts\verify-demo.ps1
.\scripts\stop-demo.ps1
```

Stopping preserves named volumes. To truly delete all ReturnFlow demo state, run:

```powershell
.\scripts\reset-demo.ps1
```

This script requires typing `RESET-RETURNFLOW` exactly before it runs `docker compose down --volumes --remove-orphans` and deletes local automation token files. This irreversibly erases this project's demo data; never run it in any real or shared environment.
