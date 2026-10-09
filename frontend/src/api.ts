export type Role = 'customer_service' | 'warehouse' | 'finance' | 'admin' | 'automation'

export type ReturnStatus =
  | 'requested'
  | 'authorized'
  | 'received'
  | 'inspected'
  | 'refund_approved'
  | 'refund_pending'
  | 'refund_unknown'
  | 'needs_reconciliation'
  | 'refunded'
  | 'reconciled'
  | 'closed'
  | 'rejected'

export interface Identity {
  enabled?: boolean
  authenticated?: boolean
  organizationId?: string
  userId?: string
  displayName?: string
  role?: Role
}

export interface AuthContext {
  organizationId: string
  token?: string
}

export interface ReturnCase {
  id: string
  organizationId: string
  caseRef: string
  externalOrderRef: string
  customerRef: string
  reason: string
  requestedAmountMinor: number
  approvedAmountMinor: number | null
  currency: string
  status: ReturnStatus
  version: number
  inspectionNotes: string | null
  rejectionReason: string | null
  createdAt: string
  updatedAt: string
}

export interface Approval {
  id: string
  kind: string
  decision: string
  userId: string
  amountMinor: number | null
  rationale: string | null
  createdAt: string
}

export interface RefundAttempt {
  id: string
  status: string
  providerRef: string | null
  providerIdempotencyKey: string
  amountMinor: number
  currency: string
  dispatchCount: number
  lastError: string | null
  evidence: Record<string, unknown> | null
  createdAt: string
  updatedAt: string
}

export interface AuditEvent {
  id: string
  actorUserId: string | null
  action: string
  resourceType: string
  resourceId: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  createdAt: string
}

export interface OutboxEvent {
  id: string
  topic: string
  status: string
  attempts: number
  lastError: string | null
  createdAt: string
  updatedAt: string
}

export interface CaseDetail extends ReturnCase {
  approvals: Approval[]
  refundAttempts: RefundAttempt[]
  outboxEvents: OutboxEvent[]
  auditEvents: AuditEvent[]
  allowedActions: string[]
}

export interface Overview {
  total: number
  pendingCustomerService: number
  pendingWarehouse: number
  pendingFinance: number
  refundProcessing: number
  refundExceptions: number
  closed: number
  recentReturns: ReturnCase[]
  recentExceptions: ReturnCase[]
  attentionItems: AttentionItem[]
}

export interface AttentionItem {
  id: string
  caseRef: string
  externalOrderRef: string
  status: ReturnStatus
  ownerRole: string
  nextAction: string
  updatedAt: string
}

export interface PageResult<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export class ApiError extends Error {
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function requestJson<T>(
  path: string,
  auth?: AuthContext,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  if (auth) headers.set('X-Organization-ID', auth.organizationId)
  if (auth?.token) headers.set('Authorization', `Bearer ${auth.token}`)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`/v1${path}`, {
    ...init,
    headers,
    credentials: 'include',
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = payload?.error?.message ?? payload?.detail ?? `请求失败（${response.status}）`
    const code = payload?.error?.code
    throw new ApiError(String(message), response.status, code)
  }
  return payload as T
}

export function idempotencyKey(scope: string): string {
  const storageKey = `returnflow.idempotency.${scope}`
  const existing = window.sessionStorage.getItem(storageKey)
  if (existing) return existing
  const created = crypto.randomUUID()
  window.sessionStorage.setItem(storageKey, created)
  return created
}

export function clearIdempotencyKey(scope: string): void {
  window.sessionStorage.removeItem(`returnflow.idempotency.${scope}`)
}

export function toMinorUnits(value: string, currency: string): number {
  const fractionDigits = new Intl.NumberFormat('en', {
    style: 'currency',
    currency,
  }).resolvedOptions().maximumFractionDigits ?? 2
  const normalized = value.trim()
  if (!/^\d+(?:\.\d+)?$/.test(normalized)) {
    throw new Error('请输入大于 0 的有效金额。')
  }
  const [whole, fraction = ''] = normalized.split('.')
  if (fraction.length > fractionDigits) {
    throw new Error(`该币种最多支持 ${fractionDigits} 位小数。`)
  }
  const scale = 10n ** BigInt(fractionDigits)
  const minor = BigInt(whole) * scale + BigInt((fraction + '0'.repeat(fractionDigits)).slice(0, fractionDigits) || '0')
  if (minor <= 0n || minor > 100_000_000n) {
    throw new Error('退款金额必须大于 0，且不得超过 100,000,000 个最小货币单位。')
  }
  return Number(minor)
}

export function formatMinorUnits(amount: number | null, currency: string): string {
  if (amount === null) return '—'
  const digits = new Intl.NumberFormat('en', {
    style: 'currency',
    currency,
  }).resolvedOptions().maximumFractionDigits ?? 2
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(amount / 10 ** digits)
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export const statusLabels: Record<ReturnStatus, string> = {
  requested: '待客服审核',
  authorized: '待仓库收货',
  received: '待仓库验货',
  inspected: '待财务审批',
  refund_approved: '退款已批准',
  refund_pending: '退款处理中',
  refund_unknown: '支付结果未知',
  needs_reconciliation: '待人工对账',
  refunded: '已退款待对账',
  reconciled: '已对账待结案',
  closed: '已结案',
  rejected: '已拒绝',
}

export const roleLabels: Record<Role, string> = {
  customer_service: '客服',
  warehouse: '仓库',
  finance: '财务',
  admin: '管理员',
  automation: '自动化服务',
}
