import { chromium } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = resolve(process.cwd(), '..')
const localDirectory = resolve(projectRoot, '.local')
const owner = JSON.parse(readFileSync(resolve(localDirectory, 'n8n-demo-credentials.json'), 'utf8'))
const apiKey = readFileSync(resolve(localDirectory, 'n8n-api-key.txt'), 'utf8').trim()
const baseUrl = (process.env.N8N_BASE_URL ?? 'http://127.0.0.1:5678').replace(/\/+$/, '')
const mailpitBaseUrl = (process.env.MAILPIT_BASE_URL ?? 'http://127.0.0.1:8025').replace(/\/+$/, '')

for (const value of [baseUrl, mailpitBaseUrl]) {
  const host = new URL(value).hostname
  if (!['127.0.0.1', 'localhost', '::1'].includes(host)) {
    throw new Error('The local n8n digest check only accepts loopback n8n and Mailpit URLs.')
  }
}
if (!apiKey) throw new Error('Local n8n API key is missing; run scripts/start-demo.ps1 first.')

async function requestJson(url, options) {
  const response = await fetch(url, { ...options, signal: AbortSignal.timeout(10_000) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(`Local digest verification request failed with HTTP ${response.status}.`)
  return body
}

const workflows = await requestJson(`${baseUrl}/api/v1/workflows?limit=100`, {
  headers: { 'X-N8N-API-KEY': apiKey },
})
const digestMatches = (workflows.data ?? []).filter((workflow) => workflow.name === '02-operations-digest')
if (digestMatches.length !== 1) throw new Error('Expected exactly one published Operations Digest workflow.')
const workflow = digestMatches[0]
if (!workflow.active) throw new Error('Operations Digest workflow is not published.')

const before = await requestJson(`${mailpitBaseUrl}/api/v1/messages?limit=100`)
const previousMessageIds = new Set((before.messages ?? []).map((message) => message.ID))
const browser = await chromium.launch({ headless: true })

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.setDefaultTimeout(15_000)
  await page.goto(`${baseUrl}/signin`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(owner.email)
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill(owner.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL((url) => !url.pathname.includes('/signin'), { timeout: 20_000 })
  await page.goto(`${baseUrl}/workflow/${workflow.id}`, { waitUntil: 'domcontentloaded' })

  const executeButton = page.locator('[data-test-id="execute-workflow-button"]')
  await executeButton.waitFor({ state: 'visible' })
  const executionResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === `/rest/workflows/${workflow.id}/run`)
  await executeButton.click()
  const executionResponse = await executionResponsePromise
  if (!executionResponse.ok()) {
    throw new Error(`Manual Operations Digest execution failed with HTTP ${executionResponse.status()}.`)
  }

  const deadline = Date.now() + 30_000
  let deliveredMessage = null
  while (Date.now() < deadline) {
    const inbox = await requestJson(`${mailpitBaseUrl}/api/v1/messages?limit=100`)
    deliveredMessage = (inbox.messages ?? []).find((message) =>
      !previousMessageIds.has(message.ID)
      && message.Subject?.includes('ReturnFlow 每日售后待办摘要'))
    if (deliveredMessage) break
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 500))
  }
  if (!deliveredMessage) throw new Error('The manual digest execution did not deliver a new Mailpit message within 30 seconds.')

  const details = await requestJson(`${mailpitBaseUrl}/api/v1/message/${deliveredMessage.ID}`)
  const messageText = details.Text ?? ''
  const includedRoles = ['客服', '仓库', '财务'].filter((role) => messageText.includes(role))
  if (!messageText.includes('待处理工单') || includedRoles.length === 0) {
    throw new Error('Mailpit received a digest, but its body did not contain live ReturnOps role/todo data.')
  }

  console.log(JSON.stringify({
    workflow: workflow.name,
    manualExecutionStatus: executionResponse.status(),
    mailpitDelivered: true,
    subject: deliveredMessage.Subject,
    created: deliveredMessage.Created,
    includedRoleSections: includedRoles,
    bodyContainsPendingCases: messageText.includes('待处理工单'),
  }))
} finally {
  await browser.close()
}
