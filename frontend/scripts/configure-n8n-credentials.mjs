import { chromium } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = resolve(process.cwd(), '..')
const owner = JSON.parse(readFileSync(resolve(projectRoot, '.local/n8n-demo-credentials.json'), 'utf8'))
const intake = JSON.parse(readFileSync(resolve(projectRoot, '.local/n8n-intake-credentials.json'), 'utf8'))
const serviceToken = readFileSync(resolve(projectRoot, '.local/automation-token.txt'), 'utf8').trim()
const organizationId = process.env.RETURNOPS_ORGANIZATION_ID
const baseUrl = process.env.N8N_BASE_URL ?? 'http://127.0.0.1:5678'
if (!serviceToken || !organizationId) throw new Error('local automation credential or organization id is missing')

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage()
page.setDefaultTimeout(15_000)

async function login() {
  await page.goto(`${baseUrl}/signin`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(owner.email)
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill(owner.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL((url) => !url.pathname.includes('/signin'), { timeout: 20_000 })
}

async function selectCredentialType(type, name) {
  await page.goto(`${baseUrl}/home/credentials`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(750)
  if (await page.getByText(name, { exact: true }).count()) return false
  await page.getByRole('button', { name: 'Create credential', exact: true }).first().click()
  await page.getByRole('option', { name: type, exact: true }).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  const inlineName = page.locator('[data-test-id="inline-edit-preview"]')
  await inlineName.click()
  const nameInput = page.getByRole('textbox', { name: 'editable input', exact: true })
  await nameInput.fill(name)
  await nameInput.press('Enter')
  return true
}

async function saveCredential(name) {
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await page.locator('[data-test-id="inline-edit-preview"]').waitFor({ state: 'visible', timeout: 15_000 })
  await page.waitForTimeout(500)
  await page.goto(`${baseUrl}/home/credentials`, { waitUntil: 'domcontentloaded' })
  await page.getByText(name, { exact: true }).first().waitFor({ state: 'visible', timeout: 10_000 })
}

try {
  await login()

  if (await selectCredentialType('Custom Auth', 'ReturnOps Demo API')) {
    const domainSelect = page.getByRole('combobox', { name: 'Select', exact: true })
    await domainSelect.click()
    await page.getByRole('option', { name: /Specific Domains/ }).click()
    await page.getByPlaceholder('example.com, *.subdomain.com').fill('api')
    const customAuth = JSON.stringify({
      headers: {
        Authorization: `Bearer ${serviceToken}`,
        'X-Organization-ID': organizationId,
      },
    })
    await page.getByRole('dialog').getByRole('textbox').first().fill(customAuth)
    await saveCredential('ReturnOps Demo API')
  }
  console.log('ReturnOps Custom Auth credential is configured with the HTTP domain restricted to api.')

  if (await selectCredentialType('Basic Auth', 'ReturnFlow Intake Caller')) {
    const fields = page.getByRole('dialog').getByRole('textbox')
    await fields.nth(0).fill(intake.user)
    await fields.nth(1).fill(intake.password)
    const basicAuthDomain = page.getByRole('combobox', { name: 'Select', exact: true })
    await basicAuthDomain.click()
    await page.getByRole('option', { name: /^None/ }).click()
    await saveCredential('ReturnFlow Intake Caller')
  }
  console.log('Created inbound Return Intake Basic Auth credential.')

  if (await selectCredentialType('SMTP', 'Mailpit SMTP')) {
    const smtpFields = page.getByRole('dialog').getByRole('textbox')
    await smtpFields.nth(2).fill('mailpit')
    await page.getByRole('spinbutton').fill('1025')
    const ssl = page.getByRole('dialog').getByRole('switch').first()
    if (await ssl.isChecked()) {
      await ssl.locator('..').click()
      if (await ssl.isChecked()) throw new Error('SMTP SSL/TLS toggle did not turn off')
    }
    await saveCredential('Mailpit SMTP')
  }
  console.log('Created unauthenticated local Mailpit SMTP credential (mailpit:1025, TLS off).')
} catch (error) {
  let message = error instanceof Error ? error.message : 'unknown error'
  for (const secret of [owner.email, owner.password, intake.password, serviceToken]) {
    if (secret) message = message.split(secret).join('[redacted]')
  }
  console.error(`n8n credential configuration failed; secrets were not logged. ${message}`)
  process.exitCode = 1
} finally {
  await browser.close()
}
