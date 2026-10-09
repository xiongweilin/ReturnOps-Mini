import { chromium } from '@playwright/test'
import { mkdirSync, readFileSync } from 'node:fs'
import { basename, resolve } from 'node:path'

const projectRoot = resolve(process.cwd(), '..')
const credentials = JSON.parse(readFileSync(resolve(projectRoot, '.local/n8n-demo-credentials.json'), 'utf8'))
const workflowPath = resolve(projectRoot, process.argv[2] ?? '')
const workflowName = basename(workflowPath, '.json')
const baseUrl = process.env.N8N_BASE_URL ?? 'http://127.0.0.1:5678'
const browser = await chromium.launch({ headless: true })

try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
  page.setDefaultTimeout(15_000)
  await page.goto(`${baseUrl}/signin`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(credentials.email)
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill(credentials.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.waitForURL((url) => !url.pathname.includes('/signin'), { timeout: 20_000 })
  await page.goto(`${baseUrl}/home/workflows`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(500)
  const createWorkflow = page.getByRole('button', { name: 'Create workflow', exact: true })
  if (await createWorkflow.isVisible().catch(() => false)) {
    await createWorkflow.click()
  } else {
    await page.getByText('Build a workflow', { exact: true }).click()
  }
  await page.getByRole('button', { name: 'More actions' }).first().click()
  await page.getByRole('menuitem', { name: 'Import', exact: true }).click()
  const chooseFile = page.waitForEvent('filechooser')
  await page.getByRole('menuitem', { name: 'From file', exact: true }).click()
  const chooser = await chooseFile
  await chooser.setFiles(workflowPath)
  await page.waitForTimeout(2_000)

  const assets = resolve(projectRoot, 'docs/assets')
  mkdirSync(assets, { recursive: true })
  await page.screenshot({ path: resolve(assets, `n8n-${workflowName}.png`), fullPage: true })
  const safeText = (await page.locator('body').innerText())
    .split(credentials.email).join('[redacted-email]')
    .split(credentials.password).join('[redacted-password]')
  console.log(`route=${new URL(page.url()).pathname}`)
  console.log(safeText.slice(0, 3_000))
} catch (error) {
  let message = error instanceof Error ? error.message : 'unknown error'
  message = message.split(credentials.email).join('[redacted-email]').split(credentials.password).join('[redacted-password]')
  console.error(`n8n UI workflow import failed. ${message}`)
  process.exitCode = 1
} finally {
  await browser.close()
}
