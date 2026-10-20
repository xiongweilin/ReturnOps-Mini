# ReturnFlow interview pitch

Suitable for a 4–5 minute portfolio presentation. Start with the business problem, then show the workflow and human handling; there is no need to introduce the underlying technology first.

## Opening: the business problem

ReturnFlow addresses the return-and-refund process of small and medium-sized e-commerce merchants. A request passes through support eligibility review, warehouse receipt and inspection, finance approval, then payment and reconciliation. Information is scattered across roles and tools, and duplicate entry creates duplicate cases; more seriously, a refund-request timeout does not mean the payment did not happen, and a direct retry can cause a duplicate refund.

I built this project to connect role handoffs and refund outcomes into an operable process while keeping every key decision with the business person responsible for it.

## Two n8n workflows

The first is **Return Intake**. After a customer return event reaches the webhook, the workflow validates and normalizes the request, then hands it to ReturnOps to create a case. When the same event is delivered again, the original case is returned; conflicting content or an invalid request is explicitly rejected, and no duplicate case is created.

The second is **Operations Digest**. It runs on a schedule or on demand, reads to-dos from current business records, organizes a summary by support, warehouse, and finance responsibility, and sends it to local Mailpit. It helps each role see what to handle next without approving anything on anyone's behalf.

## Human approval and role handoffs

The normal flow goes through support review, warehouse receipt and inspection, finance refund approval, and reconciliation. A high-value refund also requires a second finance user to approve the same amount. Administrators can view demo state but cannot bypass these business steps.

During the presentation, show how a to-do moves from one role to the next, then show that a high-value refund cannot continue before the second person approves. The point is that approval responsibility and process state line up, not which framework the approval page uses.

## Handling an unknown outcome

The key exception in the demo is: Fake Payment has stored the refund, but the response arrives after the client timeout. The system then shows "outcome unknown", keeps one dispatch record, and does not retry automatically. Finance queries the provider's authoritative record, confirms the refund outcome, and then completes reconciliation and closing.

This reflects a business rule: a timeout only means the system did not receive a reply in time; it does not prove that the payment failed. Establishing the facts first and then resuming the process avoids duplicate refunds.

## Demo sequence

1. Use the operations overview to explain current requests and role to-dos.
2. Show Intake receiving a request and a duplicate event still resolving to the same case.
3. Complete a normal refund through support, warehouse, and finance; then explain that a high-value refund needs a second finance user's approval.
4. Run the UNKNOWN scenario, showing the paused automatic retry, the provider query, reconciliation, and closing.
5. Show the Digest workflow and the Mailpit inbox result, explaining that the notification comes from real to-do data.

## Short answers for interview follow-ups

- **Why n8n?** To connect external events and notifications; business state, permissions, and refund approval still execute in the business system, so replaying a workflow cannot bypass approval.
- **How do you prevent duplicate refunds?** Duplicate requests are merged into the original case by the same event identifier; when the payment outcome is unknown, the system pauses and queries the provider's facts instead of blindly dispatching again.
- **What does this prove?** It proves that a synthetic business process in the repository can run repeatably and covers normal approval, duplicate intake, and recovery from an unknown refund outcome.
- **What does it not prove?** It has no real merchant, real payment, external email, or real customer trial data, so it does not claim to have saved hours or reduced error rates.

## Evidence and boundaries

The browser views, both n8n workflows, UNKNOWN recovery, and Mailpit digest all use synthetic data, local Fake Payment, and Mailpit. See [`TEST-EVIDENCE.en.md`](TEST-EVIDENCE.en.md) for runtime evidence and known boundaries, [`DEMO.en.md`](DEMO.en.md) for operating steps, and [`RECORDING.en.md`](RECORDING.en.md) for the video and timeline.
