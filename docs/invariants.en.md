# ReturnFlow correctness invariants

The authoritative implementation of state, permissions, evidence, and external effects lives in the backend and its tests; the assertions below must be verified against the actual code and runtime environment.

## 1. Tenants and permissions

- ReturnCase, Approval, and RefundAttempt belong to an explicit Organization.
- User queries must be isolated by organization; cross-tenant requests must not reveal whether the target object exists.
- UI-visible actions are not an authorization basis; server-side role, tenant, resource, version, and state checks are the actual gate.
- A high-value refund requires two different finance users to approve **the same amount**. The first approval must advance the version even if it does not change business state.

## 2. State machine and concurrency

- Business state follows explicit transitions; CLOSED and REJECTED are terminal.
- Updates involving shared business facts prevent races through version conditions and database constraints in the same transaction.
- When two requests make conflicting changes from the same old version, at most one may validly advance that version.
- Requested and approved amounts satisfy business constraints; amounts use a representation without floating-point error.

## 3. Idempotency and events

- Idempotency identity is scoped by (organization_id, scope, key).
- The same key with the same content may reuse an existing result; the same key with different content must report a conflict.
- Concurrent duplicate requests converge through measures such as persistent unique constraints and must not degrade into unexpected server errors.
- Webhook event identity is unique; consistent duplicate content can be handled safely, while the same identity with conflicting content must be rejected.

## 4. External refunds and read-back

- A planned action in the Outbox does not mean the external effect already happened.
- An HTTP timeout or lost ACK does not directly prove that a refund succeeded or failed.
- When an external effect may already have occurred, UNKNOWN does not permit reissuing the refund without evidence.
- A webhook or an authoritative provider query can supply refund evidence; late timeout handling must not overwrite an established SUCCEEDED.
- Payment evidence, refund business state, financial reconciliation, and final closing must remain separate.

## 5. Audit and evidence scope

- Important business transitions retain the actor, resource, action, and necessary audit information.
- Unit tests, SQLite API tests, PostgreSQL concurrency tests, simulated payment faults, browser tests, and local n8n runtime checks support different scopes of claims.
- Simulated provider results do not represent a production payment network or real financial compliance; passing tests do not imply that all external risks are covered.

For specific failure paths and acceptance conditions, see [failure scenarios](failure-lab.en.md); for runtime records, see [test evidence](TEST-EVIDENCE.en.md).
