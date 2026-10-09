import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

async function loginAsCustomerService(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByRole('button', { name: '进入工作台', exact: true }).click()
  await expect(page.getByRole('heading', { name: '业务总览', exact: true })).toBeVisible()
}

async function openOrder(page: Page, orderRef: string): Promise<void> {
  await page.getByRole('button', { name: '业务总览', exact: true }).click()
  await page.getByRole('row', { name: new RegExp(orderRef) }).click()
}

async function switchDemoRole(page: Page, role: string): Promise<void> {
  await page.getByRole('combobox', { name: '切换演示身份' }).selectOption(role)
  await expect(page.getByRole('heading', { name: '业务总览', exact: true })).toBeVisible()
}

test('customer service to warehouse to refund reconciliation reaches closed', async ({ page }) => {
  const suffix = `${Date.now()}`
  const orderRef = `DEMO-PLAYWRIGHT-${suffix}`
  await loginAsCustomerService(page)
  if (process.env.SAVE_DEMO_SCREENSHOTS === '1') {
    const screenshotDir = resolve(process.cwd(), '../docs/assets')
    mkdirSync(screenshotDir, { recursive: true })
    await page.screenshot({ path: resolve(screenshotDir, 'returnflow-overview.png'), fullPage: true })
  }

  await page.getByRole('button', { name: '＋ 新建申请', exact: true }).click()
  await page.getByLabel('订单编号', { exact: true }).fill(orderRef)
  await page.getByLabel('客户引用编号', { exact: true }).fill(`DEMO-CUSTOMER-${suffix}`)
  await page.getByLabel('申请退款金额（CNY）', { exact: true }).fill('145.67')
  await page.getByLabel('退货原因', { exact: true }).fill('Playwright 演示：虚构客户申请退货。')
  await page.getByRole('button', { name: '建立退货工单', exact: true }).click()
  await expect(page.getByText(orderRef, { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '通过客服审核', exact: true }).click()
  await page.getByLabel('审核说明（可选）', { exact: true }).fill('浏览器端客服审核通过。')
  await page.getByRole('button', { name: '确认操作', exact: true }).click()
  await expect(page.getByText('待仓库收货', { exact: true })).toBeVisible()

  await switchDemoRole(page, 'warehouse')
  await openOrder(page, orderRef)
  await page.getByRole('button', { name: '确认收货', exact: true }).click()
  await expect(page.getByRole('button', { name: '提交验货结果', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '提交验货结果', exact: true }).click()
  await page.getByLabel('验货结果', { exact: true }).fill('虚构演示验货：商品完好。')
  await page.getByRole('button', { name: '确认操作', exact: true }).click()
  await expect(page.getByText('待财务审批', { exact: true })).toBeVisible()

  await switchDemoRole(page, 'finance:0')
  await openOrder(page, orderRef)
  await page.getByRole('button', { name: '审批退款', exact: true }).click()
  await expect(page.getByLabel('批准金额（CNY）', { exact: true })).toHaveValue('145.67')
  await page.getByLabel('审批说明（可选）', { exact: true }).fill('浏览器端财务审批通过。')
  await page.getByRole('button', { name: '确认操作', exact: true }).click()

  await expect.poll(async () => {
    const statusCount = await page.getByText('已退款待对账', { exact: true }).count()
    if (statusCount) return statusCount
    await page.getByRole('button', { name: '↻ 重新加载', exact: true }).click()
    return page.getByText('已退款待对账', { exact: true }).count()
  }, { timeout: 20_000 }).toBeGreaterThan(0)

  await page.getByRole('button', { name: '确认对账完成', exact: true }).click()
  await expect(page.getByText('已对账待结案', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '结案', exact: true }).click()
  await expect(page.getByText('已结案', { exact: true })).toBeVisible()
  await expect(page.getByText('支付方证据', { exact: true })).toBeVisible()

  if (process.env.SAVE_DEMO_SCREENSHOTS === '1') {
    const screenshotDir = resolve(process.cwd(), '../docs/assets')
    mkdirSync(screenshotDir, { recursive: true })
    await page.screenshot({ path: resolve(screenshotDir, 'returnflow-closed-case.png'), fullPage: true })
  }
})

test('high-value refund requires a distinct finance approver', async ({ page }) => {
  const suffix = `${Date.now()}`
  const orderRef = `DEMO-HIGH-PLAYWRIGHT-${suffix}`
  await loginAsCustomerService(page)

  await page.getByRole('button', { name: '＋ 新建申请', exact: true }).click()
  await page.getByLabel('订单编号', { exact: true }).fill(orderRef)
  await page.getByLabel('客户引用编号', { exact: true }).fill(`DEMO-CUSTOMER-HIGH-${suffix}`)
  await page.getByLabel('申请退款金额（CNY）', { exact: true }).fill('700.00')
  await page.getByLabel('退货原因', { exact: true }).fill('高额退款双人审批演示。')
  await page.getByRole('button', { name: '建立退货工单', exact: true }).click()
  await page.getByRole('button', { name: '通过客服审核', exact: true }).click()
  await page.getByRole('button', { name: '确认操作', exact: true }).click()

  await switchDemoRole(page, 'warehouse')
  await openOrder(page, orderRef)
  await page.getByRole('button', { name: '确认收货', exact: true }).click()
  await page.getByRole('button', { name: '提交验货结果', exact: true }).click()
  await page.getByLabel('验货结果', { exact: true }).fill('高额样本验货通过。')
  await page.getByRole('button', { name: '确认操作', exact: true }).click()

  await switchDemoRole(page, 'finance:0')
  await openOrder(page, orderRef)
  await page.getByRole('button', { name: '审批退款', exact: true }).click()
  await page.getByLabel('批准金额（CNY）', { exact: true }).fill('600.00')
  await page.getByRole('button', { name: '确认操作', exact: true }).click()
  await expect(page.getByText('另一位财务人员审批', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: '审批退款', exact: true })).toHaveCount(0)

  await switchDemoRole(page, 'finance:1')
  await openOrder(page, orderRef)
  await page.getByRole('button', { name: '审批退款', exact: true }).click()
  await expect(page.getByLabel('批准金额（CNY）', { exact: true })).toHaveValue('600.00')
  if (process.env.SAVE_DEMO_SCREENSHOTS === '1') {
    const screenshotDir = resolve(process.cwd(), '../docs/assets')
    mkdirSync(screenshotDir, { recursive: true })
    await page.screenshot({ path: resolve(screenshotDir, 'returnflow-second-approver.png'), fullPage: true })
  }
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByText('待财务审批', { exact: true })).toBeVisible()
})

test('customer service cannot approve a refund through the UI or API', async ({ page }) => {
  const suffix = `${Date.now()}`
  const orderRef = `DEMO-PLAYWRIGHT-RBAC-${suffix}`
  await loginAsCustomerService(page)

  await page.getByRole('button', { name: '＋ 新建申请', exact: true }).click()
  await page.getByLabel('订单编号', { exact: true }).fill(orderRef)
  await page.getByLabel('客户引用编号', { exact: true }).fill(`DEMO-CUSTOMER-RBAC-${suffix}`)
  await page.getByLabel('申请退款金额（CNY）', { exact: true }).fill('80.00')
  await page.getByLabel('退货原因', { exact: true }).fill('Playwright RBAC 演示：合成申请。')
  await page.getByRole('button', { name: '建立退货工单', exact: true }).click()
  await page.getByRole('button', { name: '通过客服审核', exact: true }).click()
  await page.getByRole('button', { name: '确认操作', exact: true }).click()

  await switchDemoRole(page, 'warehouse')
  await openOrder(page, orderRef)
  await page.getByRole('button', { name: '确认收货', exact: true }).click()
  await page.getByRole('button', { name: '提交验货结果', exact: true }).click()
  await page.getByLabel('验货结果', { exact: true }).fill('RBAC 合成验货记录。')
  await page.getByRole('button', { name: '确认操作', exact: true }).click()

  await switchDemoRole(page, 'customer_service')
  await openOrder(page, orderRef)
  await expect(page.getByText('待财务审批', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '审批退款', exact: true })).toHaveCount(0)

  const forbidden = await page.evaluate(async (expectedOrderRef) => {
    const identityResponse = await fetch('/v1/demo/session', { credentials: 'include' })
    const identity = await identityResponse.json()
    const listResponse = await fetch(`/v1/returns?q=${encodeURIComponent(expectedOrderRef)}`, {
      headers: { 'X-Organization-ID': identity.organizationId },
      credentials: 'include',
    })
    const list = await listResponse.json()
    const target = list.items[0]
    const response = await fetch(`/v1/returns/${target.id}/approve-refund`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Organization-ID': identity.organizationId,
        'Idempotency-Key': `playwright-forbidden-${expectedOrderRef}`,
      },
      body: JSON.stringify({
        expected_version: target.version,
        approved_amount_minor: 8000,
        rationale: 'customer service must not approve refunds',
      }),
      credentials: 'include',
    })
    return { status: response.status, body: await response.json() }
  }, orderRef)
  expect(forbidden.status).toBe(403)
  await expect(page.getByText('待财务审批', { exact: true })).toBeVisible()
})

test('Finance resolves UNKNOWN from the provider without another refund dispatch', async ({ page }) => {
  test.skip(process.env.RUN_FAULT_E2E !== '1', 'create an UNKNOWN sample with the local fault-demo script first')
  const orderRef = process.env.RETURNFLOW_UNKNOWN_ORDER_REF ?? 'DEMO-ORDER-UNKNOWN-002'

  await loginAsCustomerService(page)
  await switchDemoRole(page, 'finance:1')
  await page.getByRole('button', { name: /^异常与对账(?:\s+\d+)?$/ }).click()
  await expect(page.getByRole('heading', { name: '异常与对账', exact: true })).toBeVisible()
  await page.getByRole('row', { name: new RegExp(orderRef) }).click()

  await expect(page.getByText('支付结果未知', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '查询支付方状态', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /重试|重新发起/ })).toHaveCount(0)
  await expect(page.getByText('执行 1 次', { exact: false })).toBeVisible()
  if (process.env.SAVE_DEMO_SCREENSHOTS === '1') {
    const screenshotDir = resolve(process.cwd(), '../docs/assets')
    mkdirSync(screenshotDir, { recursive: true })
    await page.screenshot({ path: resolve(screenshotDir, 'returnflow-unknown-before-reconcile.png'), fullPage: true })
  }

  await page.getByRole('button', { name: '查询支付方状态', exact: true }).click()
  await expect(page.getByText('已退款待对账', { exact: true })).toBeVisible()
  await expect(page.getByText('manual_provider_lookup', { exact: false }).first()).toBeVisible()
  await expect(page.getByText('执行 1 次', { exact: false })).toBeVisible()
  if (process.env.SAVE_DEMO_SCREENSHOTS === '1') {
    const screenshotDir = resolve(process.cwd(), '../docs/assets')
    mkdirSync(screenshotDir, { recursive: true })
    await page.screenshot({ path: resolve(screenshotDir, 'returnflow-unknown-recovered.png'), fullPage: true })
  }

  await page.getByRole('button', { name: '确认对账完成', exact: true }).click()
  await expect(page.getByText('已对账待结案', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '结案', exact: true }).click()
  await expect(page.getByText('已结案', { exact: true })).toBeVisible()
})
