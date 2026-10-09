import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

if (process.env.RUN_N8N_INTEGRATION !== '1') {
  throw new Error('Set RUN_N8N_INTEGRATION=1 to explicitly run the local n8n integration check.')
}

const webhookUrl = new URL(process.env.N8N_WEBHOOK_URL ?? 'http://127.0.0.1:5678/webhook/return-intake')
if (!['127.0.0.1', 'localhost', '::1'].includes(webhookUrl.hostname)) {
  throw new Error('This integration check only accepts a loopback n8n webhook URL.')
}

const credentialPath = resolve(process.cwd(), '../.local/n8n-intake-credentials.json')
const credentials = JSON.parse(readFileSync(credentialPath, 'utf8'))
if (!credentials.user || !credentials.password) {
  throw new Error('Local n8n Intake credentials are incomplete; run scripts/bootstrap-n8n-demo.ps1 first.')
}

const authHeader = `Basic ${Buffer.from(`${credentials.user}:${credentials.password}`).toString('base64')}`
const event = {
  event_id: 'returnflow-n8n-runtime-v1',
  external_order_ref: 'DEMO-ORDER-N8N-RUNTIME-001',
  customer_ref: 'DEMO-CUSTOMER-N8N-RUNTIME-001',
  reason: 'Synthetic n8n integration verification.',
  requested_amount_minor: 12900,
  currency: 'CNY',
}

async function send(body, { authenticate = true } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (authenticate) headers.Authorization = authHeader
  const response = await fetch(webhookUrl, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(20_000),
  })
  const payload = await response.json().catch(() => null)
  return { status: response.status, payload }
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const unauthorized = await send(event, { authenticate: false })
assert(unauthorized.status === 401, `Expected unauthenticated webhook to return 401; got ${unauthorized.status}.`)

const invalid = await send({ ...event, event_id: 'returnflow-n8n-invalid-v1', requested_amount_minor: 0 })
assert(invalid.status === 400, `Expected invalid intake to return 400; got ${invalid.status}.`)
assert(invalid.payload?.accepted === false, 'Invalid intake response must not claim success.')

const first = await send(event)
assert(first.status === 201, `Expected valid intake to return 201; got ${first.status}.`)
assert(first.payload?.accepted === true, 'Valid intake response must be accepted.')
assert(typeof first.payload?.caseId === 'string', 'Valid intake must include the ReturnOps case id.')
assert(typeof first.payload?.caseRef === 'string', 'Valid intake must include the ReturnOps case reference.')
assert(first.payload?.status === 'requested', 'A new intake must remain in requested state.')

const duplicate = await send(event)
assert(duplicate.status === 201, `Expected idempotent replay to return 201; got ${duplicate.status}.`)
assert(duplicate.payload?.accepted === true && duplicate.payload?.replayed === true, 'Duplicate intake must be marked as replayed.')
assert(duplicate.payload?.caseId === first.payload.caseId, 'Duplicate intake must return the same case id.')
assert(duplicate.payload?.caseRef === first.payload.caseRef, 'Duplicate intake must return the same case reference.')

const conflict = await send({ ...event, reason: 'Changed payload must conflict for the same event id.' })
assert(conflict.status === 409, `Expected changed payload to return 409; got ${conflict.status}.`)
assert(conflict.payload?.accepted === false, 'Conflicting intake response must not claim success.')

console.log(JSON.stringify({
  unauthorizedStatus: unauthorized.status,
  invalidStatus: invalid.status,
  createdStatus: first.status,
  caseRef: first.payload.caseRef,
  duplicateStatus: duplicate.status,
  duplicateReplayed: duplicate.payload.replayed,
  sameCase: duplicate.payload.caseId === first.payload.caseId,
  conflictStatus: conflict.status,
}))
