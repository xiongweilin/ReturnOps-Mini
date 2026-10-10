# n8n 工作流

目标运行版本：**n8n 2.42.5**。Compose 使用固定版本标签，不使用 `latest`。工作流 JSON 使用 n8n 内置节点；首次启动由 `scripts/start-demo.ps1` 自动初始化 owner、创建本地凭据、导入/更新 JSON 并发布工作流。

## 工作流

| 文件 | 触发器 | 主要职责 |
|---|---|---|
| `workflows/01-return-intake.json` | Webhook `POST /webhook/return-intake` | 认证调用方、检查输入、映射 `ReturnCreate`、基于 `event_id` 设置稳定 `Idempotency-Key`、调用 ReturnOps API，并将创建/重放/拒绝结果返回调用方。 |
| `workflows/02-operations-digest.json` | 每日 09:00 Schedule Trigger；另有手动执行入口 | 查询 `/v1/overview` 的实时计数、负责人、下一步动作和待对账工单，生成摘要并通过 SMTP 发到 Mailpit。 |

Intake 工作流只在 API 返回含工单 ID 的业务响应时报告接受成功。重复相同事件会返回同一工单和 `replayed: true`；相同事件 ID 的内容冲突会返回 ReturnOps 的冲突信息。工作流不直接访问数据库，不批准退款，也不触发支付。

## 首次部署与自动绑定

从全新 checkout/volume 启动时只需运行：

```powershell
.\scripts\start-demo.ps1
.\scripts\verify-demo.ps1
```

`start-demo.ps1` 自动完成 Compose 构建/启动、可重复业务种子和 n8n 初始化。首次缺少前端工具依赖时按 `package-lock.json` 执行 `npm ci` 并安装 headless Chromium；随后自动创建 owner、生成 Webhook Basic Auth、生成 90 天本地 bootstrap API key，并通过 n8n public REST API 创建/更新凭据及两条工作流、绑定凭据并发布。再次运行时按名称 upsert，不重复导入或重复创建资源；如果某一步失败，服务和卷保留，可直接重跑脚本恢复，不会清空数据。

bootstrap API key 只保存在 Git 忽略的 `.local/n8n-api-key.txt`，只用于本机创建/更新 n8n 配置；到期或新建 n8n volume 后会重新创建。它不会进入工作流 JSON或运行时调用。工作流仅引用凭据 ID/名称：`ReturnFlow Intake Caller`、`ReturnOps Demo API` 和 `Mailpit SMTP`。自动化用户 token 从 `.local/automation-token.txt` 读取，组织 ID 由 Seed 写入 `.local/organization-id.txt`；它只能建立工单和读取摘要，API 会拒绝审批、支付和对账。SMTP 只连 Compose 网络内的 `mailpit:1025`，不发往外部。

控制边界：人工只负责启动本地 demo；脚本执行 owner/凭据/导入/发布，n8n 数据卷保存发布状态，最后由运行时检查验证 webhook 和 Mailpit。若出现同名重复工作流/凭据，脚本会停止并要求先在本地 n8n 清理重复项，不会擅自删除用户配置。工作流自动化账号仍受 ReturnOps RBAC 限制，不能完成财务审批或触发退款。

n8n API key 使用自托管 public REST API（见[n8n API authentication](https://docs.n8n.io/connect/n8n-api/authentication/)）；密钥绝不写入仓库或 workflow JSON。

手工从编辑器导入/绑定只作为排障备用，不是新环境验收步骤。`Schedule Trigger` 只有发布后才按 `GENERIC_TIMEZONE` 配置的时区运行（默认 `Asia/Shanghai`）；也可以从编辑器手动执行摘要。

## 本地 Intake 集成验收

`scripts/start-demo.ps1` 会在完整启动 Compose 后自动导入/发布 Intake 并绑定 Webhook 与 `Custom Auth` 凭据。需要验证运行时分支时，可运行：

```powershell
cd frontend
$env:RUN_N8N_INTEGRATION = '1'
npm run test:n8n
Remove-Item Env:RUN_N8N_INTEGRATION
npm run test:n8n:digest
```

脚本只允许访问 loopback Production URL，并从被忽略的 `.local/n8n-intake-credentials.json` 读取 Basic Auth；不会打印凭据。它验证 401 未授权、400 无效输入、201 建单、同事件重放返回相同工单，以及同幂等键不同内容返回 409。固定合成事件可重复运行，不会产生重复工单；演示库重置后可重建同一合成样本。

工作流文件中的 HTTP 请求地址使用 Compose 服务名 `api`。从容器外部调用时，应使用 n8n 显示的 Test 或 Production Webhook URL。演示界面和编辑器应只在本机回环地址访问。

## 当前本地验收

当前 Compose n8n 2.42.5 实例已由 `start-demo.ps1` 自动创建/更新凭据、upsert 并发布两个工作流。Production Webhook 的运行时集成检查已实测未授权、无效、创建、重放及冲突分支；实际建单保持 `requested`，没有批准退款。Operations Digest 手动触发与 Mailpit 投递通过；随后 2026-10-10 09:00:53（Asia/Shanghai）每日计划实际触发，n8n 执行记录 ID `20` 显示 Succeeded（110 ms），Mailpit 收到来自实时 API 查询的角色待办和下一步动作。对应工作流与运行证据截图见 [`docs/assets/`](../docs/assets/)，完整结果与限制见 [`docs/TEST-EVIDENCE.md`](../docs/TEST-EVIDENCE.md)。

工作流与凭据保存在本地 n8n volume 中，不会随仓库导出 JSON 提交。新建或重置 volume 后重跑 `scripts/start-demo.ps1` 即会重新初始化 owner、创建本地凭据并发布工作流；本地自动化 token、owner 登录、bootstrap API key 和 Webhook Basic Auth 值只放在被忽略的 `.local/` 文件中。

## 邮件结果语义

摘要邮件是信息性通知。多次手动执行或重复调度可能产生多封相同日期的摘要；SMTP 超时也可能发生在 Mailpit 已接收邮件之后。n8n 记录执行结果，人工重跑可能重复发送，因此此流程不声称 exactly-once 邮件交付。

## 官方资料

- [n8n 工作流导入与导出](https://docs.n8n.io/build/manage-workflows/export-and-import/)
- [Webhook 节点与测试/生产 URL](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)
- [Respond to Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook/)
- [Schedule Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/)
- [Send Email](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.sendemail/)
