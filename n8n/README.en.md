# n8n workflows

Target runtime version: **n8n 2.42.5**. Compose uses a fixed-version tag, not `latest`. Workflow JSON uses built-in n8n nodes; on first start, `scripts/start-demo.ps1` automatically initializes the owner, creates local credentials, imports/updates the JSON, and publishes the workflows.

## Workflows

| File | Trigger | Main responsibility |
|---|---|---|
| `workflows/01-return-intake.json` | Webhook `POST /webhook/return-intake` | Authenticate the caller, validate input, map `ReturnCreate`, set a stable `Idempotency-Key` from `event_id`, call the ReturnOps API, and return the create/replay/reject result to the caller. |
| `workflows/02-operations-digest.json` | Daily 09:00 Schedule Trigger; also a manual execution entry | Query live counts, owners, next actions, and cases awaiting reconciliation from `/v1/overview`, generate a digest, and send it to Mailpit over SMTP. |

The Intake workflow reports acceptance only when the API returns a business response containing a case ID. Repeating the same event returns the same case and `replayed: true`; content conflict for the same event ID returns ReturnOps' conflict information. The workflow never accesses the database directly, approves refunds, or triggers payments.

## First deployment and automatic binding

For a fresh checkout/volume, only run:

```powershell
.\scripts\start-demo.ps1
.\scripts\verify-demo.ps1
```

`start-demo.ps1` automatically performs the Compose build/start, repeatable business seed, and n8n initialization. When frontend tool dependencies are missing on first use, it runs `npm ci` from `package-lock.json` and installs headless Chromium; it then creates the owner, generates Webhook Basic Auth, generates a 90-day local bootstrap API key, and creates/updates credentials and both workflows through the n8n public REST API, binds credentials, and publishes. A rerun upserts by name and does not import again or create duplicate resources; if a step fails, services and volumes are retained and the script can be rerun directly to recover without clearing data.

The bootstrap API key is stored only in Git-ignored `.local/n8n-api-key.txt` and is used only to create/update local n8n configuration; it is recreated after expiry or a new n8n volume. It never enters workflow JSON or runtime calls. Workflows reference only credential IDs/names: `ReturnFlow Intake Caller`, `ReturnOps Demo API`, and `Mailpit SMTP`. The automation user token is read from `.local/automation-token.txt`, and the organization ID is written by Seed to `.local/organization-id.txt`; that user can only create cases and read digests, and the API rejects approval, payment, and reconciliation. SMTP connects only to `mailpit:1025` inside the Compose network and never sends externally.

Control boundary: humans only start the local demo; the script performs owner/credential/import/publish operations, the n8n data volume stores publication state, and runtime checks finally verify the webhook and Mailpit. If duplicate workflows/credentials with the same name appear, the script stops and requires cleaning up duplicates in local n8n first; it never deletes user configuration on its own. The workflow automation account is still limited by ReturnOps RBAC and cannot complete finance approval or trigger refunds.

The n8n API key uses the self-hosted public REST API (see [n8n API authentication](https://docs.n8n.io/connect/n8n-api/authentication/)); secrets are never written to the repository or workflow JSON.

Manual import/binding from the editor is only a troubleshooting fallback, not a new-environment acceptance step. `Schedule Trigger` runs in the timezone configured by `GENERIC_TIMEZONE` (default `Asia/Shanghai`) only after publication; the digest can also be run manually from the editor.

## Local Intake integration acceptance

After starting Compose fully, `scripts/start-demo.ps1` automatically imports/publishes Intake and binds the Webhook and `Custom Auth` credentials. To verify runtime branches, run:

```powershell
cd frontend
$env:RUN_N8N_INTEGRATION = '1'
npm run test:n8n
Remove-Item Env:RUN_N8N_INTEGRATION
npm run test:n8n:digest
```

The script allows access only to the loopback Production URL and reads Basic Auth from ignored `.local/n8n-intake-credentials.json`; it never prints credentials. It verifies 401 unauthorized, 400 invalid input, 201 case creation, same-case replay for the same event, and 409 for different content under the same idempotency key. The fixed synthetic event can be run repeatedly without creating duplicate cases; after resetting the demo database, the same synthetic sample can be recreated.

HTTP request addresses in workflow files use the Compose service name `api`. When calling from outside the container, use the Test or Production Webhook URL shown by n8n. The demo UI and editor should be accessed only through the local loopback address.

## Current local acceptance

The current Compose n8n 2.42.5 instance has had credentials automatically created/updated, both workflows upserted and published by `start-demo.ps1`. Runtime integration checks of the Production webhook measured unauthorized, invalid, create, replay, and conflict branches; the actual created case remained `requested`, and no refund was approved. Operations Digest manual trigger and Mailpit delivery passed; the daily schedule then actually fired at 2026-10-10 09:00:53 (Asia/Shanghai), n8n execution record ID `20` shows Succeeded (110 ms), and Mailpit received the role to-dos and next actions from the live API query. For workflow and runtime evidence screenshots, see [`docs/assets/`](../docs/assets/); for full results and limitations, see [`docs/TEST-EVIDENCE.en.md`](../docs/TEST-EVIDENCE.en.md).

Workflows and credentials remain in the local n8n volume and are not committed with the repository JSON export. After creating or resetting a volume, rerun `scripts/start-demo.ps1` to reinitialize the owner, create local credentials, and publish the workflows; local automation tokens, owner login, the bootstrap API key, and Webhook Basic Auth values exist only in ignored `.local/` files.

## Email outcome semantics

The digest email is an informational notification. Multiple manual runs or repeated schedules may produce multiple digests for the same date; an SMTP timeout can also occur after Mailpit has received the email. n8n records the execution result, and manual reruns may resend, so this flow does not claim exactly-once email delivery.

## Official resources

- [n8n workflow import and export](https://docs.n8n.io/build/manage-workflows/export-and-import/)
- [Webhook node and test/production URLs](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)
- [Respond to Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook/)
- [Schedule Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/)
- [Send Email](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.sendemail/)
