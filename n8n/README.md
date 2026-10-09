# n8n 工作流

目标运行版本：**n8n 2.42.5**。Compose 使用固定版本标签，不使用 `latest`。工作流 JSON 使用 n8n 内置节点，导入后仍需绑定本地演示凭据。

## 工作流

| 文件 | 触发器 | 主要职责 |
|---|---|---|
| `workflows/01-return-intake.json` | Webhook `POST /webhook/return-intake` | 认证调用方、检查输入、映射 `ReturnCreate`、基于 `event_id` 设置稳定 `Idempotency-Key`、调用 ReturnOps API，并将创建/重放/拒绝结果返回调用方。 |
| `workflows/02-operations-digest.json` | 每日 09:00 Schedule Trigger；另有手动执行入口 | 查询 `/v1/overview` 的实时计数、负责人、下一步动作和待对账工单，生成摘要并通过 SMTP 发到 Mailpit。 |

Intake 工作流只在 API 返回含工单 ID 的业务响应时报告接受成功。重复相同事件会返回同一工单和 `replayed: true`；相同事件 ID 的内容冲突会返回 ReturnOps 的冲突信息。工作流不直接访问数据库，不批准退款，也不触发支付。

## 首次导入与凭据

在 n8n 编辑器选择 **Workflows → Import from File**，依次导入两个 JSON 文件。导入后，为节点选择或创建以下凭据；凭据内容不要写入工作流 JSON。

1. 在 `01-return-intake` 的 **Return Intake Webhook** 节点选择 Webhook Basic Auth 凭据，例如 `ReturnFlow Intake Caller`。外部演示调用方必须使用该凭据。
2. 两个 **HTTP Request** 节点都选择 `Custom Auth` 凭据，例如 `ReturnOps Demo API`。凭据 JSON 包含两个请求头：`Authorization`（Bearer token）和 `X-Organization-ID`。本地 Seed 在 `.local/automation-token.txt` 保存自动化用户 Token；组织 ID 由 Seed 输出。该账号只能建立工单和读取摘要，API 会拒绝审批、支付和对账操作。
3. `02-operations-digest` 的 **Send Summary to Mailpit** 节点选择 SMTP 凭据，例如 `Mailpit SMTP`：主机 `mailpit`、端口 `1025`、不启用 TLS，用户名和密码留空。邮件收件地址使用虚构的 `operations@demo-store.example`。

完成凭据绑定后保存工作流。Intake 测试时，打开 Webhook 节点的 Test URL 并点击 **Listen for Test Event**；验证通过后发布工作流，再使用 Production URL。Schedule Trigger 只有在工作流发布后才会按计划执行；它使用 Compose 中 `GENERIC_TIMEZONE` 配置的时区（默认 `Asia/Shanghai`），也可以从编辑器手动执行摘要工作流。

## 本地 Intake 集成验收

完整启动 Compose、导入并发布 Intake、绑定 Webhook 与 `Custom Auth` 凭据后，可运行以下本地集成检查：

```powershell
cd frontend
$env:RUN_N8N_INTEGRATION = '1'
npm run test:n8n
Remove-Item Env:RUN_N8N_INTEGRATION
```

脚本只允许访问 loopback Production URL，并从被忽略的 `.local/n8n-intake-credentials.json` 读取 Basic Auth；不会打印凭据。它验证 401 未授权、400 无效输入、201 建单、同事件重放返回相同工单，以及同幂等键不同内容返回 409。固定合成事件可重复运行，不会产生重复工单；演示库重置后可重建同一合成样本。

工作流文件中的 HTTP 请求地址使用 Compose 服务名 `api`。从容器外部调用时，应使用 n8n 显示的 Test 或 Production Webhook URL。演示界面和编辑器应只在本机回环地址访问。

## 当前本地验收

当前 Compose n8n 2.42.5 实例已通过 Web UI 导入、凭据绑定并发布两个工作流。Production Webhook 的运行时集成检查已实测未授权、无效、创建、重放及冲突分支；实际建单保持 `requested`，没有批准退款。更新后的 Operations Digest 在容器重启前后均通过手动触发，Mailpit 邮件包含从 API 查询的角色待办和下一步动作。对应节点图和收件箱截图见 [`docs/assets/`](../docs/assets/)，完整结果与限制见 [`docs/TEST-EVIDENCE.md`](../docs/TEST-EVIDENCE.md)。

工作流与凭据保存在本地 n8n volume 中，不会随仓库导出 JSON 提交。新建或重置 volume 后仍需按上一节重新初始化和绑定凭据；本地自动化 token、owner 登录和 Webhook Basic Auth 值只放在被忽略的 `.local/` 文件中。

## 邮件结果语义

摘要邮件是信息性通知。多次手动执行或重复调度可能产生多封相同日期的摘要；SMTP 超时也可能发生在 Mailpit 已接收邮件之后。n8n 记录执行结果，人工重跑可能重复发送，因此此流程不声称 exactly-once 邮件交付。

## 官方资料

- [n8n 工作流导入与导出](https://docs.n8n.io/build/manage-workflows/export-and-import/)
- [Webhook 节点与测试/生产 URL](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)
- [Respond to Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook/)
- [Schedule Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/)
- [Send Email](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.sendemail/)
