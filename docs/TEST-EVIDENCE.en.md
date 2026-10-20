# Test evidence and environment limitations

## Executed

| Check | Result |
|---|---|
| `pytest -q -m 'not integration'` | **41 passed, 8 deselected**; covers domain/API, tenant isolation, four-eyes approval, idempotency, worker/outbox, reconciliation, and workflow JSON structure tests |
| `pytest -q -m integration` | **8 passed, 41 deselected**; connected to local Compose PostgreSQL, each test ran in an isolated temporary schema and cleaned up; 2 Starlette/httpx deprecation warnings |
| Full `pytest -q` | **49 passed**, 2 deprecation warnings |
| `ruff check src/returnops src/fake_payment tests` | Passed |
| `npm run build` | Passed (TypeScript + Vite production bundle) |
| `npm run e2e:typecheck` | Passed |
| GitHub `frontend` CI job | Independently runs `npm ci`, `npm run build`, `npm run lint`, and `npm run e2e:typecheck` on every CI run |
| `npm run test:e2e` | **3 passed, 1 skipped**; normal loop, high-value different approvers, and support lacking approval permission (UI hidden and API returns 403), run against local Compose frontend/API |
| `npm run test:e2e:fault` | **1 passed**; UNKNOWN, single dispatch, no blind retry, authoritative query, reconciliation, and closing, run against the local demo stack |
| `npm run lint` | Passed with no lint warnings |
| `npm run test:n8n` with PowerShell `RUN_N8N_INTEGRATION` set | **Passed**; Production webhook measured 401 unauthorized, 400 invalid input, 201 case creation, 201 same-case replay, and 409 content conflict; failures are never marked accepted |
| `scripts/verify-demo.ps1` | Compose service list and ReturnOps API, demo mode, frontend, n8n editor, and Mailpit page checks passed |
| `docker compose ps` | PostgreSQL, API, Fake Payment, and Mailpit healthy; frontend, n8n, and worker running. Host ports bind only to `127.0.0.1` |
| `n8n/workflows/*.json` | JSON and static node/credential constraint tests passed; a fresh n8n **2.42.5** volume was automatically created/bound with three local credentials, both workflows were upserted and published by `start-demo.ps1`, with no manual UI import or per-node configuration |
| Intake Production webhook | Runtime integration tests passed all branches; the fixed synthetic event retained case `RET-4B014F9106` in the ReturnOps API with state `requested`. No refund was triggered |
| Operations Digest | Manual execution succeeded after container restart; the daily Schedule Trigger then fired automatically at 2026-10-10 09:00:53 (Asia/Shanghai), n8n execution record ID `20` shows Succeeded (110 ms), and Mailpit received an email from the live API digest with to-dos, responsible roles, and next actions; the current local inbox contains 6 digests. No real SMTP was connected |
| Restart persistence | Restarted PostgreSQL, API, worker, frontend, Fake Payment, n8n, and Mailpit without deleting any volume; demo cases still existed, the timeout sample's provider record remained `succeeded` with `post_count=1`, and Mailpit email was preserved; after restart, `verify-demo.ps1`, the n8n Intake integration check, and manual Digest execution all succeeded again |
| `npm run test:n8n:digest` | **Passed**; Playwright manually ran the published Digest in the n8n UI, received a new Mailpit email, and the body contained live to-dos and support/warehouse/finance roles |
| Fresh-environment `start-demo.ps1` | Starting from a source copy with no `.env`, `.local`, `frontend/node_modules`, or `.git`, created an empty Compose project/volumes; a single command completed seed, owner, 90-day API key, local credentials, and two published workflows; a second run reused the same workflow ID/key and created no duplicate resources, with no manual n8n UI steps |
| Controlled full-demo verification | In the same clean Compose project, `verify-demo.ps1`, normal Playwright E2E (3 passed/1 skipped), UNKNOWN recovery E2E (1 passed), n8n webhook branches, and Digest→Mailpit all passed; real payment and external SMTP were not connected |

### First deployment clean-environment reproduction

Starting in Windows PowerShell 7 from a new source copy; the copy had no `.env`, `.local/`, `frontend/node_modules/`, or `.git/`, and used a new Compose project and named volumes. The only deployment action was running `scripts/start-demo.ps1`: it generated ignored local environment/owner/webhook credentials, ran the seed, installed the locked npm toolchain, created and verified a local n8n API key, then created/updated credentials through the n8n API, imported both JSON files, and published them. No human ever logged into n8n, clicked Import, bound nodes individually, or published manually. `scripts/verify-demo.ps1` and the Intake/Digest runtime checks then passed; rerunning `start-demo.ps1` reused the existing key and workflow IDs without duplicates.

During the clean-environment trial, a temporary self-chosen API port conflicted with an independently running AIOS service on the same machine, and another first image build hit a PyPI TLS EOF; after choosing an unused loopback port and retrying, the independent project started successfully. Both issues were test-host resource/transient network problems; no other Compose project data was modified or cleaned.

### 2026-10-10 README clean-environment reproduction

This round built a fresh source copy from a Git archive of `main` merge commit `beacc62702ffd692684abdee6bd461f99752aa7f`; the copy initially had no `.git/`, `.env`, `.local/`, or `frontend/node_modules/`, and used an independent Compose project and fresh named volumes. Followed the README and ran `scripts/start-demo.ps1` twice: the first run generated local configuration and created/published both n8n workflows, the second reused existing resources; `scripts/verify-demo.ps1` passed. `npm ci`, Chromium installation, normal browser E2E (3 passed, 1 skipped), UNKNOWN recovery E2E (1 passed), n8n Intake webhook (401, 400, 201, same-event replay 201, conflict 409), and the Digest→Mailpit email check all passed. The unknown-refund scenario confirmed that Fake Payment stored the refund and no webhook was sent; finance completed reconciliation after the authoritative query. After reproduction, only this round's independent Compose project was stopped; its volumes were retained.

The first controlled GitHub Actions run was triggered on merged `main` commit `beacc62702ffd692684abdee6bd461f99752aa7f`: [run 38034480552](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38034480552). On a clean Ubuntu runner, Seed hit permission denied while writing `.local/organization-id.txt`, so the subsequent browser, UNKNOWN, n8n, and email verification did not run. The cause was that the Compose bind mount created a root-owned directory when host `.local/` did not yet exist; `scripts/start-demo.ps1` was adjusted to create the host directory before starting Compose.

After the directory fix, [run 38035544448](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38035544448) passed stack startup, the basic browser flow, and UNKNOWN creation, but the recovery test looked for default order `DEMO-ORDER-UNKNOWN-002`, while the preceding script created `DEMO-ORDER-UNKNOWN-981`; the browser could not find the target case, so the subsequent Intake and Digest steps were skipped. The workflow now configures both the creation script and the recovery test through the same `RETURNFLOW_UNKNOWN_ORDER_REF` environment value.

The final [run 38035879608](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38035879608) completed successfully on a clean Ubuntu runner at code commit `4e9e588b37cb8e417c4d7902182a07036eda0276`: automatic n8n startup and configuration, full stack checks, normal browser E2E, UNKNOWN scenario creation, browser authoritative-query/reconciliation/closing recovery, Production Intake webhook, Digest→Mailpit, and cleanup of the temporary Compose project and test volumes—all steps succeeded. The tested application and workflow code did not change in the documentation commit of the final recorded run number.

In the first regular PR CI round, [run 38036341354](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38036341354), 7 of 8 checks passed; Fault Lab hit a PostgreSQL deadlock with an in-flight Fake Payment webhook while resetting scenario data. Fault Lab's synchronous response delay and UNKNOWN reconciliation scenarios were changed not to deliver non-target webhooks, isolating async requests from the next scenario. The subsequent [run 38036635498](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38036635498) passed all 8 PR checks, including four Fault Lab scenarios, the performance contract, frontend, PostgreSQL integration, dependency/image scanning, mutation testing, quality, and hygiene checks.

Sampled review of the video and text: the MP4 duration is 297.2 seconds, consistent with the about 4–5 minute recording outline; the Simplified Chinese subtitles and `RECORDING.md` timeline cover the overview, Intake idempotency, role approvals and high-value two-person review, manual query after an unknown payment outcome, Operations Digest, and Mailpit receipt. A sampled check of representative frames showed that these UI views match this round's browser, n8n, and Mailpit runtime evidence. The video and all runtime samples use fictional data, local Fake Payment, and Mailpit.

The Playwright browser flow connects to the local Compose frontend/API, PostgreSQL, Fake Payment, and worker, and performs support creation/review, warehouse receipt/inspection, normal refund, external success evidence, finance reconciliation, and closing; a direct API request for finance approval as support returns 403. In the timeout scenario, Fake Payment stored the refund, the delayed response timed out, and no webhook was sent; the UI showed `REFUND_UNKNOWN` and dispatch count 1; Finance queried the provider record, confirmed success, and completed reconciliation and closing. The end-to-end test leaves dynamically generated `DEMO-PLAYWRIGHT-*` synthetic cases in the persistent demo database; the fault test also leaves a closed `DEMO-ORDER-UNKNOWN-003`, and the n8n production webhook leaves `DEMO-ORDER-N8N-LIVE-*` and the fixed `DEMO-ORDER-N8N-RUNTIME-001` cases. None of these are customer data. They remain readable after the container restarts described above, and the provider still has only one dispatch record.

PostgreSQL integration tests use temporary schemas in the Compose database and drop them when the tests exit; demo data is neither reused nor cleared. The n8n Runtime check uses a fixed `event_id`; repeated execution of the same event returns the same case, while conflicts and input errors create no new business record.

Screenshots are generated from the real UI:

- [ReturnFlow normal case loop](assets/returnflow-closed-case.png)
- [ReturnFlow live business overview](assets/returnflow-overview.png)
- [ReturnFlow high-value two-person approval](assets/returnflow-second-approver.png)
- [ReturnFlow UNKNOWN safe pause and recovery](assets/returnflow-unknown-before-reconcile.png), [authoritative query evidence](assets/returnflow-unknown-recovered.png)
- [n8n Return Intake node graph](assets/n8n-01-return-intake.png)
- [n8n Operations Digest node graph](assets/n8n-02-operations-digest.png)
- [n8n scheduled digest execution record](assets/n8n-02-scheduled-execution.png)
- [Mailpit digest inbox](assets/mailpit-summary-inbox.png)

### 2026-10-10 latest main post-fix acceptance

PR [#8](https://github.com/xiongweilin/ReturnOps-Mini/pull/8) merged the readiness fix into main at code commit `fd9ce37448d57d8cc81ad71ac22a72c8bb393147`. Before the fix, the latest main's [CI run 38037011756](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38037011756) failed at the Fault Lab performance step: `docker compose up -d --build` had started the API, but `docker compose run --rm k6` started dependencies by default and rebuilt the API; `depends_on: service_started` only means the container started, not that the HTTP service is ready. Logs showed that k6's immediate requests were refused, and the final failure rate was **5.27% (278/5274)**.

`faultlab/run_perf.py` now first polls the real `http://127.0.0.1:8000/health`, requiring HTTP 200 with status `ok`, for up to 60 seconds; it then starts k6 with `docker compose run --no-deps --rm k6`, avoiding a rebuild of the running API. `faultlab/k6/perf_contract.js` was not modified; the original thresholds remain: `http_req_failed: ['rate<0.01']`, `http_req_duration: ['p(95)<500', 'p(99)<1000']`, `duplicate_effect: ['count==0']`.

The fix PR's [regular checks run 38038353761](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38038353761) all passed. The merged latest main's [CI run 38038495640](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38038495640) succeeded in all 8 jobs at commit `fd9ce37448d57d8cc81ad71ac22a72c8bb393147`, including Fault Lab scenarios and the k6 performance contract.

After regular CI was fully green, a [controlled demo integration run 38038686561](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38038686561) was triggered on the same main commit and completed fully: isolated demo stack and automatic n8n configuration, service checks, normal browser E2E, UNKNOWN payment creation and browser recovery, Production Intake webhook, Operations Digest→Mailpit, and cleanup of that temporary project.

A fresh source copy was also built from a Git archive of that main commit; it initially had no `.git/`, `.env`, `.local/`, or `frontend/node_modules/`, and used an independent Compose project. Ran `scripts/start-demo.ps1` twice per the README, running `scripts/verify-demo.ps1` after each; both succeeded, and the second run reused the existing n8n local credentials and both published workflows. API, PostgreSQL, Fake Payment, and Mailpit were healthy, and the frontend, API, n8n editor, and Mailpit page checks passed. `scripts/stop-demo.ps1` then stopped only that isolated project and retained its volumes. Local secrets generated during startup were neither displayed nor copied.

For the interview pitch, see [`INTERVIEW-PITCH.en.md`](INTERVIEW-PITCH.en.md), organized around the business problem, Return Intake and Operations Digest, role approval responsibility, and manual query and recovery after an unknown refund outcome. The latest main's controlled run covers the normal, approval, exception-recovery, and email-digest paths described in the recording and demo documentation. The MP4, subtitles, and `RECORDING.md` used in the earlier sampled video check were unchanged in this main update; this round did not re-encode or re-check the video frame by frame. This section's CI and controlled demo are bound to fix commit `fd9ce37448d57d8cc81ad71ac22a72c8bb393147`; this evidence-document commit does not change the tested code.

## Not yet verified / boundaries

- The real daily schedule has been observed once: n8n executed successfully at 2026-10-10 09:00:53 (Asia/Shanghai) and Mailpit received the email. One success does not prove long-term scheduling reliability; no real SMTP is connected, and exactly-once delivery of SMTP retries has not been verified (this system makes no such promise).
- The Playwright browser end-to-end flow runs against PostgreSQL through the local Compose frontend/API; randomly generated synthetic test cases remain in the named volume. PostgreSQL integration tests instead use a temporary schema created per test and dropped afterward.
- No real email or payment service is connected. Mailpit and Fake Payment are local services and produce no outbound email or real refunds.
- The owner, short-lived bootstrap API key, and runtime credentials are stored in Git-ignored `.local/` files and the local n8n encrypted volume; workflow JSON and screenshots contain no secrets. After creating/resetting volumes, rerunning `scripts/start-demo.ps1` restores the owner, credentials, and published workflows automatically; Docker Desktop, Node.js 24+, npm, and network access for the first dependency/image pull are required.
- [`BASELINE.en.md`](BASELINE.en.md) is the historical baseline before the first implementation; its "Docker unavailable / n8n not running" describes only the state at that time; current runtime evidence is this document.
