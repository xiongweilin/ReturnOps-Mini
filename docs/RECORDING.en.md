# Recording outline (about 4–5 minutes)

Finished video: [play the real UI recording](assets/returnflow-demo.mp4) · [Simplified Chinese subtitles](assets/returnflow-demo.zh-CN.srt). To record again, start Docker/n8n locally and run `scripts/record-demo-video.ps1`; recording creates synthetic cases/UNKNOWN cases and sends a digest to local Mailpit. The raw video and TTS are staged in the Git-ignored `.local/`.

## Before recording

1. Run `scripts/start-demo.ps1` in `pwsh` and confirm the frontend, API, and both published n8n workflows are healthy.
2. A fresh n8n volume requires no manual import/binding; the start script configures the owner, credentials, and workflows automatically. If full initialization fails, fix the dependency/configuration indicated by the error and rerun; do not delete the demo volume.
3. Mailpit is used to view demo email; verify the screen contains no real personal information, passwords, tokens, `.env` content, or database credentials.
4. Use seed-generated fictional orders; do not open `.local/automation-token.txt` during recording.

## Timeline

| Time | Visual / narration |
|---|---|
| 0:00–0:30 | Business overview: support to-dos, warehouse to-dos, finance to-dos, refund exceptions, and closed counts. Explain that all samples are fictional. |
| 0:30–1:15 | As support, create and review a new request; switch to warehouse, confirm receipt, and record inspection. Point out that every operation is constrained by server-side role and version checks. |
| 1:15–2:00 | Finance A approves a normal amount; wait for Fake Payment success, then inspect the provider reference, evidence, Outbox execution count, and audit. |
| 2:00–2:35 | Open the high-value sample: after Finance A's first approval, no second approval button is visible; switch to Finance B and check the default amount and second-person record. |
| 2:35–3:35 | Run `scripts/run-unknown-demo.ps1 -OrderRef DEMO-ORDER-UNKNOWN-002`; show `REFUND_UNKNOWN`, one dispatch, and no retry in the exception center; click the authoritative query and show Fake Payment's success evidence. |
| 3:35–4:05 | Finance reconciles and closes; show the order of unknown, query, reconciliation, and closing in the audit timeline. |
| 4:05–4:35 | Show the n8n Intake/Digest node graphs, the synthetic request created by the Production webhook, one successful 09:00 Schedule Trigger execution record, and the digest email in Mailpit. If the recording environment cannot run Docker/n8n, skip these runtime views and explain the JSON export and credential-binding boundary. |
| 4:35–5:00 | Summary: the API owns business facts; n8n owns peripheral automation; after a timeout, prefer pausing and verifying over guessing the payment outcome or blindly retrying. |

## Suggested screenshot list

- ReturnFlow business overview: [`assets/returnflow-overview.png`](assets/returnflow-overview.png)
- ReturnFlow closed case detail: [`assets/returnflow-closed-case.png`](assets/returnflow-closed-case.png)
- Finance B high-value second approval: [`assets/returnflow-second-approver.png`](assets/returnflow-second-approver.png)
- UNKNOWN safe pause and authoritative-query recovery: [`assets/returnflow-unknown-before-reconcile.png`](assets/returnflow-unknown-before-reconcile.png), [`assets/returnflow-unknown-recovered.png`](assets/returnflow-unknown-recovered.png)
- n8n Intake workflow node graph: [`assets/n8n-01-return-intake.png`](assets/n8n-01-return-intake.png)
- n8n Operations Digest node graph: [`assets/n8n-02-operations-digest.png`](assets/n8n-02-operations-digest.png)
- Mailpit actual digest inbox: [`assets/mailpit-summary-inbox.png`](assets/mailpit-summary-inbox.png)
