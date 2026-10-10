import { chromium } from '@playwright/test'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = resolve(process.cwd(), '..')
const localDirectory = resolve(projectRoot, '.local')
const ownerPath = resolve(localDirectory, 'n8n-demo-credentials.json')
const apiKeyPath = resolve(localDirectory, 'n8n-api-key.txt')
const owner = JSON.parse(readFileSync(ownerPath, 'utf8'))
const baseUrl = (process.env.N8N_BASE_URL ?? 'http://127.0.0.1:5678').replace(/\/+$/, '')
const base = new URL(baseUrl)

if (!['127.0.0.1', 'localhost', '::1'].includes(base.hostname)) {
  throw new Error('n8n bootstrap is restricted to a loopback URL.')
}

async function isUsable(apiKey) {
  if (!apiKey) return false
  try {
    const response = await fetch(`${baseUrl}/api/v1/workflows?limit=1`, {
      headers: { 'X-N8N-API-KEY': apiKey },
      signal: AbortSignal.timeout(5_000),
    })
    return response.ok
  } catch {
    return false
  }
}

const savedKey = existsSync(apiKeyPath) ? readFileSync(apiKeyPath, 'utf8').trim() : ''
if (await isUsable(savedKey)) {
  console.log('Existing local n8n API key is valid; no key was regenerated.')
  process.exit(0)
}

mkdirSync(localDirectory, { recursive: true })
const browser = await chromium.launch({ headless: true })

try {
  const page = await browser.newPage()
  page.setDefaultTimeout(15_000)
  await page.goto(`${baseUrl}/signin`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(owner.email)
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill(owner.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL((url) => !url.pathname.includes('/signin'), { timeout: 20_000 })

  await page.goto(`${baseUrl}/settings/api`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Create API key', exact: true }).click()
  const dialog = page.locator('[role="dialog"]').filter({ hasText: 'Create API Key' })
  await dialog.locator('[data-test-id="api-key-label"]').fill('ReturnFlow local bootstrap')
  await dialog.getByPlaceholder('Select').click()
  await page.getByRole('option', { name: '90 days', exact: true }).click()

  const keyResponsePromise = page.waitForResponse((response) => {
    const request = response.request()
    return request.method() === 'POST'
      && new URL(response.url()).pathname === '/rest/api-keys'
      && response.ok()
  })
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  const keyResponse = await keyResponsePromise
  const responseBody = await keyResponse.json()
  const apiKey = responseBody?.data?.rawApiKey
  if (typeof apiKey !== 'string' || apiKey.length < 100) {
    throw new Error('n8n did not return a usable local API key; the key value was not logged.')
  }

  if (!await isUsable(apiKey)) {
    throw new Error('The new local n8n API key was not accepted by the public API.')
  }

  writeFileSync(apiKeyPath, `${apiKey}\n`, { encoding: 'utf8', mode: 0o600 })
  console.log('Created and verified a 90-day local n8n API key in ignored .local/n8n-api-key.txt.')
} catch (error) {
  let message = error instanceof Error ? error.message : 'unknown error'
  for (const secret of [owner.email, owner.password, savedKey]) {
    if (secret) message = message.split(secret).join('[redacted]')
  }
  console.error(`n8n API key bootstrap failed; owner credentials and key material were not logged. ${message}`)
  process.exitCode = 1
} finally {
  await browser.close()
}
