# Failure scenarios and acceptance boundaries

The following reproducible failure scenarios define expected invariants and the evidence that should be obtained. Execution entry points and historical results are in [faultlab](../faultlab/README.en.md), [test evidence](TEST-EVIDENCE.en.md), and the relevant integration tests. Scenarios that have not actually been executed remain acceptance requirements awaiting verification.

| Scenario | Behavior that must hold | Proportionate evidence |
| --- | --- | --- |
| Concurrent modification of a Case from the same old version | Conflicting transitions from the same version must not both commit | PostgreSQL concurrency test and version-update results |
| Concurrent submission with the same Idempotency-Key | Identical requests converge to one effect; conflicting content is rejected | Database uniqueness constraints, responses, and persisted records |
| Using a real Case ID across tenants | Other tenants' objects are neither exposed nor modified | API/service tests with different tenant identities |
| Concurrent first approvals for a high-value refund | Two mutually non-exclusive first approvals cannot remain | Concurrency checks on persisted approvals and Case version |
| Provider fails explicitly before execution | Treated as a proven failure, not confused with UNKNOWN | Controlled 503-before-processing fault scenario |
| Provider refunded but ACK was lost | Enter an uncertain state; do not blindly POST again | timeout-after-processing and provider query |
| Webhook succeeds first, timeout callback arrives later | An established success is not downgraded by a late callback | Out-of-order callback regression test |
| Same Webhook replayed / conflicting content | Consistent replay is idempotent; conflicting content for the same event ID is rejected | Webhook unique key and payload validation |
| Worker terminates after the external effect but before local commit | Recovery does not create a duplicate uncontrolled external refund | Stable provider intent, restart, and reconciliation |
| Future business-rule and schema changes | History, rule versions, and migration results remain traceable | Claim only after concrete migration / rollback acceptance |

Fault injection changes only the isolated demo environment and must not reach real payment services or customer data. Do not describe "no error observed" as proof that a dangerous path does not exist. Verifiable runtime results and unverified acceptance requirements must be recorded separately.
