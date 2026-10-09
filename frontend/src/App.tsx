import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  clearIdempotencyKey,
  formatDate,
  formatMinorUnits,
  idempotencyKey,
  requestJson,
  roleLabels,
  statusLabels,
  toMinorUnits,
  type AuthContext,
  type CaseDetail,
  type Identity,
  type Overview,
  type PageResult,
  type ReturnCase,
  type ReturnStatus,
  type Role,
} from './api'

type Page = 'overview' | 'returns' | 'exceptions' | 'detail' | 'create'
type LoginMode = 'demo' | 'token'

const PAGE_SIZE = 12
const actionLabels: Record<string, string> = {
  authorize: '通过客服审核',
  reject: '拒绝申请',
  receive: '确认收货',
  inspect: '提交验货结果',
  approve_refund: '审批退款',
  provider_reconcile: '查询支付方状态',
  retry_failed_refund: '重新执行已确认失败的退款',
  mark_reconciled: '确认对账完成',
  close: '结案',
}

const navigation: { page: Page; title: string; icon: string }[] = [
  { page: 'overview', title: '业务总览', icon: '◫' },
  { page: 'returns', title: '退货工单', icon: '▤' },
  { page: 'exceptions', title: '异常与对账', icon: '↻' },
]

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

function statusTone(status: ReturnStatus): string {
  if (['closed', 'reconciled', 'refunded'].includes(status)) return 'positive'
  if (['refund_unknown', 'needs_reconciliation', 'rejected'].includes(status)) return 'warning'
  if (status === 'refund_pending') return 'active'
  return 'neutral'
}

function StatusBadge({ status }: { status: ReturnStatus }) {
  return <span className={`status-badge ${statusTone(status)}`}>{statusLabels[status]}</span>
}

function CaseTable({
  items,
  onSelect,
}: {
  items: ReturnCase[]
  onSelect: (item: ReturnCase) => void
}) {
  if (items.length === 0) {
    return <div className="empty-state">暂无符合条件的工单</div>
  }

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>工单</th>
            <th>订单编号</th>
            <th>退款金额</th>
            <th>当前状态</th>
            <th>更新时间</th>
            <th aria-label="打开工单" />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} onClick={() => onSelect(item)} className="clickable-row">
              <td>
                <strong>{item.caseRef}</strong>
                <span className="subline">{item.customerRef}</span>
              </td>
              <td>{item.externalOrderRef}</td>
              <td>{formatMinorUnits(item.approvedAmountMinor ?? item.requestedAmountMinor, item.currency)}</td>
              <td><StatusBadge status={item.status} /></td>
              <td>{formatDate(item.updatedAt)}</td>
              <td><span className="row-arrow" aria-hidden="true">›</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MetricCard({
  label,
  value,
  tone = 'plain',
  hint,
}: {
  label: string
  value: number
  tone?: string
  hint?: string
}) {
  return (
    <article className={`metric-card ${tone}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value.toLocaleString('zh-CN')}</div>
      {hint && <div className="metric-hint">{hint}</div>}
    </article>
  )
}

function LoginPanel({
  demoEnabled,
  busy,
  error,
  onDemoLogin,
  onTokenLogin,
}: {
  demoEnabled: boolean
  busy: boolean
  error: string
  onDemoLogin: (role: Role, financeSlot: number) => Promise<void>
  onTokenLogin: (token: string, organizationId: string) => Promise<void>
}) {
  const [mode, setMode] = useState<LoginMode>(demoEnabled ? 'demo' : 'token')
  const [role, setRole] = useState<Role>('customer_service')
  const [financeSlot, setFinanceSlot] = useState(0)
  const [token, setToken] = useState('')
  const [organizationId, setOrganizationId] = useState('')
  const [formError, setFormError] = useState('')

  async function submitDemo(event: FormEvent) {
    event.preventDefault()
    setFormError('')
    try {
      await onDemoLogin(role, role === 'finance' ? financeSlot : 0)
    } catch (error) {
      setFormError(messageOf(error))
    }
  }

  async function submitToken(event: FormEvent) {
    event.preventDefault()
    setFormError('')
    try {
      await onTokenLogin(token.trim(), organizationId.trim())
    } catch (error) {
      setFormError(messageOf(error))
    }
  }

  return (
    <main className="login-page">
      <div className="login-brand">
        <div className="brand-mark">R</div>
        <div>
          <div className="brand-name">ReturnFlow</div>
          <div className="brand-caption">售后退款工作台</div>
        </div>
      </div>
      <section className="login-card">
        <div className="eyebrow">安全业务操作台</div>
        <h1>欢迎回来</h1>
        <p className="login-intro">选择工作身份，按当前业务流程处理退货和退款。</p>
        {demoEnabled && (
          <div className="login-tabs" role="tablist" aria-label="登录方式">
            <button
              className={mode === 'demo' ? 'selected' : ''}
              type="button"
              onClick={() => setMode('demo')}
            >演示身份</button>
            <button
              className={mode === 'token' ? 'selected' : ''}
              type="button"
              onClick={() => setMode('token')}
            >API Token</button>
          </div>
        )}
        {mode === 'demo' && demoEnabled ? (
          <form className="form-stack" onSubmit={submitDemo}>
            <label>
              工作身份
              <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
                <option value="customer_service">客服</option>
                <option value="warehouse">仓库</option>
                <option value="finance">财务</option>
                <option value="admin">管理员</option>
              </select>
            </label>
            {role === 'finance' && (
              <label>
                财务审批人
                <select value={financeSlot} onChange={(event) => setFinanceSlot(Number(event.target.value))}>
                  <option value={0}>Finance A</option>
                  <option value={1}>Finance B</option>
                </select>
              </label>
            )}
            <button className="primary-button full-width" disabled={busy} type="submit">
              {busy ? '正在登录…' : '进入工作台'}
            </button>
            <p className="small-note">本地演示身份来自后端预置用户，会话保存在 HttpOnly Cookie 中。</p>
          </form>
        ) : (
          <form className="form-stack" onSubmit={submitToken}>
            <label>
              组织 ID
              <input
                required
                value={organizationId}
                onChange={(event) => setOrganizationId(event.target.value)}
                placeholder="粘贴组织 UUID"
                autoComplete="off"
              />
            </label>
            <label>
              Bearer Token
              <input
                required
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="粘贴 API Token"
                autoComplete="off"
              />
            </label>
            <button className="primary-button full-width" disabled={busy} type="submit">
              {busy ? '正在验证…' : '验证并进入'}
            </button>
            <p className="small-note">Token 仅保存在当前页面内存中，刷新后需重新输入。</p>
          </form>
        )}
        {(formError || error) && <div className="notice error">{formError || error}</div>}
      </section>
      <div className="login-footer">ReturnOps 管理业务事实 · n8n 负责外围自动化</div>
    </main>
  )
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="detail-section">
      <div className="section-heading"><h3>{title}</h3></div>
      {children}
    </section>
  )
}

function App() {
  const [demoEnabled, setDemoEnabled] = useState(false)
  const [demoAuthenticated, setDemoAuthenticated] = useState(false)
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [manualAuth, setManualAuth] = useState<AuthContext | null>(null)
  const [booting, setBooting] = useState(true)
  const [busy, setBusy] = useState(false)
  const [page, setPage] = useState<Page>('overview')
  const [overview, setOverview] = useState<Overview | null>(null)
  const [caseResult, setCaseResult] = useState<PageResult<ReturnCase> | null>(null)
  const [exceptions, setExceptions] = useState<CaseDetail[]>([])
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [refreshCounter, setRefreshCounter] = useState(0)
  const [notice, setNotice] = useState<{ text: string; tone: string } | null>(null)
  const [error, setError] = useState('')
  const [actionForm, setActionForm] = useState('')
  const [actionText, setActionText] = useState('')
  const [approvedAmount, setApprovedAmount] = useState('')
  const [currency, setCurrency] = useState('CNY')
  const [transition, setTransition] = useState<{ action: string; before: ReturnStatus; after: ReturnStatus } | null>(null)

  const auth = useMemo<AuthContext | null>(() => {
    if (manualAuth) return manualAuth
    if (identity && identity.organizationId) return { organizationId: identity.organizationId }
    return null
  }, [identity, manualAuth])

  useEffect(() => {
    let active = true
    requestJson<Identity>('/demo/session')
      .then((session) => {
        if (!active) return
        setDemoEnabled(Boolean(session.enabled))
        if (session.authenticated) {
          setIdentity(session)
          setDemoAuthenticated(true)
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(messageOf(reason))
      })
      .finally(() => {
        if (active) setBooting(false)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!auth) return
    let active = true
    async function load() {
      setBusy(true)
      setError('')
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
        if (statusFilter) params.set('status', statusFilter)
        if (search) params.set('q', search)
        const [summary, returns] = await Promise.all([
          requestJson<Overview>('/overview', auth ?? undefined),
          requestJson<PageResult<ReturnCase>>(`/returns?${params}`, auth ?? undefined),
        ])
        if (!active) return
        setOverview(summary)
        setCaseResult(returns)
        if (page === 'exceptions') {
          const result = await requestJson<{ items: CaseDetail[] }>('/returns/exceptions', auth ?? undefined)
          if (active) setExceptions(result.items)
        }
        if (selectedId) {
          const current = await requestJson<CaseDetail>(`/returns/${selectedId}`, auth ?? undefined)
          if (active) setDetail(current)
        }
      } catch (reason) {
        if (active) setError(messageOf(reason))
      } finally {
        if (active) setBusy(false)
      }
    }
    void load()
    return () => { active = false }
  }, [auth, page, statusFilter, search, offset, selectedId, refreshCounter])

  async function demoLogin(role: Role, financeSlot: number) {
    setBusy(true)
    setError('')
    try {
      const session = await requestJson<Identity>('/demo/session', undefined, {
        method: 'POST',
        body: JSON.stringify({ role, finance_slot: financeSlot }),
      })
      setIdentity(session)
      setManualAuth(null)
      setDemoAuthenticated(true)
      setSelectedId(null)
      setPage('overview')
      setNotice({ text: `已进入${session.displayName ?? roleLabels[role]}工作区`, tone: 'success' })
    } finally {
      setBusy(false)
    }
  }

  async function tokenLogin(token: string, organizationId: string) {
    if (!token || !organizationId) throw new Error('请填写组织 ID 和 Token。')
    setBusy(true)
    try {
      const candidate = { token, organizationId }
      const currentUser = await requestJson<Identity>('/me', candidate)
      setManualAuth(candidate)
      setIdentity(currentUser)
      setDemoAuthenticated(false)
      setSelectedId(null)
      setPage('overview')
      setNotice({ text: 'Token 验证成功', tone: 'success' })
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    if (demoAuthenticated) {
      await requestJson('/demo/session', undefined, { method: 'DELETE' }).catch(() => undefined)
    }
    setIdentity(null)
    setManualAuth(null)
    setDemoAuthenticated(false)
    setSelectedId(null)
    setDetail(null)
    setNotice(null)
  }

  async function switchRole(value: string) {
    const [roleValue, slotValue] = value.split(':')
    await demoLogin(roleValue as Role, Number(slotValue ?? '0'))
  }

  function openCase(item: ReturnCase) {
    setSelectedId(item.id)
    setDetail(null)
    setTransition(null)
    setActionForm('')
    setNotice(null)
    setPage('detail')
  }

  async function createReturn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!auth) return
    setBusy(true)
    setError('')
    const form = new FormData(event.currentTarget)
    try {
      const requestedAmountMinor = toMinorUnits(String(form.get('amount') ?? ''), currency)
      const scope = 'return-create'
      const result = await requestJson<{ replayed: boolean; result: ReturnCase }>(
        '/returns',
        auth,
        {
          method: 'POST',
          headers: { 'Idempotency-Key': idempotencyKey(scope) },
          body: JSON.stringify({
            external_order_ref: String(form.get('order') ?? '').trim(),
            customer_ref: String(form.get('customer') ?? '').trim(),
            reason: String(form.get('reason') ?? '').trim(),
            requested_amount_minor: requestedAmountMinor,
            currency,
          }),
        },
      )
      clearIdempotencyKey(scope)
      setNotice({ text: result.replayed ? '检测到重复提交，已返回原工单。' : '退货申请已建立。', tone: 'success' })
      setSelectedId(result.result.id)
      setPage('detail')
      setRefreshCounter((value) => value + 1)
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  async function runAction(action: string, extra: Record<string, unknown> = {}) {
    if (!auth || !detail) return
    const before = detail.status
    const scope = `${detail.id}-${action}-${detail.version}`
    const endpoints: Record<string, string> = {
      authorize: 'authorize',
      reject: 'reject',
      receive: 'receive',
      inspect: 'inspect',
      approve_refund: 'approve-refund',
      provider_reconcile: 'provider-reconcile',
      retry_failed_refund: 'retry-failed-refund',
      mark_reconciled: 'mark-reconciled',
      close: 'close',
    }
    const versioned = ['authorize', 'reject', 'receive', 'inspect', 'approve_refund', 'retry_failed_refund', 'mark_reconciled', 'close'].includes(action)
    const payload = versioned ? { expected_version: detail.version, ...extra } : extra
    setBusy(true)
    setError('')
    try {
      const response = await requestJson<{ replayed?: boolean; result?: Record<string, unknown> }>(
        `/returns/${detail.id}/${endpoints[action]}`,
        auth,
        {
          method: 'POST',
          headers: { 'Idempotency-Key': idempotencyKey(scope) },
          body: Object.keys(payload).length ? JSON.stringify(payload) : undefined,
        },
      )
      clearIdempotencyKey(scope)
      const updated = await requestJson<CaseDetail>(`/returns/${detail.id}`, auth)
      setDetail(updated)
      setTransition({ action, before, after: updated.status })
      const result = response.result
      const secondApprovalRequired = Boolean(result && result.secondApprovalRequired)
      setNotice({
        text: secondApprovalRequired
          ? '第一位财务审批已记录；高额退款需要另一位财务人员审批相同金额。'
          : `${actionLabels[action]}已提交，当前状态：${statusLabels[updated.status]}。`,
        tone: secondApprovalRequired ? 'info' : 'success',
      })
      setActionForm('')
      setActionText('')
      setRefreshCounter((value) => value + 1)
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  async function submitActionForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!detail) return
    try {
      if (actionForm === 'authorize') await runAction(actionForm, { rationale: actionText.trim() || null })
      if (actionForm === 'inspect') await runAction(actionForm, { notes: actionText.trim() })
      if (actionForm === 'reject') await runAction(actionForm, { reason: actionText.trim() })
      if (actionForm === 'approve_refund') {
        await runAction(actionForm, {
          approved_amount_minor: toMinorUnits(approvedAmount, detail.currency),
          rationale: actionText.trim() || null,
        })
      }
    } catch (reason) {
      setError(messageOf(reason))
    }
  }

  function beginAction(action: string) {
    if (['authorize', 'inspect', 'reject', 'approve_refund'].includes(action)) {
      setActionForm(action)
      setActionText('')
      if (action === 'approve_refund' && detail) {
        const digits = new Intl.NumberFormat('en', { style: 'currency', currency: detail.currency }).resolvedOptions().maximumFractionDigits ?? 2
        const firstFinanceApproval = detail.approvals.find(
          (approval) => approval.kind === 'refund' && approval.decision === 'approved',
        )
        const amountMinor = firstFinanceApproval?.amountMinor ?? detail.requestedAmountMinor
        const whole = Math.floor(amountMinor / 10 ** digits)
        const decimal = amountMinor % 10 ** digits
        setApprovedAmount(digits ? `${whole}.${String(decimal).padStart(digits, '0')}` : String(whole))
      }
      return
    }
    void runAction(action)
  }

  function selectPage(next: Page) {
    setPage(next)
    if (next !== 'detail') setSelectedId(null)
    setOffset(0)
    setError('')
    setNotice(null)
  }

  function refreshData() {
    setNotice(null)
    setRefreshCounter((value) => value + 1)
  }

  if (booting) {
    return <main className="loading-screen"><div className="brand-mark">R</div><p>正在连接 ReturnOps…</p></main>
  }

  if (!auth) {
    return (
      <LoginPanel
        demoEnabled={demoEnabled}
        busy={busy}
        error={error}
        onDemoLogin={demoLogin}
        onTokenLogin={tokenLogin}
      />
    )
  }

  const title = page === 'detail' ? (detail?.caseRef ?? '工单详情') : page === 'create' ? '新建退货申请' : navigation.find((item) => item.page === page)?.title ?? '业务总览'
  const canCreate = identity?.role === 'customer_service' || identity?.role === 'admin'
  const canViewExceptions = identity?.role === 'finance' || identity?.role === 'admin'
  const pageCases = caseResult?.items ?? []
  const roleOption = identity?.role === 'finance'
    ? `${identity.displayName?.endsWith('B') ? 'finance:1' : 'finance:0'}`
    : identity?.role ?? 'customer_service'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">R</div>
          <div><div className="brand-name">ReturnFlow</div><div className="brand-caption">售后运营</div></div>
        </div>
        <div className="workspace-label">工作区</div>
        <nav className="main-nav" aria-label="主导航">
          {navigation.filter((item) => item.page !== 'exceptions' || canViewExceptions).map((item) => (
            <button
              key={item.page}
              type="button"
              className={`nav-item ${page === item.page || (page === 'detail' && item.page === 'returns') || (page === 'create' && item.page === 'returns') ? 'active' : ''}`}
              onClick={() => selectPage(item.page)}
            >
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>
              <span>{item.title}</span>
              {item.page === 'exceptions' && overview?.refundExceptions ? <span className="nav-count">{overview.refundExceptions}</span> : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <span className="dot green" />
            <div><strong>业务 API 已连接</strong><span>数据来自当前组织</span></div>
          </div>
          <div className="sidebar-version">ReturnOps Mini · Demo</div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>ReturnFlow</span><span>/</span><strong>{title}</strong></div>
          <div className="topbar-actions">
            <span className="live-label"><span className="dot green" />实时数据</span>
            <div className="identity-control">
              <div className="avatar">{(identity?.displayName ?? 'API').slice(0, 1)}</div>
              <div className="identity-name"><strong>{identity?.displayName ?? (manualAuth ? 'API 用户' : '业务用户')}</strong><span>{identity?.role ? roleLabels[identity.role] : 'Bearer Token'}</span></div>
              {demoAuthenticated && identity?.role ? (
                <select
                  aria-label="切换演示身份"
                  className="role-switch"
                  value={roleOption}
                  onChange={(event) => void switchRole(event.target.value)}
                >
                  <option value="customer_service">切换：客服</option>
                  <option value="warehouse">切换：仓库</option>
                  <option value="finance:0">切换：Finance A</option>
                  <option value="finance:1">切换：Finance B</option>
                  <option value="admin">切换：管理员</option>
                </select>
              ) : null}
              <button className="icon-button" type="button" onClick={() => void logout()} title="退出登录" aria-label="退出登录">↪</button>
            </div>
          </div>
        </header>

        <div className="content-area">
          {notice && <div className={`notice ${notice.tone}`} role="status"><span>{notice.text}</span><button onClick={() => setNotice(null)} aria-label="关闭提示">×</button></div>}
          {error && <div className="notice error" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="关闭错误">×</button></div>}

          {page === 'overview' && (
            <>
              <div className="page-heading">
                <div><div className="eyebrow">运营概况</div><h1>业务总览</h1><p>查看当前组织的退货、退款与异常处理进度。</p></div>
                <div className="heading-actions"><button className="secondary-button" onClick={refreshData} disabled={busy}>↻ 刷新数据</button>{canCreate && <button className="primary-button" onClick={() => selectPage('create')}>＋ 新建申请</button>}</div>
              </div>
              <div className="metrics-grid">
                <MetricCard label="工单总数" value={overview?.total ?? 0} hint="当前组织全部工单" />
                <MetricCard label="待客服审核" value={overview?.pendingCustomerService ?? 0} tone="blue" />
                <MetricCard label="待仓库处理" value={overview?.pendingWarehouse ?? 0} tone="purple" />
                <MetricCard label="待财务审批" value={overview?.pendingFinance ?? 0} tone="orange" />
                <MetricCard label="退款处理中" value={overview?.refundProcessing ?? 0} tone="green" />
                <MetricCard label="待财务核查 / 对账" value={overview?.refundExceptions ?? 0} tone="red" hint="含未知结果与已退款待对账" />
                <MetricCard label="已结案" value={overview?.closed ?? 0} tone="plain" />
              </div>
              <div className="dashboard-grid">
                <section className="panel">
                  <div className="panel-heading"><div><h2>最近工单</h2><p>按最近更新时间排序</p></div><button className="text-button" onClick={() => selectPage('returns')}>查看全部 <span>→</span></button></div>
                  <CaseTable items={overview?.recentReturns ?? []} onSelect={openCase} />
                </section>
                <section className="panel exception-panel">
                  <div className="panel-heading"><div><h2>异常与待对账</h2><p>结果未知、需要核查或等待财务对账</p></div><span className="count-pill">{overview?.refundExceptions ?? 0}</span></div>
                  {(overview?.recentExceptions ?? []).length === 0 ? (
                    <div className="empty-state compact"><div className="empty-check">✓</div><strong>当前没有待核查或对账记录</strong><span>新的异常会显示在这里</span></div>
                  ) : (
                    <div className="exception-list">
                      {overview?.recentExceptions.map((item) => (
                        <button key={item.id} className="exception-item" onClick={() => openCase(item)}>
                          <span className="exception-icon">!</span><span className="exception-copy"><strong>{item.caseRef}</strong><span>{item.externalOrderRef}</span></span><StatusBadge status={item.status} /><span className="row-arrow">›</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {canViewExceptions && <button className="secondary-button full-width" onClick={() => selectPage('exceptions')}>打开异常与对账中心</button>}
                </section>
              </div>
            </>
          )}

          {page === 'returns' && (
            <>
              <div className="page-heading">
                <div><div className="eyebrow">工单管理</div><h1>退货工单</h1><p>搜索业务记录，并按状态查看处理进度。</p></div>
                {canCreate && <button className="primary-button" onClick={() => selectPage('create')}>＋ 新建退货申请</button>}
              </div>
              <section className="panel">
                <form className="filter-row" onSubmit={(event) => { event.preventDefault(); setOffset(0); setSearch(searchDraft.trim()) }}>
                  <label className="search-field"><span aria-hidden="true">⌕</span><input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="搜索工单号、订单号或客户引用" /><button type="submit" className="sr-only">搜索</button></label>
                  <select className="filter-select" aria-label="按状态筛选" value={statusFilter} onChange={(event) => { setOffset(0); setStatusFilter(event.target.value) }}>
                    <option value="">全部状态</option>
                    {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                  <span className="result-count">共 {caseResult?.total ?? 0} 条</span>
                </form>
                <CaseTable items={pageCases} onSelect={openCase} />
                <div className="pagination">
                  <span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页，共 {caseResult ? Math.max(1, Math.ceil(caseResult.total / PAGE_SIZE)) : 1} 页</span>
                  <div><button className="secondary-button" disabled={offset === 0 || busy} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</button><button className="secondary-button" disabled={!caseResult || offset + PAGE_SIZE >= caseResult.total || busy} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button></div>
                </div>
              </section>
            </>
          )}

          {page === 'exceptions' && (
            <>
              <div className="page-heading">
                <div><div className="eyebrow">退款控制</div><h1>异常与对账</h1><p>查询支付方权威状态，核对本地退款意图与外部证据。</p></div>
                <button className="secondary-button" onClick={refreshData} disabled={busy}>↻ 刷新异常</button>
              </div>
              <div className="info-banner"><strong>未知结果不会自动重试。</strong><span>只有在权威查询确认没有退款记录后，财务人员才能重新发起已确认失败的退款。</span></div>
              <section className="panel">
                <div className="panel-heading"><div><h2>需要处理的记录</h2><p>列表由 ReturnOps 当前业务状态生成</p></div><span className="count-pill danger">{exceptions.length}</span></div>
                <CaseTable items={exceptions} onSelect={openCase} />
              </section>
            </>
          )}

          {page === 'create' && (
            <>
              <div className="page-heading"><div><div className="eyebrow">客服工作区</div><h1>新建退货申请</h1><p>使用客户引用编号保存演示工单，不录入真实个人信息。</p></div><button className="secondary-button" onClick={() => selectPage('returns')}>返回工单列表</button></div>
              <section className="panel form-panel">
                <form className="business-form" onSubmit={(event) => void createReturn(event)}>
                  <div className="form-grid">
                    <label>订单编号<input required name="order" maxLength={120} placeholder="例如 ORDER-10001" /></label>
                    <label>客户引用编号<input required name="customer" maxLength={120} placeholder="例如 CUSTOMER-001" /></label>
                    <label>退款币种<select value={currency} onChange={(event) => setCurrency(event.target.value)}><option value="CNY">CNY · 人民币</option><option value="USD">USD · 美元</option><option value="JPY">JPY · 日元</option></select></label>
                    <label>申请退款金额（{currency}）<input required name="amount" type="number" min="0.01" step={currency === 'JPY' ? '1' : '0.01'} placeholder={currency === 'JPY' ? '12900' : '129.00'} /></label>
                    <label className="full-row">退货原因<textarea required name="reason" rows={4} maxLength={2000} placeholder="说明客户申请退货的原因" /></label>
                  </div>
                  <div className="form-footer"><span>金额将以整数最小货币单位提交，避免浮点误差。</span><button className="primary-button" disabled={busy}>{busy ? '正在提交…' : '建立退货工单'}</button></div>
                </form>
              </section>
            </>
          )}

          {page === 'detail' && (
            <>
              <div className="page-heading detail-page-heading">
                <div><button className="back-link" onClick={() => selectPage('returns')}>← 返回工单列表</button><div className="detail-title-row"><h1>{detail?.caseRef ?? '正在载入…'}</h1>{detail && <StatusBadge status={detail.status} />}</div><p>工单详情、审批记录、支付证据与操作审计</p></div>
                <button className="secondary-button" onClick={refreshData} disabled={busy}>↻ 重新加载</button>
              </div>
              {!detail ? <div className="panel empty-state">正在读取工单详情…</div> : (
                <>
                  <div className="detail-summary-grid">
                    <article className="summary-card"><span>申请金额</span><strong>{formatMinorUnits(detail.requestedAmountMinor, detail.currency)}</strong></article>
                    <article className="summary-card"><span>批准金额</span><strong>{formatMinorUnits(detail.approvedAmountMinor, detail.currency)}</strong></article>
                    <article className="summary-card"><span>当前版本</span><strong>v{detail.version}</strong></article>
                    <article className="summary-card"><span>创建时间</span><strong>{formatDate(detail.createdAt)}</strong></article>
                  </div>
                  <div className="detail-layout">
                    <div className="detail-main-column">
                      <DetailSection title="退货信息">
                        <div className="data-grid">
                          <div><span>订单编号</span><strong>{detail.externalOrderRef}</strong></div>
                          <div><span>客户引用编号</span><strong>{detail.customerRef}</strong></div>
                          <div><span>退款币种</span><strong>{detail.currency}</strong></div>
                          <div><span>最近更新</span><strong>{formatDate(detail.updatedAt)}</strong></div>
                          <div className="wide"><span>申请原因</span><strong>{detail.reason}</strong></div>
                          {detail.inspectionNotes && <div className="wide"><span>验货记录</span><strong>{detail.inspectionNotes}</strong></div>}
                          {detail.rejectionReason && <div className="wide"><span>拒绝原因</span><strong>{detail.rejectionReason}</strong></div>}
                        </div>
                      </DetailSection>
                      <DetailSection title="审批记录">
                        {detail.approvals.length === 0 ? <div className="empty-state compact">尚无审批记录</div> : <div className="approval-list">{detail.approvals.map((approval, index) => <div className="approval-row" key={approval.id}><span className="approval-index">{index + 1}</span><div><strong>{approval.kind === 'eligibility' ? '客服资格审核' : approval.kind === 'high_value_refund_second' ? '高额退款第二人审批' : '财务退款审批'}</strong><span>{approval.rationale || '未填写说明'} · {formatDate(approval.createdAt)}</span></div><div className="approval-amount">{formatMinorUnits(approval.amountMinor, detail.currency)}</div></div>)}</div>}
                      </DetailSection>
                      <DetailSection title="退款与外部支付结果">
                        {detail.refundAttempts.length === 0 ? <div className="empty-state compact">财务批准后将建立退款意图</div> : detail.refundAttempts.map((attempt) => <div className="refund-card" key={attempt.id}><div className="refund-card-heading"><div><span>退款意图</span><strong>{attempt.id}</strong></div><span className={`status-badge ${attempt.status === 'succeeded' ? 'positive' : attempt.status === 'unknown' || attempt.status === 'failed' ? 'warning' : 'active'}`}>{attempt.status}</span></div><div className="data-grid"><div><span>退款金额</span><strong>{formatMinorUnits(attempt.amountMinor, attempt.currency)}</strong></div><div><span>支付方退款编号</span><strong>{attempt.providerRef || '尚未确认'}</strong></div><div><span>派发次数</span><strong>{attempt.dispatchCount}</strong></div><div><span>幂等意图编号</span><strong className="mono break-all">{attempt.providerIdempotencyKey}</strong></div></div>{attempt.lastError && <div className="evidence-box warning-box"><strong>最近异常</strong><span>{attempt.lastError}</span></div>}{attempt.evidence && <div className="evidence-box"><strong>支付方证据</strong><pre>{JSON.stringify(attempt.evidence, null, 2)}</pre></div>}</div>)}
                      </DetailSection>
                      <DetailSection title="操作与队列审计">
                        <div className="audit-list">{detail.auditEvents.length === 0 ? <div className="empty-state compact">暂无操作审计</div> : [...detail.auditEvents].reverse().map((item) => <div className="audit-row" key={item.id}><span className="audit-dot" /><div><strong>{item.action}</strong><span>{item.actorUserId ? `操作人 ${item.actorUserId}` : '系统操作'} · {formatDate(item.createdAt)}</span>{item.metadata && <small>{JSON.stringify(item.metadata)}</small>}</div></div>)}</div>
                        {detail.outboxEvents.length > 0 && <div className="outbox-list"><strong>Outbox 派发记录</strong>{detail.outboxEvents.map((item) => <div key={item.id}><code>{item.topic}</code><span>{item.status}</span><span>执行 {item.attempts} 次</span>{item.lastError && <small>{item.lastError}</small>}</div>)}</div>}
                      </DetailSection>
                    </div>
                    <aside className="detail-side-column">
                      <section className="panel action-panel"><div className="panel-heading"><div><h2>可执行操作</h2><p>后端仍会独立检查角色与状态</p></div></div>{detail.allowedActions.length === 0 ? <div className="empty-state compact">当前身份没有可执行操作</div> : <div className="action-list">{detail.allowedActions.map((action) => <button key={action} className={action === 'reject' || action === 'retry_failed_refund' ? 'action-button danger-action' : 'action-button'} onClick={() => beginAction(action)} disabled={busy}>{actionLabels[action]}</button>)}</div>}
                        {actionForm && <form className="action-form" onSubmit={(event) => void submitActionForm(event)}><div className="action-form-heading">{actionLabels[actionForm]}</div>{actionForm === 'approve_refund' && <label>批准金额（{detail.currency}）<input type="number" min="0.01" step="0.01" required value={approvedAmount} onChange={(event) => setApprovedAmount(event.target.value)} /></label>}{actionForm === 'inspect' && <label>验货结果<textarea rows={3} required value={actionText} onChange={(event) => setActionText(event.target.value)} /></label>}{actionForm === 'reject' && <label>拒绝原因<textarea rows={3} required value={actionText} onChange={(event) => setActionText(event.target.value)} /></label>}{actionForm === 'authorize' && <label>审核说明（可选）<textarea rows={3} value={actionText} onChange={(event) => setActionText(event.target.value)} /></label>}{actionForm === 'approve_refund' && <label>审批说明（可选）<textarea rows={3} value={actionText} onChange={(event) => setActionText(event.target.value)} /></label>}<div className="action-form-buttons"><button type="button" className="secondary-button" onClick={() => setActionForm('')}>取消</button><button className="primary-button" disabled={busy}>{busy ? '处理中…' : '确认操作'}</button></div></form>}
                        {transition && <div className="transition-result"><strong>{actionLabels[transition.action]}结果</strong><span>{statusLabels[transition.before]} <b>→</b> {statusLabels[transition.after]}</span></div>}
                        <div className="current-version">操作基于工单版本 v{detail.version}</div>
                      </section>
                      <section className="panel authority-panel"><div className="authority-icon">i</div><div><strong>结果未知时暂停自动重试</strong><p>系统会优先通过支付方权威查询获得事实，再开放安全恢复操作。</p></div></section>
                    </aside>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
