# 测试证据与环境限制

## 已执行

| 检查 | 结果 |
|---|---|
| `pytest -q -m 'not integration'` | **41 passed, 8 deselected**；包括领域/API、租户隔离、四眼审批、幂等、worker/outbox、对账和工作流 JSON 结构测试 |
| `pytest -q -m integration` | **8 passed, 41 deselected**；连接本地 Compose PostgreSQL，每个测试在独立临时 schema 中运行并清理；有 2 条 Starlette/httpx 弃用警告 |
| 完整 `pytest -q` | **49 passed**，2 条弃用警告 |
| `ruff check src/returnops src/fake_payment tests` | 通过 |
| `npm run build` | 通过（TypeScript + Vite production bundle） |
| `npm run e2e:typecheck` | 通过 |
| `npm run test:e2e` | **3 passed, 1 skipped**；普通闭环、高额不同审批人、客服无权审批（UI 隐藏且 API 返回 403），通过本地 Compose 前端/API 执行 |
| `npm run test:e2e:fault` | **1 passed**；UNKNOWN、单次派发、无盲目重试、权威查询、对账和结案，通过本地演示栈执行 |
| `npm run lint` | 通过，无 lint warning |
| PowerShell 设置 `RUN_N8N_INTEGRATION` 后执行 `npm run test:n8n` | **通过**；Production Webhook 实测 401 未授权、400 无效输入、201 建单、201 同工单重放、409 内容冲突；不会将失败标记为已接受 |
| `scripts/verify-demo.ps1` | Compose 服务列表和 ReturnOps API、演示模式、前端、n8n 编辑器、Mailpit 页面检查通过 |
| `docker compose ps` | PostgreSQL、API、Fake Payment、Mailpit 健康；前端、n8n、worker 运行中。主机端口仅绑定 `127.0.0.1` |
| `n8n/workflows/*.json` | JSON 与静态节点/凭证约束测试通过；两个工作流已在 n8n **2.42.5** UI 导入、绑定本地凭据并发布 |
| Intake 生产 Webhook | 运行时集成测试通过所有分支；固定合成事件在 ReturnOps API 中保留工单 `RET-4B014F9106`，状态 `requested`。没有触发退款 |
| Operations Digest | 重启后再次手动运行成功；2026-10-10（Asia/Shanghai）最新邮件包含实时 API 待办、负责角色及下一步动作；当前本地收件箱共 5 封摘要。未连接真实 SMTP |
| 容器重启持久化 | 在不删除任何卷的前提下重启 PostgreSQL、API、worker、前端、Fake Payment、n8n 与 Mailpit；演示工单仍存在，超时样例的支付方记录仍为 `succeeded` 且 `post_count=1`，Mailpit 邮件保留；重启后 `verify-demo.ps1`、n8n Intake 集成检查与 Digest 手动执行均再次成功 |

Playwright 浏览器流连接本地 Compose 前端/API、PostgreSQL、Fake Payment 与 worker，执行客服创建/审核、仓库收货/验货、普通退款、外部成功证据、财务对账和结案；客服身份对财务审批的直接 API 请求返回 403。超时场景中 Fake Payment 已保存退款、延迟响应超时且无 Webhook，UI 显示 `REFUND_UNKNOWN` 和派发次数 1；Finance 查询支付方记录后证实成功，随后完成对账与结案。端到端测试在持久化演示库中留下动态生成的 `DEMO-PLAYWRIGHT-*` 合成工单；故障测试另留下已结案的 `DEMO-ORDER-UNKNOWN-003`，n8n 生产 Webhook 留下 `DEMO-ORDER-N8N-LIVE-*` 与固定的 `DEMO-ORDER-N8N-RUNTIME-001` 工单。这些都不是客户数据。上述容器重启后仍可读取，且支付方仍只存在一次派发记录。

PostgreSQL 集成测试另行使用 Compose 数据库中的临时 schema，测试退出时删除这些 schema；不复用或清空演示数据。n8n Runtime 检查使用固定 `event_id`，同事件重复执行返回同一工单；冲突和输入错误不会新建业务记录。

截图由真实 UI 生成：

- [ReturnFlow 正常工单闭环](assets/returnflow-closed-case.png)
- [ReturnFlow 实时业务总览](assets/returnflow-overview.png)
- [ReturnFlow 高额二人审批](assets/returnflow-second-approver.png)
- [ReturnFlow UNKNOWN 安全暂停与恢复](assets/returnflow-unknown-before-reconcile.png)、[权威查询证据](assets/returnflow-unknown-recovered.png)
- [n8n Return Intake 节点图](assets/n8n-01-return-intake.png)
- [n8n Operations Digest 节点图](assets/n8n-02-operations-digest.png)
- [Mailpit 摘要收件箱](assets/mailpit-summary-inbox.png)

## 尚未验证 / 边界

- Operations Digest 的**手动**执行和 Mailpit 投递已验证；虽然每日 09:00 Schedule Trigger 已发布，但尚未等待真实计划时刻验证自动调度。
- Playwright 浏览器端到端流程通过本地 Compose 前端/API 运行在 PostgreSQL 演示库上；随机生成的合成测试工单会保留在命名卷中。PostgreSQL 集成测试则使用每次单独创建、结束后清理的临时 schema。
- 未连接真实邮件服务或支付服务。Mailpit 与 Fake Payment 均为本地服务，不会产生外发邮件或真实退款。
- owner 与凭据保存在被 Git 忽略的 `.local/` 文件及本地 n8n 命名卷中；工作流 JSON 与截图不含秘密。新建/重置 n8n volume 后仍需按 [`README.md`](../README.md) 和 [`n8n/README.md`](../n8n/README.md) 初始化 owner、导入工作流并绑定本地凭据。
- [`BASELINE.md`](BASELINE.md) 是首次实施前的历史基线，其中的“Docker 不可用 / n8n 未运行”只描述当时状态；当前运行时证据以本文件为准。
