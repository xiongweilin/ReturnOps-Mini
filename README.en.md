# ReturnOps Mini

[![CI](https://github.com/xiongweilin/ReturnOps-Mini/actions/workflows/ci.yml/badge.svg)](https://github.com/xiongweilin/ReturnOps-Mini/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white&style=flat-square)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-required-4169E1?logo=postgresql&logoColor=white&style=flat-square)
![License](https://img.shields.io/github/license/xiongweilin/ReturnOps-Mini?style=flat-square) [![Docs: EN / 中文](https://img.shields.io/badge/docs-EN%20%7C%20%E4%B8%AD%E6%96%87-blue.svg)](README.en.md)

[简体中文](README.md) | [English](README.en.md)

ReturnOps Mini is a deliberately small multi-tenant returns and refunds SaaS that still preserves real engineering risks. It is neither a production e-commerce platform nor a showcase for how much code AI can generate. It is a compact, complete product for training **engineering judgment**.

The repository extracts the most instructive reliability problems from `commerce-orchestrator` and `administrative-orchestrator`: tenant isolation, role permissions, state machines, optimistic concurrency control, idempotency, Outbox, external side effects, unknown outcomes, webhook deduplication, reconciliation, migrations, and auditing. At the same time, it deliberately removes DBOS, Kafka, Redis, general workflow engines, CQRS, and other infrastructure that would hide the basic mechanisms.

The training goal is not to memorize every line of code. It is to build the ability to:

- draw the complete state and data flow;
- explain which code and database constraints enforce each core invariant;
- produce testable failure-path predictions in answer-free probes when that independence is the skill being tested;
- judge what a passing test actually proves and what it does not;
- assess impact radius, verification, and rollback risk after an AI-generated change;
- handle uncertain reality where an external system may have succeeded while the local system does not know.

If, after completing the training, the only conclusion you can give is “the AI review says it is fine,” the project has not achieved its goal. The end state is: **AI mainly searches, generates, challenges, and injects faults; you define correctness, choose evidence, and make the final judgment.**

## 1. Product

A merchant team uses ReturnOps Mini to process returns and refunds. The system has four roles:

- `customer_service`: create returns and review eligibility;
- `warehouse`: confirm receipt and inspect goods;
- `finance`: approve refunds, handle uncertain outcomes, reconcile, and close;
- `admin`: tenant-management role; it can perform some business actions but is not a superuser that bypasses every rule.

Normal business states:

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

External refund execution may enter an exceptional branch:

```text
REFUND_PENDING
  -> REFUND_UNKNOWN
  -> NEEDS_RECONCILIATION
  -> REFUNDED
```

The most important state is `REFUND_UNKNOWN`. An HTTP timeout proves only that this system did not receive a definite response; it does not prove that the payment provider did not execute the refund. Automatically POSTing again at that point can create a duplicate refund. The core rule is therefore: **an unknown outcome must not be blindly retried; facts must be recovered through a webhook or an authoritative query.**

## 2. Core invariants

See [`docs/invariants.md`](docs/invariants.md) for the complete list. The most important rules are:

1. Every business record belongs to exactly one Organization.
2. A user cannot read or modify return records from another Organization.
3. Cross-tenant object IDs appear as `404` to the caller.
4. Business state can change only through declared state-machine transitions.
5. Concurrent state writes must use compare-and-swap on `version`.
6. A refund amount must be greater than zero and must not exceed the requested amount.
7. High-value refunds require two different finance users to approve the same amount.
8. A refund intent uses a stable provider idempotency key.
9. When the external outcome is unknown, the system must not automatically initiate the refund again.
10. `REFUNDED` must be produced by evidence from the payment provider.
11. The same webhook event can affect business state at most once.
12. `CLOSED` and `REJECTED` are terminal states.

When reviewing AI-generated code, first ask which invariants the change touches; do not begin with variable names or code style.

## 3. Architecture

```text
Browser / API client
        |
        v
FastAPI API  ---- authentication + tenant membership
        |
        +---- Return Service ---- PostgreSQL
        |       |                   | ReturnCase / Approval / Audit
        |       |                   | IdempotencyRecord
        |       +---- Outbox -------| OutboxEvent
        |
        +---- Payment Webhook ------| WebhookReceipt
                                    |
Worker <---- FOR UPDATE SKIP LOCKED-+
  |
  v
Fake Payment Provider (separate process + SQLite)
  |
  +---- synchronous HTTP response
  +---- Webhook
  +---- authoritative query used for reconciliation
```

The project deliberately does not use DBOS, Kafka, Redis, CQRS, Event Sourcing, or a general workflow engine. This is not because those technologies are inherently bad. The training objective is to make it clear which step is a database fact, which is merely planned execution, which has crossed a network boundary, which can only be classified as unknown, and which mechanism actually prevents concurrent duplicate writes.

## 4. Layout and reading order

```text
src/returnops/
  api/                 HTTP boundary, authentication, dependency injection
  domain/              states, roles, transition rules, invariants
  services/
    returns.py          core business actions + version CAS
    idempotency.py      request replay / conflict / concurrent races
    outbox.py           durable event, claim, lease, retry
    payments.py         external refund intent, outcomes, evidence
    webhooks.py         webhook deduplication and success confirmation
    reconciliation.py  authoritative query and convergence of UNKNOWN
    worker.py           Outbox consumption and network boundary
    tenancy.py          user and Organization membership
  models.py             SQLAlchemy persistence models
  static/index.html     intentionally thin browser console

src/fake_payment/
  app.py                fault-injectable payment-provider simulator

tests/
  integration/          concurrency tests that require real PostgreSQL

docs/
  invariants.md
  failure-lab.md
  ai-judgment-training.md
```

For a first read, use: `docs/invariants.md` → `domain/states.py` → `services/returns.py` → `services/idempotency.py` → `services/worker.py` → `services/payments.py` → `services/webhooks.py` → `services/reconciliation.py`, and only then return to models, API, and tests.

## 5. Quick start

Docker and Compose v2 are required:

```bash
docker compose up --build -d
docker compose run --rm api python -m returnops.seed
```

The seed command prints an Organization ID and demo bearer tokens for several roles. Open `http://localhost:8000/`, paste the Organization ID and the matching role token into the console, and advance the workflow according to that role.

Service endpoints: API `http://localhost:8000`, API health `http://localhost:8000/health`, Fake payment `http://localhost:8090/health`.

## 6. Tests and evidence levels

Fast tests:

```bash
pytest -q -m 'not integration'
```

Real PostgreSQL concurrency tests:

```bash
export RETURNOPS_TEST_DATABASE_URL='postgresql+psycopg://returnops:returnops@localhost:5432/returnops'
pytest -q -m integration
```

Different tests can prove different things. Pure-function unit tests cover the state machine and amount rules; SQLite API tests cover HTTP contracts, tenant filtering, and ordinary transaction behavior; PostgreSQL concurrency tests cover real unique-index waiting, row locks, and CAS races; fake-provider experiments cover lost ACKs, duplicate webhooks, and cases where the external action succeeded while local state is unknown; migration round trips validate schema evolution.

“Everything is green” is not a complete conclusion. The right question is: **which invariants does this evidence actually prove, and which parts of the state space remain untested?**

## 7. Using AI to improve engineering judgment

See [`docs/ai-judgment-training.md`](docs/ai-judgment-training.md) for the full method. Do not hand the repository to AI and only ask for a “full review.” Use this loop instead:

```text
choose one invariant
↓
state the minimum clue, initial judgment, or uncertainty
↓
let AI expand candidate state/data paths, counterexamples, or formal structure
↓
decide which distinctions can change the judgment and what evidence is needed
↓
let AI inject faults or counterexamples
↓
run tests / PostgreSQL / fake provider / migration
↓
compare candidate judgments with observed results
↓
revise the model and retain reusable failure patterns
```

AI may participate heavily in search, generation, and formalization. Use answer-free work only when independent retrieval or prediction is the capability being tested. You remain responsible for deciding what counts as sufficient evidence, whether the system is sufficiently correct, and when the model must be reopened.

Suggested prompt:

```text
You are my software engineering mentor and candidate-formalization assistant.

This round focuses only on this invariant: <insert one invariant>.

Rules:
1. First let me state the minimum clue, initial judgment, or uncertainty.
2. You may expand candidate structures, counterexamples, and failure paths, but label them as candidates and do not make the final judgment for me.
3. Do not assume code or tests are correct because their names look reasonable.
4. Require me to distinguish confirmed facts, hypotheses, risks, and required evidence.
5. Switch to question-only, answer-free mode only when this round explicitly tests independent retrieval or prediction.
6. At the end, identify at most three important omissions and explain how to verify them.
```

Before merging any change, you must be able to answer: Which invariants did this change touch? Which states, database rows, or external side effects changed? What is the most dangerous failure point? Which test or experiment proves the intended property? If that proof fails, what is the worst possible system outcome?

## 8. Suggested training stages

Stage A: pure state judgment; study only `domain/states.py` and state-machine tests.

Stage B: database invariants; study tenant ownership, amount constraints, CAS, and high-value dual approval.

Stage C: request semantics; study Idempotency-Key, replay, conflict, and 20 concurrent callers.

Stage D: external reality; study worker, fake provider, webhooks, UNKNOWN, and reconciliation.

Stage E: system evolution; change approval rules, add fields, write migrations, and keep old data compatible.

## 9. Known boundaries of the first version

This is a training project, not a production-ready financial/e-commerce system. The first version prioritizes completeness and verifiability. It does not cover real PII compliance, production secret management, complex tax/multi-currency/partial refunds, SSO, a complete front-end experience, production-grade monitoring/SLOs, or multi-region disaster recovery.

The first version has locally verified non-integration tests and migration round trips. Real PostgreSQL concurrency semantics continue to be verified by CI/integration tests. A later hardening phase is intended to focus specifically on these unproven boundaries.
