# System invariants

This file is the human-owned correctness contract for ReturnOps Mini. AI-generated code may change implementation details, but a change to one of these rules must be explicit and accompanied by tests/migrations where applicable.

## 1. Tenant isolation

- Every return case, approval, refund attempt, idempotency record, and business audit event belongs to one organization.
- A normal business query is scoped by the current organization.
- A user may act only through a membership in the selected organization.
- A known object id from another tenant must not disclose whether that object exists; the business API returns not-found semantics.

Questions to ask:

- Does a new query include `organization_id`?
- Does a background worker derive tenant identity from persisted data instead of trusting caller input?
- Can an unscoped provider reference be used to cross tenant boundaries?

## 2. Legal state transitions

The state machine in `domain/states.py` is the single vocabulary for case transitions.

Normal path:

```text
requested -> authorized -> received -> inspected
          -> refund_approved -> refund_pending
          -> refunded -> reconciled -> closed
```

Exceptional paths:

```text
requested -> rejected
inspected -> rejected
refund_pending -> refund_unknown
refund_pending -> needs_reconciliation
refund_unknown -> refunded
refund_unknown -> needs_reconciliation
needs_reconciliation -> refunded
needs_reconciliation -> refund_pending   # explicit retry only after known failure
```

`closed` and `rejected` are terminal.

## 3. Optimistic concurrency

- Each return has a monotonically increasing integer `version`.
- User-driven mutations carry `expected_version`.
- The database update itself compares the old version/status; checking only in Python is not sufficient.
- A stale writer receives a version conflict and must reload.

Evidence required: real PostgreSQL concurrent transactions, not only sequential SQLite tests.

## 4. Refund amount

- Requested amount is strictly positive.
- Approved amount is strictly positive.
- Approved amount cannot exceed requested amount.
- A high-value second approval must approve the same amount as the first approval.

## 5. Approval independence

- High-value refund threshold is configuration.
- At/above the threshold, two distinct finance user ids are required.
- The first approval alone must not plan or dispatch a refund.
- A user cannot satisfy both approval slots by retrying or by changing idempotency keys.

## 6. One logical provider refund

- The training model permits one refund attempt per return case.
- A refund attempt has one stable provider idempotency key.
- Automatic retry after a provider-declared pre-processing failure reuses that key.
- Changing the provider idempotency key during a retry would violate this invariant.

## 7. Ambiguity is not failure

A timeout/network error after dispatch does not prove whether the provider executed the refund.

Therefore:

- ambiguous dispatch -> attempt `UNKNOWN`;
- case -> `REFUND_UNKNOWN`;
- the dispatch outbox item is considered handled;
- no automatic retry is scheduled;
- an authoritative provider lookup or webhook must resolve the ambiguity.

## 8. Known failure is different from unknown

A provider response that explicitly states the request was rejected before processing may be retried automatically up to the configured limit.

If safe retries are exhausted, the case enters `NEEDS_RECONCILIATION`.

If an authoritative lookup proves that an `UNKNOWN` idempotency key does not exist at the provider, the attempt becomes known `FAILED`, the case enters `NEEDS_RECONCILIATION`, and a finance user may explicitly retry.

## 9. Provider evidence controls `REFUNDED`

No human endpoint directly marks a case refunded.

Evidence sources currently accepted are:

- successful synchronous provider response;
- valid provider webhook;
- manual authoritative provider lookup.

The evidence source is written to the audit trail.

## 10. Webhook deduplication

- `(provider, event_id)` is unique.
- Same event id + same payload is replay-safe.
- Same event id + different payload is a conflict and must not be silently accepted.
- A duplicate success event must not cause a second business side effect.

## 11. Idempotent business writes

- Every mutating user-facing business endpoint requires `Idempotency-Key`.
- The uniqueness domain is organization + operation scope + key.
- Same key + same canonical request -> original response.
- Same key + different canonical request -> conflict.
- Concurrent same-key insert races must resolve through the database constraint and replay the winner, not leak a 500.

## 12. Outbox ownership

- Planning the refund attempt and creating the outbox event happen in the same database transaction as the state change.
- Workers claim events with a lease and `FOR UPDATE SKIP LOCKED` on PostgreSQL.
- Expired `processing` leases can be reclaimed.
- Known-safe failures can be rescheduled with backoff.
- Ambiguous provider results are not rescheduled.

## 13. Audit is evidence, not authority

Audit records explain important state/effect decisions but are not the source of current business state. A missing audit row is observability damage; it must not be used as a hidden way to authorize a state transition.

## 14. Migrations preserve meaning

Future schema changes must consider existing rows. Do not solve a changed requirement by deleting/recreating the database.

At minimum, CI must continue proving the migration chain can reach head. When a later migration changes existing data, add a fixture-at-old-version upgrade test.

## 15. Terminal closure

`CLOSED` means the refund has provider evidence, has been reconciled by finance, and requires no further workflow transition in this small product.

A later feature that needs reopening must introduce explicit semantics rather than silently adding `closed -> ...` transitions.
