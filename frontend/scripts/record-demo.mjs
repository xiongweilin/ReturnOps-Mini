import { chromium, expect } from '@playwright/test'
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = resolve(process.cwd(), '..')
const localDirectory = resolve(projectRoot, '.local')
const workDirectory = process.env.RETURNFLOW_VIDEO_WORK_DIR
if (!workDirectory) throw new Error('RETURNFLOW_VIDEO_WORK_DIR must point to an ignored local video-work directory.')

const owner = JSON.parse(readFileSync(resolve(localDirectory, 'n8n-demo-credentials.json'), 'utf8'))
const intakeCredentials = JSON.parse(readFileSync(resolve(localDirectory, 'n8n-intake-credentials.json'), 'utf8'))
const apiKey = readFileSync(resolve(localDirectory, 'n8n-api-key.txt'), 'utf8').trim()
const baseUrl = (process.env.RETURNFLOW_FRONTEND_URL ?? 'http://127.0.0.1:4173').replace(/\/+$/, '')
const n8nBaseUrl = (process.env.N8N_BASE_URL ?? 'http://127.0.0.1:5678').replace(/\/+$/, '')
const mailpitBaseUrl = (process.env.MAILPIT_BASE_URL ?? 'http://127.0.0.1:8025').replace(/\/+$/, '')
const unknownOrderRef = process.env.RETURNFLOW_UNKNOWN_ORDER_REF ?? ''
const postRollMs = Number.parseInt(process.env.RETURNFLOW_VIDEO_POST_ROLL_MS ?? '3500', 10)
const videoSize = { width: 1600, height: 900 }

for (const value of [baseUrl, n8nBaseUrl, mailpitBaseUrl]) {
  const host = new URL(value).hostname
  if (!['127.0.0.1', 'localhost', '::1'].includes(host)) {
    throw new Error('The public demo recording only accepts local loopback service URLs.')
  }
}
if (!apiKey || !intakeCredentials.user || !intakeCredentials.password || !unknownOrderRef) {
  throw new Error('Local demo video credentials or the UNKNOWN scenario reference are missing.')
}
if (!Number.isFinite(postRollMs) || postRollMs < 0 || postRollMs > 15_000) {
  throw new Error('RETURNFLOW_VIDEO_POST_ROLL_MS must be between 0 and 15000.')
}

mkdirSync(workDirectory, { recursive: true })
const manifestPath = resolve(workDirectory, 'narration-manifest.json')
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
const scenes = new Map(manifest.scenes.map((scene) => [scene.id, scene]))
for (const scene of scenes.values()) {
  if (!Number.isInteger(scene.durationMs) || scene.durationMs <= 0) {
    throw new Error(`Narration duration is missing for scene ${scene.id}.`)
  }
}

async function publicApi(path) {
  const response = await fetch(`${n8nBaseUrl}/api/v1${path}`, {
    headers: { 'X-N8N-API-KEY': apiKey },
    signal: AbortSignal.timeout(15_000),
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(`Local n8n lookup failed with HTTP ${response.status}.`)
  return body
}

async function mailpitApi(path) {
  const response = await fetch(`${mailpitBaseUrl}/api/v1${path}`, { signal: AbortSignal.timeout(10_000) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(`Local Mailpit lookup failed with HTTP ${response.status}.`)
  return body
}

const workflowList = await publicApi('/workflows?limit=100')
const intakeMatches = (workflowList.data ?? []).filter((workflow) => workflow.name === '01-return-intake')
const digestMatches = (workflowList.data ?? []).filter((workflow) => workflow.name === '02-operations-digest')
if (intakeMatches.length !== 1 || digestMatches.length !== 1 || !intakeMatches[0].active || !digestMatches[0].active) {
  throw new Error('Both n8n workflows must be uniquely published before recording.')
}

const suffix = `${Date.now()}`
const orderRef = `DEMO-VIDEO-${suffix}`
const highValueOrderRef = `DEMO-VIDEO-HIGH-${suffix}`
const customerRef = `DEMO-CUSTOMER-VIDEO-${suffix}`
const intakeUrl = `${n8nBaseUrl}/webhook/return-intake`
const authHeader = `Basic ${Buffer.from(`${intakeCredentials.user}:${intakeCredentials.password}`).toString('base64')}`

const browser = await chromium.launch({ headless: true })
let recordingContext
let rawVideoPath
const timeline = []
let elapsedMs = 0

async function loginOwnerForRecording() {
  const context = await browser.newContext()
  const page = await context.newPage()
  page.setDefaultTimeout(15_000)
  await page.goto(`${n8nBaseUrl}/signin`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(owner.email)
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill(owner.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL((url) => !url.pathname.includes('/signin'), { timeout: 20_000 })
  const state = await context.storageState()
  await context.close()
  return state
}

async function runScene(page, sceneId, action) {
  const scene = scenes.get(sceneId)
  if (!scene) throw new Error(`Missing narration scene ${sceneId}.`)
  const actionStartedAt = Date.now()
  await action()
  const actionDurationMs = Date.now() - actionStartedAt
  const narrationStartMs = elapsedMs + actionDurationMs
  await page.waitForTimeout(scene.durationMs + postRollMs)
  const entry = {
    id: scene.id,
    caption: scene.caption,
    actionStartMs: elapsedMs,
    actionDurationMs,
    narrationStartMs,
    narrationDurationMs: scene.durationMs,
    postRollMs,
  }
  timeline.push(entry)
  elapsedMs = narrationStartMs + scene.durationMs + postRollMs
  console.log(`Recorded chapter ${scene.id} (${Math.round((elapsedMs - entry.actionStartMs) / 1000)}s).`)
}

async function createIntakeCase() {
  const event = {
    event_id: `returnflow-video-${suffix}`,
    external_order_ref: orderRef,
    customer_ref: customerRef,
    reason: '虚构演示退货事件：商品完好。',
    requested_amount_minor: 14567,
    currency: 'CNY',
  }
  const response = await fetch(intakeUrl, {
    method: 'POST',
    headers: { Authorization: authHeader, 'Content-Type': 'application/json' },
    body: JSON.stringify(event),
    signal: AbortSignal.timeout(20_000),
  })
  const body = await response.json().catch(() => null)
  if (response.status !== 201 || body?.accepted !== true || body.status !== 'requested') {
    throw new Error(`The local n8n Production Webhook did not create the synthetic video case (HTTP ${response.status}).`)
  }
  console.log(`Created synthetic video case ${body.caseRef} from the production webhook.`)
  return body
}

async function loginAsCustomerService(page) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: '进入工作台', exact: true }).click()
  await expect(page.getByRole('heading', { name: '业务总览', exact: true })).toBeVisible()
}

async function openOrder(page, reference) {
  await page.getByRole('button', { name: '业务总览', exact: true }).click()
  await page.getByRole('row', { name: new RegExp(reference) }).click()
}

async function switchDemoRole(page, role) {
  await page.getByRole('combobox', { name: '切换演示身份' }).selectOption(role)
  await expect(page.getByRole('heading', { name: '业务总览', exact: true })).toBeVisible()
}

async function waitForMailpitMessage(previousIds) {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    const inbox = await mailpitApi('/messages?limit=100')
    const found = (inbox.messages ?? []).find((message) =>
      !previousIds.has(message.ID)
      && message.Subject?.includes('ReturnFlow 每日售后待办摘要'))
    if (found) return found
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 500))
  }
  throw new Error('The manual Digest did not arrive in local Mailpit within 30 seconds.')
}

try {
  const storageState = await loginOwnerForRecording()
  recordingContext = await browser.newContext({
    viewport: videoSize,
    recordVideo: { dir: workDirectory, size: videoSize },
    storageState,
  })
  const page = await recordingContext.newPage()
  page.setDefaultTimeout(15_000)
  const video = page.video()

  await runScene(page, 'overview', async () => {
    await loginAsCustomerService(page)
    await expect(page.getByText('待客服审核', { exact: true }).first()).toBeVisible()
  })

  await runScene(page, 'intake-workflow', async () => {
    await page.goto(`${n8nBaseUrl}/workflow/${intakeMatches[0].id}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Return Intake Webhook', { exact: true })).toBeVisible()
    await expect(page.getByText('Create Return in ReturnOps', { exact: true })).toBeVisible()
    await expect(page.getByText('Published', { exact: true })).toBeVisible()
  })

  await runScene(page, 'webhook-case', async () => {
    await createIntakeCase()
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: '业务总览', exact: true })).toBeVisible()
    await openOrder(page, orderRef)
    await expect(page.getByText(orderRef, { exact: true })).toBeVisible()
    await expect(page.getByText('待客服审核', { exact: true })).toBeVisible()
  })

  await runScene(page, 'customer-warehouse', async () => {
    await page.getByRole('button', { name: '通过客服审核', exact: true }).click()
    await page.getByLabel('审核说明（可选）', { exact: true }).fill('录屏演示：客服确认虚构退货资格。')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await expect(page.getByText('待仓库收货', { exact: true })).toBeVisible()

    await switchDemoRole(page, 'warehouse')
    await openOrder(page, orderRef)
    await page.getByRole('button', { name: '确认收货', exact: true }).click()
    await page.getByRole('button', { name: '提交验货结果', exact: true }).click()
    await page.getByLabel('验货结果', { exact: true }).fill('录屏演示：虚构商品外观完好。')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await expect(page.getByText('待财务审批', { exact: true })).toBeVisible()
  })

  await runScene(page, 'finance-close', async () => {
    await switchDemoRole(page, 'finance:0')
    await openOrder(page, orderRef)
    await page.getByRole('button', { name: '审批退款', exact: true }).click()
    await expect(page.getByLabel('批准金额（CNY）', { exact: true })).toHaveValue('145.67')
    await page.getByLabel('审批说明（可选）', { exact: true }).fill('录屏演示：财务审批虚构退款。')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()

    await expect.poll(async () => {
      const count = await page.getByText('已退款待对账', { exact: true }).count()
      if (count) return count
      await page.getByRole('button', { name: '↻ 重新加载', exact: true }).click()
      return page.getByText('已退款待对账', { exact: true }).count()
    }, { timeout: 20_000 }).toBeGreaterThan(0)
    await page.getByRole('button', { name: '确认对账完成', exact: true }).click()
    await expect(page.getByText('已对账待结案', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '结案', exact: true }).click()
    await expect(page.getByText('已结案', { exact: true })).toBeVisible()
    await expect(page.getByText('支付方证据', { exact: true })).toBeVisible()
  })

  await runScene(page, 'four-eyes', async () => {
    await switchDemoRole(page, 'customer_service')
    await page.getByRole('button', { name: '＋ 新建申请', exact: true }).click()
    await page.getByLabel('订单编号', { exact: true }).fill(highValueOrderRef)
    await page.getByLabel('客户引用编号', { exact: true }).fill(`DEMO-CUSTOMER-HIGH-${suffix}`)
    await page.getByLabel('申请退款金额（CNY）', { exact: true }).fill('700.00')
    await page.getByLabel('退货原因', { exact: true }).fill('录屏演示：高额退款双人复核。')
    await page.getByRole('button', { name: '建立退货工单', exact: true }).click()
    await expect(page.getByText(highValueOrderRef, { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '通过客服审核', exact: true }).click()
    await page.getByRole('button', { name: '确认操作', exact: true }).click()

    await switchDemoRole(page, 'warehouse')
    await openOrder(page, highValueOrderRef)
    await page.getByRole('button', { name: '确认收货', exact: true }).click()
    await page.getByRole('button', { name: '提交验货结果', exact: true }).click()
    await page.getByLabel('验货结果', { exact: true }).fill('录屏演示：高额样本验货通过。')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()

    await switchDemoRole(page, 'finance:0')
    await openOrder(page, highValueOrderRef)
    await page.getByRole('button', { name: '审批退款', exact: true }).click()
    await page.getByLabel('批准金额（CNY）', { exact: true }).fill('600.00')
    await page.getByLabel('审批说明（可选）', { exact: true }).fill('录屏演示：第一位财务部分审批。')
    await page.getByRole('button', { name: '确认操作', exact: true }).click()
    await expect(page.getByText('另一位财务人员审批', { exact: false })).toBeVisible()
    await expect(page.getByRole('button', { name: '审批退款', exact: true })).toHaveCount(0)

    await switchDemoRole(page, 'finance:1')
    await openOrder(page, highValueOrderRef)
    await page.getByRole('button', { name: '审批退款', exact: true }).click()
    await expect(page.getByLabel('批准金额（CNY）', { exact: true })).toHaveValue('600.00')
  })

  await runScene(page, 'unknown-pause', async () => {
    const cancelButton = page.getByRole('button', { name: '取消', exact: true })
    if (await cancelButton.count()) await cancelButton.click()
    await switchDemoRole(page, 'finance:1')
    await page.getByRole('button', { name: /^异常与对账(?:\s+\d+)?$/ }).click()
    await expect(page.getByRole('heading', { name: '异常与对账', exact: true })).toBeVisible()
    await page.getByRole('row', { name: new RegExp(unknownOrderRef) }).click()
    await expect(page.getByText('支付结果未知', { exact: true })).toBeVisible()
    await expect(page.getByText('执行 1 次', { exact: false })).toBeVisible()
    await expect(page.getByRole('button', { name: '查询支付方状态', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /重试|重新发起/ })).toHaveCount(0)
  })

  await runScene(page, 'unknown-reconcile', async () => {
    await page.getByRole('button', { name: '查询支付方状态', exact: true }).click()
    await expect(page.getByText('已退款待对账', { exact: true })).toBeVisible()
    await expect(page.getByText('manual_provider_lookup', { exact: false }).first()).toBeVisible()
    await expect(page.getByText('执行 1 次', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: '确认对账完成', exact: true }).click()
    await expect(page.getByText('已对账待结案', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '结案', exact: true }).click()
    await expect(page.getByText('已结案', { exact: true })).toBeVisible()
  })

  let digestMessage
  await runScene(page, 'digest-workflow', async () => {
    const previousInbox = await mailpitApi('/messages?limit=100')
    const previousIds = new Set((previousInbox.messages ?? []).map((message) => message.ID))
    await page.goto(`${n8nBaseUrl}/workflow/${digestMatches[0].id}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Read Current Operations Summary', { exact: true })).toBeVisible()
    await expect(page.getByText('Send Summary to Mailpit', { exact: true })).toBeVisible()
    const responsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === `/rest/workflows/${digestMatches[0].id}/run`)
    await page.locator('[data-test-id="execute-workflow-button"]').click()
    const execution = await responsePromise
    if (!execution.ok()) throw new Error(`Manual local Digest execution failed with HTTP ${execution.status()}.`)
    digestMessage = await waitForMailpitMessage(previousIds)
  })

  await runScene(page, 'digest-mailpit', async () => {
    await page.goto(mailpitBaseUrl, { waitUntil: 'domcontentloaded' })
    const messageLink = page.locator('a').filter({ hasText: 'ReturnFlow 每日售后待办摘要' }).first()
    await messageLink.click()
    await expect(page.getByText('待处理工单', { exact: false })).toBeVisible()
    await expect(page.getByText('待客服处理', { exact: false })).toBeVisible()
    await expect(page.getByText('待仓库处理', { exact: false })).toBeVisible()
    await expect(page.getByText('待财务审批', { exact: false })).toBeVisible()
  })

  await runScene(page, 'architecture-close', async () => {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: '业务总览', exact: true })).toBeVisible()
  })

  await recordingContext.close()
  const savedVideoPath = await video.path()
  rawVideoPath = resolve(workDirectory, 'returnflow-demo-raw.webm')
  copyFileSync(savedVideoPath, rawVideoPath)
  const timelineResult = {
    videoSize,
    durationMs: elapsedMs,
    postRollMs,
    orderRef,
    highValueOrderRef,
    unknownOrderRef,
    intakeWorkflowId: intakeMatches[0].id,
    digestWorkflowId: digestMatches[0].id,
    digestMessage: digestMessage ? { subject: digestMessage.Subject, created: digestMessage.Created } : null,
    scenes: timeline,
  }
  writeFileSync(resolve(workDirectory, 'timeline.json'), `${JSON.stringify(timelineResult, null, 2)}\n`, 'utf8')
  console.log(JSON.stringify({
    chapters: timeline.map((entry) => entry.id),
    durationSeconds: Math.round(elapsedMs / 1000),
    syntheticOrderRef: orderRef,
    syntheticHighValueOrderRef: highValueOrderRef,
    unknownOrderRef,
    digestSubject: digestMessage?.Subject,
    rawVideo: rawVideoPath,
  }))
} finally {
  if (recordingContext) await recordingContext.close().catch(() => {})
  await browser.close()
}
