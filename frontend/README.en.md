# ReturnFlow frontend console

This directory contains ReturnFlow's React, TypeScript, and Vite business interface. Support, warehouse, finance, and admin users view real cases, role to-dos, approval records, refund evidence, and reconciliation state through the browser; the server API remains the sole authority for business state and authorization.

For the product overview, full architecture, and test boundaries, see the repository [README](../README.en.md), [demo steps](../docs/DEMO.en.md), and [architecture](../docs/ARCHITECTURE.en.md).

## Run the full demo stack

Start Compose from the repository root in Windows PowerShell 7:

```powershell
.\scripts\start-demo.ps1
```

Then open <http://127.0.0.1:4173>. Demo identities are issued by the API as short-lived HttpOnly cookies; do not store credentials in frontend source, persistent browser storage, or screenshots. For first-time n8n initialization, see [`n8n/README.en.md`](../n8n/README.en.md).

## Local development

```powershell
cd frontend
npm ci
npm run dev
```

Vite proxies `/v1` requests to `http://127.0.0.1:8000` by default. If the API uses another local address, override it with `RETURNOPS_API_PROXY`. A standalone dev server cannot replace the Compose integration demo; the database, Fake Payment, worker, and n8n are still provided by the root Compose project.

## Checks and browser tests

```powershell
npm run build
npm run lint
npm run e2e:typecheck
npm run test:e2e
```

End-to-end tests require a running local ReturnFlow Compose stack and Playwright Chromium; for the full fault-recovery flow and n8n Production webhook acceptance commands, see [`docs/DEMO.en.md`](../docs/DEMO.en.md) and [`n8n/README.en.md`](../n8n/README.en.md). These tests leave synthetic cases in the persistent demo database; see [`docs/TEST-EVIDENCE.en.md`](../docs/TEST-EVIDENCE.en.md) for the data boundary and reset steps.
