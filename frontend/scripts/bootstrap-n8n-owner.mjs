import { chromium } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = resolve(process.cwd(), '..')
const credentialsPath = resolve(projectRoot, '.local/n8n-demo-credentials.json')
const credentials = JSON.parse(readFileSync(credentialsPath, 'utf8'))
const baseUrl = process.env.N8N_BASE_URL ?? 'http://127.0.0.1:5678'
const browser = await chromium.launch({ headless: true })

try {
  const page = await browser.newPage()
  page.setDefaultTimeout(15_000)
  let setupStatus = 'not required'
  await page.goto(`${baseUrl}/setup`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(500)

  const setupEmail = page.getByRole('textbox', { name: 'Email *', exact: true })
  if (await setupEmail.isVisible().catch(() => false)) {
    setupStatus = 'pending'
    const captureSetupStatus = (response) => {
      if (response.url().includes('/rest/owner/setup')) setupStatus = response.status()
    }
    page.on('response', captureSetupStatus)
    await setupEmail.fill(credentials.email)
    await page.getByRole('textbox', { name: 'First Name *', exact: true }).fill(credentials.firstName)
    await page.getByRole('textbox', { name: 'Last Name *', exact: true }).fill(credentials.lastName)
    await page.getByRole('textbox', { name: 'Password *', exact: true }).fill(credentials.password)
    const updates = page.getByRole('checkbox', { name: 'I want to receive security and product updates' })
    if (await updates.isChecked().catch(() => false)) await updates.uncheck()
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await page.waitForTimeout(2500)
    page.off('response', captureSetupStatus)
    if (typeof setupStatus === 'number' && setupStatus >= 400) {
      throw new Error(`owner setup endpoint returned ${setupStatus}`)
    }
  }

  const signInEmail = page.getByRole('textbox', { name: 'Email', exact: true })
  if (await signInEmail.isVisible().catch(() => false)) {
    await signInEmail.fill(credentials.email)
    await page.getByRole('textbox', { name: 'Password', exact: true }).fill(credentials.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.waitForURL((url) => !url.pathname.includes('/signin'), { timeout: 20_000 })
  }

  const url = new URL(page.url())
  if (url.pathname === '/setup') {
    throw new Error('owner setup form did not complete')
  }
  console.log(`n8n local owner setup is ready (route: ${url.pathname}; setup response: ${setupStatus}).`)
} catch (error) {
  let message = error instanceof Error ? error.message : 'unknown error'
  message = message.split(credentials.email).join('[redacted-email]').split(credentials.password).join('[redacted-password]')
  console.error(`n8n owner setup failed; credential values were not logged. ${message}`)
  process.exitCode = 1
} finally {
  await browser.close()
}
