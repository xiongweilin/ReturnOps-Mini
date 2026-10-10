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
| GitHub `frontend` CI job | 独立执行 `npm ci`、`npm run build`、`npm run lint` 和 `npm run e2e:typecheck`；随每次 CI 运行 |
| `npm run test:e2e` | **3 passed, 1 skipped**；普通闭环、高额不同审批人、客服无权审批（UI 隐藏且 API 返回 403），通过本地 Compose 前端/API 执行 |
| `npm run test:e2e:fault` | **1 passed**；UNKNOWN、单次派发、无盲目重试、权威查询、对账和结案，通过本地演示栈执行 |
| `npm run lint` | 通过，无 lint warning |
| PowerShell 设置 `RUN_N8N_INTEGRATION` 后执行 `npm run test:n8n` | **通过**；Production Webhook 实测 401 未授权、400 无效输入、201 建单、201 同工单重放、409 内容冲突；不会将失败标记为已接受 |
| `scripts/verify-demo.ps1` | Compose 服务列表和 ReturnOps API、演示模式、前端、n8n 编辑器、Mailpit 页面检查通过 |
| `docker compose ps` | PostgreSQL、API、Fake Payment、Mailpit 健康；前端、n8n、worker 运行中。主机端口仅绑定 `127.0.0.1` |
| `n8n/workflows/*.json` | JSON 与静态节点/凭证约束测试通过；全新 n8n **2.42.5** volume 由 `start-demo.ps1` 自动创建/绑定三项本地凭据、upsert 并发布两个工作流，无需 UI 手工导入或逐节点配置 |
| Intake 生产 Webhook | 运行时集成测试通过所有分支；固定合成事件在 ReturnOps API 中保留工单 `RET-4B014F9106`，状态 `requested`。没有触发退款 |
| Operations Digest | 容器重启后手动执行成功；随后每日 Schedule Trigger 于 2026-10-10 09:00:53（Asia/Shanghai）自动触发，n8n 执行记录 ID `20` 显示 Succeeded（110 ms），Mailpit 收到来自实时 API 摘要的邮件，含待办、负责角色及下一步动作；当前本地收件箱共 6 封摘要。未连接真实 SMTP |
| 容器重启持久化 | 在不删除任何卷的前提下重启 PostgreSQL、API、worker、前端、Fake Payment、n8n 与 Mailpit；演示工单仍存在，超时样例的支付方记录仍为 `succeeded` 且 `post_count=1`，Mailpit 邮件保留；重启后 `verify-demo.ps1`、n8n Intake 集成检查与 Digest 手动执行均再次成功 |
| `npm run test:n8n:digest` | **通过**；Playwright 在 n8n UI 手动运行已发布 Digest，收到新的 Mailpit 邮件，正文包含实时待办与客服/仓库/财务角色 |
| 全新环境 `start-demo.ps1` | 从不含 `.env`、`.local`、`frontend/node_modules` 或 `.git` 的源代码副本开始，创建空 Compose 项目/数据卷；单次命令完成 Seed、owner、90 天 API key、本地 credentials、两条已发布工作流；第二次运行复用同一 workflow ID/key 并未产生重复资源，无人工 n8n UI 步骤 |
| 受控完整演示验证 | 同一干净 Compose 项目中 `verify-demo.ps1`、普通 Playwright E2E（3 passed/1 skipped）、UNKNOWN recovery E2E（1 passed）、n8n Webhook 分支、Digest→Mailpit 均通过；真实支付与外部 SMTP 未连接 |

### 首次部署干净环境复现

在 Windows PowerShell 7 中从新源代码副本开始；副本没有 `.env`、`.local/`、`frontend/node_modules/` 或 `.git/`，并使用新的 Compose 项目和命名卷。唯一的部署操作是运行 `scripts/start-demo.ps1`：它生成被忽略的本地环境/owner/Webhook 凭据，执行 Seed、安装锁定的 npm 工具链、创建并校验本地 n8n API key，再通过 n8n API 创建/更新凭据、导入两份 JSON 并发布。全程没有人工登录 n8n、点击 Import、逐节点绑定或手工 Publish。随后 `scripts/verify-demo.ps1` 和 Intake/Digest 运行时检查通过；再次运行 `start-demo.ps1` 复用现有 key 与 workflow ID，不重复创建。

干净环境试跑时，一个临时自选 API 端口曾与同机独立运行的 AIOS 服务冲突，另一次首次镜像构建遇到 PyPI TLS EOF；选择未占用的 loopback 端口并重试后，独立项目成功启动。问题均为测试主机资源/瞬时网络，不修改或清理其他 Compose 项目数据。

### 2026-10-10 README 干净环境复现

本轮从 `main` 合并提交 `beacc62702ffd692684abdee6bd461f99752aa7f` 的 Git archive 建立全新源代码副本；副本初始不含 `.git/`、`.env`、`.local/` 或 `frontend/node_modules/`，使用独立 Compose 项目和全新命名卷。按 README 调用 `scripts/start-demo.ps1` 两次：首次生成本地配置并创建/发布两条 n8n 工作流，第二次复用已有资源；`scripts/verify-demo.ps1` 通过。`npm ci`、Chromium 安装、普通浏览器 E2E（3 passed、1 skipped）、UNKNOWN 恢复 E2E（1 passed）、n8n Intake Webhook（401、400、201、同事件重放 201、冲突 409）以及 Digest→Mailpit 邮件检查均通过。未知退款场景确认 Fake Payment 已保存退款、无 Webhook；财务权威查询后完成对账。复现后仅停止本轮独立 Compose 项目，保留其数据卷。

受控 GitHub Actions 首次运行在合并后的 `main` 提交 `beacc62702ffd692684abdee6bd461f99752aa7f` 上触发：[run 38034480552](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38034480552)。Ubuntu 干净 runner 在 Seed 写入 `.local/organization-id.txt` 时遇到权限拒绝，未进入后续浏览器、UNKNOWN、n8n 与邮件验证。原因是 Compose bind mount 在宿主机 `.local/` 尚不存在时创建了 root 所有目录；`scripts/start-demo.ps1` 已调整为在启动 Compose 前创建宿主机目录。

修复目录问题后的 [run 38035544448](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38035544448) 通过栈启动、基础浏览器流程和 UNKNOWN 创建，但恢复测试查找默认订单 `DEMO-ORDER-UNKNOWN-002`，而前置脚本创建了 `DEMO-ORDER-UNKNOWN-981`；浏览器找不到目标工单，后续 Intake 与 Digest 步骤因此跳过。workflow 现通过同一个 `RETURNFLOW_UNKNOWN_ORDER_REF` 环境值同时配置创建脚本和恢复测试。

最终 [run 38035879608](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38035879608) 在干净 Ubuntu runner 上以代码提交 `4e9e588b37cb8e417c4d7902182a07036eda0276` 成功完成：自动启动及配置 n8n、完整栈检查、普通浏览器 E2E、创建 UNKNOWN 场景、浏览器权威查询/对账/结案恢复、Production Intake Webhook、Digest→Mailpit，以及临时 Compose 项目与测试卷清理，所有步骤均为 success。测试过的应用与 workflow 代码在最终记录运行号的文档提交中未变更。

PR 常规 CI 首轮 [run 38036341354](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38036341354) 的 8 项中有 7 项通过；Fault Lab 在重置场景数据时与仍在执行的 Fake Payment Webhook 发生 PostgreSQL 死锁。Fault Lab 的同步响应延迟与 UNKNOWN 对账场景已切换为不投递非目标 Webhook，隔离异步请求对下一个场景的影响。随后 [run 38036635498](https://github.com/xiongweilin/ReturnOps-Mini/actions/runs/38036635498) 的 8 项 PR 检查全部通过，包括四类 Fault Lab 场景、性能契约、前端、PostgreSQL 集成、依赖/镜像扫描、变异测试、质量和 hygiene 检查。

视频与文字说明抽样核对：MP4 时长为 297.2 秒，和约 4–5 分钟的录屏说明相符；简体中文字幕及 `RECORDING.md` 的时间线覆盖总览、Intake 幂等、岗位审批与高额二人复核、支付结果未知后的人工查询、Operations Digest 和 Mailpit 收件。对成片代表性画面的抽样检查显示这些 UI 与本轮浏览器、n8n 和 Mailpit 运行证据一致。视频和所有运行样例使用虚构数据、本地 Fake Payment 与 Mailpit。

Playwright 浏览器流连接本地 Compose 前端/API、PostgreSQL、Fake Payment 与 worker，执行客服创建/审核、仓库收货/验货、普通退款、外部成功证据、财务对账和结案；客服身份对财务审批的直接 API 请求返回 403。超时场景中 Fake Payment 已保存退款、延迟响应超时且无 Webhook，UI 显示 `REFUND_UNKNOWN` 和派发次数 1；Finance 查询支付方记录后证实成功，随后完成对账与结案。端到端测试在持久化演示库中留下动态生成的 `DEMO-PLAYWRIGHT-*` 合成工单；故障测试另留下已结案的 `DEMO-ORDER-UNKNOWN-003`，n8n 生产 Webhook 留下 `DEMO-ORDER-N8N-LIVE-*` 与固定的 `DEMO-ORDER-N8N-RUNTIME-001` 工单。这些都不是客户数据。上述容器重启后仍可读取，且支付方仍只存在一次派发记录。

PostgreSQL 集成测试另行使用 Compose 数据库中的临时 schema，测试退出时删除这些 schema；不复用或清空演示数据。n8n Runtime 检查使用固定 `event_id`，同事件重复执行返回同一工单；冲突和输入错误不会新建业务记录。

截图由真实 UI 生成：

- [ReturnFlow 正常工单闭环](assets/returnflow-closed-case.png)
- [ReturnFlow 实时业务总览](assets/returnflow-overview.png)
- [ReturnFlow 高额二人审批](assets/returnflow-second-approver.png)
- [ReturnFlow UNKNOWN 安全暂停与恢复](assets/returnflow-unknown-before-reconcile.png)、[权威查询证据](assets/returnflow-unknown-recovered.png)
- [n8n Return Intake 节点图](assets/n8n-01-return-intake.png)
- [n8n Operations Digest 节点图](assets/n8n-02-operations-digest.png)
- [n8n 定时摘要执行记录](assets/n8n-02-scheduled-execution.png)
- [Mailpit 摘要收件箱](assets/mailpit-summary-inbox.png)

## 尚未验证 / 边界

- 真实每日计划已观察一次：2026-10-10 09:00:53（Asia/Shanghai）n8n 执行成功并由 Mailpit 收件。单次成功不证明长期调度可靠性；未连接真实 SMTP，也未验证 SMTP 重试的 exactly-once 交付（本系统不作此承诺）。
- Playwright 浏览器端到端流程通过本地 Compose 前端/API 运行在 PostgreSQL 演示库上；随机生成的合成测试工单会保留在命名卷中。PostgreSQL 集成测试则使用每次单独创建、结束后清理的临时 schema。
- 未连接真实邮件服务或支付服务。Mailpit 与 Fake Payment 均为本地服务，不会产生外发邮件或真实退款。
- owner、短期 bootstrap API key 与运行时凭据保存在被 Git 忽略的 `.local/` 文件及本地 n8n 加密卷中；工作流 JSON 与截图不含秘密。新建/重置 volume 后重跑 `scripts/start-demo.ps1` 自动恢复 owner、凭据和已发布工作流；需要 Docker Desktop、Node.js 24+、npm，以及首次依赖/镜像拉取时的网络。
- [`BASELINE.md`](BASELINE.md) 是首次实施前的历史基线，其中的“Docker 不可用 / n8n 未运行”只描述当时状态；当前运行时证据以本文件为准。
