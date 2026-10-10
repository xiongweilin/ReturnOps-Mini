import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = resolve(process.cwd(), '..')
const localDirectory = resolve(projectRoot, '.local')
const apiKey = readFileSync(resolve(localDirectory, 'n8n-api-key.txt'), 'utf8').trim()
const serviceToken = readFileSync(resolve(localDirectory, 'automation-token.txt'), 'utf8').trim()
const organizationId = readFileSync(resolve(localDirectory, 'organization-id.txt'), 'utf8').trim()
const intake = JSON.parse(readFileSync(resolve(localDirectory, 'n8n-intake-credentials.json'), 'utf8'))
const baseUrl = (process.env.N8N_BASE_URL ?? 'http://127.0.0.1:5678').replace(/\/+$/, '')
const base = new URL(baseUrl)

if (!['127.0.0.1', 'localhost', '::1'].includes(base.hostname)) {
  throw new Error('n8n workflow provisioning is restricted to a loopback URL.')
}
if (!apiKey || !serviceToken || !organizationId || !intake.user || !intake.password) {
  throw new Error('Local ReturnFlow/n8n bootstrap files are incomplete; rerun scripts/start-demo.ps1.')
}

const apiRoot = `${baseUrl}/api/v1`
const apiHeaders = {
  'X-N8N-API-KEY': apiKey,
  'Content-Type': 'application/json',
}

async function api(method, path, body) {
  const response = await fetch(`${apiRoot}${path}`, {
    method,
    headers: apiHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(20_000),
  })
  const result = await response.json().catch(() => null)
  if (!response.ok) {
    throw new Error(`n8n public API ${method} ${path} failed with HTTP ${response.status}; no credential values were logged.`)
  }
  return result
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().filter((key) => value[key] !== undefined).map((key) => [key, stable(value[key])]),
    )
  }
  return value
}

function workflowSignature(workflow) {
  const settingNames = ['executionOrder', 'saveDataErrorExecution', 'saveDataSuccessExecution']
  return JSON.stringify(stable({
    name: workflow.name,
    nodes: (workflow.nodes ?? []).map((node) => ({
      name: node.name,
      type: node.type,
      typeVersion: node.typeVersion,
      position: node.position,
      parameters: node.parameters,
      credentials: node.credentials ?? null,
      disabled: Boolean(node.disabled),
    })),
    connections: workflow.connections ?? {},
    settings: Object.fromEntries(settingNames.map((name) => [name, workflow.settings?.[name] ?? null])),
  }))
}

function attachCredentials(workflow, credentialIds) {
  const bindings = workflow.name === '01-return-intake'
    ? {
        'Return Intake Webhook': ['httpBasicAuth', 'ReturnFlow Intake Caller'],
        'Create Return in ReturnOps': ['httpCustomAuth', 'ReturnOps Demo API'],
      }
    : {
        'Read Current Operations Summary': ['httpCustomAuth', 'ReturnOps Demo API'],
        'Send Summary to Mailpit': ['smtp', 'Mailpit SMTP'],
      }

  for (const [nodeName, [type, credentialName]] of Object.entries(bindings)) {
    const node = workflow.nodes.find((candidate) => candidate.name === nodeName)
    const credentialId = credentialIds.get(credentialName)
    if (!node || !credentialId) throw new Error(`Could not bind the expected local credential to ${nodeName}.`)
    node.credentials = { [type]: { id: credentialId, name: credentialName } }
  }
  return workflow
}

async function ensureCredentials() {
  const listed = await api('GET', '/credentials?limit=100')
  const current = Array.isArray(listed?.data) ? listed.data : []
  const definitions = [
    {
      name: 'ReturnFlow Intake Caller',
      type: 'httpBasicAuth',
      data: { user: intake.user, password: intake.password },
    },
    {
      name: 'ReturnOps Demo API',
      type: 'httpCustomAuth',
      data: {
        json: JSON.stringify({
          headers: {
            Authorization: `Bearer ${serviceToken}`,
            'X-Organization-ID': organizationId,
          },
        }),
        allowedHttpRequestDomains: 'domains',
        allowedDomains: 'api',
      },
    },
    {
      name: 'Mailpit SMTP',
      type: 'smtp',
      data: {
        host: 'mailpit',
        port: 1025,
        secure: false,
        disableStartTls: false,
        user: '',
        password: '',
      },
    },
  ]
  const ids = new Map()

  for (const definition of definitions) {
    const matches = current.filter((credential) => credential.name === definition.name)
    if (matches.length > 1) {
      throw new Error(`Found ${matches.length} n8n credentials named ${definition.name}; remove duplicates in n8n and rerun.`)
    }

    let result
    if (matches.length === 0) {
      result = await api('POST', '/credentials', definition)
      console.log(`Created local n8n credential: ${definition.name}.`)
    } else {
      if (matches[0].type !== definition.type) {
        throw new Error(`The existing n8n credential ${definition.name} has an unexpected type; resolve it in n8n and rerun.`)
      }
      result = await api('PATCH', `/credentials/${matches[0].id}`, definition)
      console.log(`Verified local n8n credential: ${definition.name}.`)
    }
    if (!result?.id || result.name !== definition.name || result.type !== definition.type) {
      throw new Error(`n8n did not confirm credential ${definition.name}; no secret values were logged.`)
    }
    ids.set(definition.name, result.id)
  }

  return ids
}

async function ensureWorkflow(fileName, credentialIds) {
  const filePath = resolve(projectRoot, 'n8n', 'workflows', fileName)
  const source = JSON.parse(readFileSync(filePath, 'utf8'))
  const desired = attachCredentials(source, credentialIds)
  const payload = {
    name: desired.name,
    nodes: desired.nodes,
    connections: desired.connections,
    settings: desired.settings,
  }
  const listed = await api('GET', '/workflows?limit=100')
  const matches = (listed?.data ?? []).filter((workflow) => workflow.name === desired.name)
  if (matches.length > 1) {
    throw new Error(`Found multiple n8n workflows named ${desired.name}; remove duplicates in n8n and rerun.`)
  }

  let id
  let changed = false
  if (matches.length === 0) {
    const created = await api('POST', '/workflows', payload)
    id = created?.id
    changed = true
    console.log(`Created local n8n workflow: ${desired.name}.`)
  } else {
    id = matches[0].id
    const current = await api('GET', `/workflows/${id}`)
    if (workflowSignature(current) !== workflowSignature(desired)) {
      await api('PUT', `/workflows/${id}`, payload)
      changed = true
      console.log(`Updated local n8n workflow: ${desired.name}.`)
    }
  }

  if (!id) throw new Error(`n8n did not return an ID for ${desired.name}.`)
  let saved = await api('GET', `/workflows/${id}`)
  if (changed || !saved.active) {
    await api('POST', `/workflows/${id}/activate`, {})
    saved = await api('GET', `/workflows/${id}`)
  }
  if (!saved.active || workflowSignature(saved) !== workflowSignature(desired)) {
    throw new Error(`n8n did not confirm the expected published workflow ${desired.name}.`)
  }
  console.log(`Published and verified local n8n workflow: ${desired.name} (${id}).`)
}

const credentialIds = await ensureCredentials()
await ensureWorkflow('01-return-intake.json', credentialIds)
await ensureWorkflow('02-operations-digest.json', credentialIds)
console.log('n8n credentials and both published workflows are ready; the workflow token remains limited to the ReturnOps automation role.')
