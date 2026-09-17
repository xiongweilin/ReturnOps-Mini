# ReturnOps Mini

ReturnOps Mini is a deliberately small but rigorous multi-tenant returns/refunds SaaS used to practice engineering judgment with AI-generated code.

The codebase is intentionally much smaller than `commerce-orchestrator` and `administrative-orchestrator`. It keeps the failure modes that matter—tenant isolation, role checks, state transitions, optimistic concurrency, idempotency, durable outbox work, ambiguous external effects, webhook deduplication, reconciliation, migrations, and audit evidence—while removing generic workflow engines and unrelated domains.

The training goal is not to memorize every line. It is to be able to explain the system's invariants, predict failure modes, trace state changes, and decide what evidence is sufficient before accepting an AI-generated change.

## Product

A merchant team handles a return through these roles:

- `customer_service`: creates and authorizes a return.
- `warehouse`: confirms receipt and inspection.
- `finance`: approves the refund, reconciles uncertain provider results, and closes the case.
- `admin`: tenant administration role; it is deliberately not a universal business-action bypass.

The normal state path is:

```text
REQUESTED
  -> AUTHORIZED
  -> RECEIVED
  -> INSPECTED
  -> REFUND_APPROVED
  -> REFUND_PENDING
  -> REFUNDED
  -> RECONCILED
  -> CLOSED
```

External refund execution can branch:

```text
REFUND_PENDING
  -> REFUND_UNKNOWN          # request may have reached provider, ACK was lost
  -> NEEDS_RECONCILIATION    # outcome is known failed or requires human attention
  -> REFUNDED                # provider evidence confirms success
```

`REFUND_UNKNOWN` is the most important state in the project. A timeout does not prove that a refund failed. The worker therefore stops automatic retries after an ambiguous network result and requires provider reconciliation.

## Non-negotiable invariants

The detailed list lives in [`docs/invariants.md`](docs/invariants.md). The core rules are:

1. A return belongs to exactly one organization, and tenant-scoped reads/writes must include that organization.
2. Cross-tenant object identifiers resolve as `404`, not as an authorization oracle.
3. Business state changes go through the state machine and use compare-and-swap (`version`) updates.
4. Approved refund amount must be positive and cannot exceed the requested amount.
5. High-value refunds require two distinct finance approvers for the same amount.
6. A refund attempt has one stable provider idempotency key.
7. An ambiguous provider outcome is never automatically retried.
8. `REFUNDED` requires provider evidence (sync response, webhook, or authoritative lookup), not a user button.
9. Duplicate webhooks are harmless; event-id reuse with different payload is rejected.
10. `CLOSED` is terminal.

When reviewing AI-generated changes, start from these invariants rather than from line-by-line aesthetics.

## Architecture

```text
Browser / API client
        |
        v
FastAPI API  ---- authentication + tenant membership
        |
        +---- Return service ---- PostgreSQL
        |       |                   | cases / approvals / audit
        |       |                   | idempotency records
        |       +---- outbox -------| events
        |
        +---- payment webhook ------| webhook receipts
                                    |
Worker <---- FOR UPDATE SKIP LOCKED-+
  |
  v
Fake Payment Provider (separate process + SQLite)
  |
  +---- synchronous response
  +---- webhook
  +---- authoritative lookup for reconciliation
```

The code deliberately does **not** use DBOS, Kafka, Redis, CQRS, event sourcing, or a generic workflow engine. The intent is to make the reliability mechanisms visible rather than delegated to infrastructure.

## Repository map

```text
src/returnops/
  api/                 HTTP boundary and dependency wiring
  domain/              state vocabulary, transitions, invariants
  services/
    returns.py          business operations + version CAS
    idempotency.py      request replay/conflict semantics
    outbox.py           durable event claim/lease/retry
    payments.py         external-effect truth and evidence
    webhooks.py         deduplication + provider confirmation
    reconciliation.py  resolve ambiguous outcomes
    worker.py           dispatch loop
    tenancy.py          authentication/tenant membership checks
  models.py             SQLAlchemy persistence model
  static/index.html     thin operations console
src/fake_payment/
  app.py                controllable external provider simulator
tests/
  integration/          PostgreSQL concurrency tests
```

## Quick start with Docker Compose

Requirements: Docker with Compose v2.

```bash
docker compose up --build -d

docker compose run --rm api python -m returnops.seed
```

The seed command prints one organization id plus five demo bearer tokens. Open:

```text
http://localhost:8000/
```

Paste the organization id and the appropriate role token into the operations console.

Useful service endpoints:

```text
API:          http://localhost:8000
API health:   http://localhost:8000/health
Fake payment: http://localhost:8090/health
```

Stop everything with:

```bash
docker compose down
```

Use `docker compose down -v` only when you intentionally want to delete the PostgreSQL and fake-provider data volumes.

## Local development without Compose

Python 3.12+ is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
alembic upgrade head
python -m returnops.seed
uvicorn returnops.main:app --reload
```

Run the fake payment provider separately:

```bash
FAKE_PAYMENT_DB=./fake-payment.db \
FAKE_PAYMENT_WEBHOOK_URL=http://localhost:8000/v1/webhooks/payment \
uvicorn fake_payment.app:app --port 8090
```

Run the worker separately:

```bash
python -m returnops.services.worker
```

## Tests

Fast unit/service/API tests:

```bash
pytest -q -m 'not integration'
```

PostgreSQL concurrency tests require a real PostgreSQL server because SQLite cannot prove row-lock and unique-index race behavior:

```bash
export RETURNOPS_TEST_DATABASE_URL='postgresql+psycopg://returnops:returnops@localhost:5432/returnops'
pytest -q -m integration
```

The CI workflow starts PostgreSQL 17 and runs both suites. It also checks Alembic upgrade/downgrade/upgrade behavior.

## Failure simulation

Set `RETURNOPS_PAYMENT_SIMULATION_MODE` for the worker/API environment and restart the relevant service.

Supported fake-provider modes:

- `normal`: provider persists the refund, returns success, and emits a webhook.
- `503_before_processing`: provider explicitly rejects before processing; safe automatic retry is allowed.
- `timeout_after_processing`: provider persists success but withholds the HTTP ACK; ReturnOps must enter `REFUND_UNKNOWN` and must not blindly retry.
- `duplicate_webhook`: provider sends the same webhook event twice.
- `no_webhook`: provider returns synchronous success but does not send a webhook.

See [`docs/failure-lab.md`](docs/failure-lab.md) for exercises where the expected answer is intentionally not reduced to “tests are green”.

## High-value approval rule

`RETURNOPS_HIGH_VALUE_THRESHOLD` is expressed in minor currency units. The default is `50000` (for USD, 500.00).

Below the threshold, one finance approval transitions the case and plans the refund. At or above the threshold, the first finance approval records intent but leaves the case `INSPECTED`; a second **different** finance user must approve the exact same amount before the case advances.

This rule is intentionally simple enough to understand and rich enough to expose stale-version races, duplicate decisions, identity constraints, and migration questions.

## Why idempotency is implemented this way

Every mutating business API requires `Idempotency-Key`. A record is unique by `(organization_id, scope, key)`.

The important race is two requests that both read “no record” and then insert the same key. The implementation uses the database unique constraint plus a savepoint. On PostgreSQL, the loser waits for the winner transaction to settle, rolls back only the savepoint, then reads and replays the committed response. It does not turn a normal concurrency loser into an unhandled `IntegrityError`/500.

The integration test launches 20 concurrent sessions and expects all 20 calls to receive the same winner response.

## Why state updates use CAS

A Python check such as:

```python
if case.version == expected_version:
    case.status = next_status
```

is insufficient when two transactions can read the same version. ReturnOps performs the write as a conditional update equivalent to:

```sql
UPDATE return_case
SET status = :new_status,
    version = version + 1
WHERE id = :id
  AND organization_id = :organization_id
  AND version = :expected_version
  AND status = :expected_status;
```

Exactly one concurrent writer can match the old version. A zero-row update becomes `VersionConflict`.

## Training workflow

Do not ask an AI to “review the whole repo” and accept its answer. Use this cycle:

1. Pick one invariant from `docs/invariants.md`.
2. Draw the relevant data/state path without looking at implementation details.
3. Find the code that claims to enforce it.
4. Write down one failure scenario that would violate it.
5. Identify whether the evidence should come from a unit test, PostgreSQL concurrency test, migration test, fake-provider experiment, or manual inspection.
6. Ask an AI reviewer to challenge your reasoning, not to replace it.
7. Only then inspect or change the code.

The project is small enough that you should eventually be able to explain every module's responsibility, while still large enough to contain real distributed-systems failure semantics.

## Deliberate limitations

This is a training product, not a production commerce platform. It intentionally omits:

- real PII handling and regulatory retention policy;
- real payment credentials/signature schemes;
- rate limiting and abuse prevention;
- currency-specific decimal/rounding rules beyond minor-unit integers;
- refunds split across multiple payment instruments;
- partial/multiple refund attempts on one return;
- email/SMS notification infrastructure;
- complex tenant administration and SSO;
- production observability stack.

Those omissions are boundaries, not invitations to silently assume production readiness.
