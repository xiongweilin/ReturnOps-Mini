# Failure lab: exercises for engineering judgment

Use these exercises after the happy path works. The point is to predict the correct state/evidence first, then run the experiment.

Do not ask an AI for the final answer before writing your own prediction.

## Lab 1 — stale version

Setup:

1. Put a case in `AUTHORIZED` with version `2`.
2. Open two independent database/API clients.
3. Both read version `2`.
4. Both try to receive it with `expected_version=2`.

Prediction questions:

- How many writes may succeed?
- What exact database predicate enforces that?
- What state/version remains?
- What happens to audit rows from the losing transaction?

Acceptance: one winner, one `VersionConflict`; the loser transaction must not leave business artifacts.

## Lab 2 — same idempotency key, 20 callers

Run the PostgreSQL integration test or reproduce it manually.

Prediction questions:

- Why can both callers initially observe “no record”?
- At which database operation do they serialize?
- Why is a savepoint used?
- Why is catching `IntegrityError` without a savepoint dangerous?
- Why must the loser read the winner's response rather than inventing a second response?

Acceptance: all callers get one logical result, exactly one idempotency row exists, and no caller receives a generic 500.

## Lab 3 — cross-tenant object id

1. Create Organization A and Organization B.
2. Create a return under A.
3. Authenticate as a valid B user.
4. Call `GET /v1/returns/{A_case_id}` while selecting B.

Prediction questions:

- Should this be 403 or 404, and why?
- Which layer must enforce the tenant predicate?
- Would checking tenant only in the router be sufficient for background/service callers?

Acceptance: B cannot distinguish a real A case id from a nonexistent id through this endpoint.

## Lab 4 — two high-value approvers

Set a low threshold for convenience, then create an inspected case above it.

1. Finance A approves amount 60,000.
2. Finance A tries again under another idempotency key.
3. Finance B approves a different amount.
4. Finance B approves the same amount.

Prediction questions:

- After step 1, why should state still be `INSPECTED`?
- What prevents step 2?
- What prevents step 3?
- Which step creates the refund attempt/outbox event?

Acceptance: only step 4 completes the business approval.

## Lab 5 — provider rejects before processing

Set:

```text
RETURNOPS_PAYMENT_SIMULATION_MODE=503_before_processing
```

Prediction questions:

- Is the outcome known or unknown?
- Why is automatic retry allowed here?
- Does retry reuse or replace the provider idempotency key?
- What happens after the retry limit?

Acceptance: safe failures retry with backoff; exhaustion routes to reconciliation.

## Lab 6 — timeout after provider success

Set:

```text
RETURNOPS_PAYMENT_SIMULATION_MODE=timeout_after_processing
```

The fake provider persists a successful refund and then delays its response beyond the ReturnOps client timeout.

Before running it, answer:

- Is the refund failed?
- May the worker automatically issue another POST?
- What case state should be visible immediately after the timeout?
- What evidence can later resolve the state?

Acceptance: attempt becomes `UNKNOWN`, case becomes `REFUND_UNKNOWN`, and no automatic redispatch is queued.

Then use provider reconciliation. Because the fake provider persisted the refund, lookup should confirm success and transition the case to `REFUNDED`.

## Lab 7 — ACK lost and webhook arrives first

Use `timeout_after_processing` and let the fake provider webhook arrive while the HTTP client is still timing out.

Think about ordering:

```text
provider stores refund
provider schedules webhook
webhook marks attempt success
HTTP request times out
worker catches timeout
```

Questions:

- Can the worker overwrite `SUCCEEDED` with `UNKNOWN`?
- Does the current transaction/session ordering make this possible?
- What test would prove the desired rule?

This is intentionally a deeper exercise. If you discover an ordering bug, add a regression test before fixing it.

## Lab 8 — duplicate webhook

Set `duplicate_webhook`.

Questions:

- What database constraint provides dedupe?
- Why do we also compare the payload hash?
- What happens if a provider incorrectly reuses an event id for a changed payload?

Acceptance: duplicate identical event is replay-safe; changed payload is rejected.

## Lab 9 — worker crashes after provider success but before local commit

This failure is not fully instrumented as a built-in switch. Add a temporary test hook or monkeypatch.

Desired reasoning:

- Provider has executed the refund.
- Local transaction did not commit `SUCCEEDED` or outbox `done`.
- Lease eventually expires and worker sees the event again.
- Reusing the same provider idempotency key prevents a second logical provider refund.

Then ask whether the code classifies the second provider response correctly and whether the test proves it.

## Lab 10 — requirement change after one year

New rule:

```text
amount < 50000: one finance approval
amount >= 50000: two distinct finance approvals
```

Assume the old version had only one approval and there are already 100,000 rows.

Do not write code first. Design:

- migration order;
- interpretation of historical approvals;
- old API compatibility window;
- deployment order if old/new application versions overlap;
- rollback behavior;
- metrics/audit to detect unexpected paths.

Only after that ask AI to draft a migration.

## Lab 11 — tenant-scoping review

Search every `select(ReturnCase)`, `select(Approval)`, and `select(RefundAttempt)`.

Classify each query as:

- directly user/tenant scoped;
- derived from a tenant-scoped object;
- system-global by design;
- suspicious/unproven.

This exercise is about proving a property across a codebase rather than reading every line.

## Lab 12 — delete one test

Pick an invariant and temporarily delete the test you think proves it. Ask:

- Is there another independent test/evidence path?
- Was the original test actually proving the invariant or only the happy path?
- Could the implementation be wrong while all remaining tests stay green?

The goal is to learn that “test suite passes” and “property is proven” are different statements.
