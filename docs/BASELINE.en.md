# ReturnFlow development baseline

Recorded: 2026-10-09

> Historical record: this document describes only the repository and runtime environment before the first implementation; actual Docker / PostgreSQL / n8n acceptance results appear in [`TEST-EVIDENCE.en.md`](TEST-EVIDENCE.en.md).

## Git baseline

- At the start of the inspection, the worktree was clean on `main`, at baseline commit `c2563b38bf72d160079e8ddfe7595ab0ca151466` (2026-09-29).
- Per the task requirements, created and switched to `feature/returnflow-portfolio` from the clean baseline.
- No project feature code had been modified or committed after this record.

## Existing implementation

| Area | Baseline state |
|---|---|
| Business state and permissions | FastAPI provides Bearer Token, organization membership, and role checks; support, warehouse, finance, and admin roles and the return state machine already exist. Case-state writes use version CAS. |
| Returns and refunds | APIs already exist for case creation, eligibility approval, receipt, inspection, refund approval, rejection, refund reconciliation, and closing. The high-value refund threshold is configurable and requires two different finance users to approve. |
| Reliability | Request idempotency records, an Outbox worker, stable payment idempotency keys, payment-evidence verification, webhook deduplication, pausing automatic dispatch on unknown outcomes, authoritative provider queries, and audit events already exist. |
| Payment simulation | A separate Fake Payment service stores simulated refunds and can be configured to demonstrate pre-processing failure, post-processing timeout, webhook confirmation before timeout, and duplicate webhooks. |
| Database | SQLAlchemy models cover organizations, users, memberships, cases, approvals, refund intents, webhook receipts, audits, idempotency records, and Outbox. Alembic currently has only the initial schema migration. |
| Operator UI | `/` serves a static landing page; it has no business operations. The API has case listing, basic detail, creation, and state operations, but detail returns no approvals, refund evidence, or audit timeline, and there is no overview summary API. |
| Demo initialization | Seed creates the organization and five demo identities when `Demo Store` does not exist; it returns immediately when the organization exists. It does not yet generate repeatable reset scenarios or provide a browser demo-identity entry point. |

## Still missing for this task

- A standalone React, TypeScript, Vite operations console with overview, cases, detail, and exception/reconciliation pages.
- n8n Intake and Operations Digest workflows with a restricted service identity, importable JSON, and configuration instructions.
- Mailpit, the read-only APIs needed for digests, and the email-notification workflow.
- A local demo mode, repeatable scenario data, start/stop/initialize/reset/verify scripts, and business-demo documentation and runtime screenshots.
- The current Compose setup contains only PostgreSQL, migrations, API, worker, and Fake Payment; it has no frontend, n8n, or Mailpit services.

## Phase 0 verification results

| Check | Result |
|---|---|
| `docker compose config --quiet` | Passed; the existing Compose configuration parsed. |
| `docker compose build` | Not completed. The Docker CLI could not connect to the local Docker Desktop Linux Engine named pipe; container build and runtime were therefore not verified. No containers were started. |
| `.\.venv\Scripts\pytest.exe -q -m 'not integration'` | Passed: 30 passed, 8 deselected; two deprecation warnings from Starlette/httpx appeared. |
| `.\.venv\Scripts\pytest.exe -q -m integration` | 8 skipped, 30 deselected. Test fixtures were skipped because `RETURNOPS_TEST_DATABASE_URL` was not configured; PostgreSQL concurrency and runtime semantics were not verified on this machine. |

The repository virtual environment uses Python 3.12.13 with project dependencies. The system `pytest` without arguments uses Python 3.14.8 and could not load the tests because SQLAlchemy was missing; this baseline test ran in the repository virtual environment.

## Evidence boundary

The checks above prove that the existing SQLite unit and API tests passed; they do not prove that PostgreSQL concurrency, Docker deployment, the browser console, n8n, or Mailpit can run. There is no local enterprise usage data, so no claim can be made about saved hours, lower error rates, or production reliability.
