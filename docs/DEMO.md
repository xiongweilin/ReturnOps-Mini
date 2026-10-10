# ReturnFlow 本地演示剧本

## 1. 启动与访问

在 Windows PowerShell 7 中：

```powershell
.\scripts\start-demo.ps1
```

首次启动自动创建忽略的 `.env` 并生成本地随机密钥；演示不需要把密钥复制到浏览器、工作流 JSON 或录屏。常用页面：

- 前端：<http://127.0.0.1:4173>
- API 文档：<http://127.0.0.1:8000/docs>
- n8n：<http://127.0.0.1:5678>（首次设置 owner）
- Mailpit：<http://127.0.0.1:8025>

## 2. 种子数据

演示身份选择「客服 / 仓库 / Finance A / Finance B / 管理员」。种子至少覆盖以下路径：

| 订单 | 初始状态 | 演示点 |
|---|---|---|
| `DEMO-ORDER-INTAKE-001` | 待客服审核 | n8n 可重复投递同一 `event_id`，API 返回同一工单 |
| `DEMO-ORDER-REJECTED-001` | 已拒绝 | 客服拒绝和原因留痕 |
| `DEMO-ORDER-WAREHOUSE-001` | 待仓库验货 | 收货/验货权限边界 |
| `DEMO-ORDER-FINANCE-001` | 待财务审批 | 正常审批路径 |
| `DEMO-ORDER-HIGH-VALUE-001` | 第一笔财务审批已记账 | Finance A 不再显示第二次「审批退款」；Finance B 可用相同金额审批 |
| `DEMO-ORDER-CLOSED-001` | 已结案 | 正常退款证据、对账与审计时间线 |

`seed-demo.ps1` 可以重复执行。已有样例不会不断复制；新建的样例仍全部是合成数据。

## 3. 浏览器端到端测试

先启动 ReturnFlow 栈，然后：

```powershell
cd frontend
npm ci
npx playwright install chromium
$env:RETURNFLOW_FRONTEND_URL = 'http://127.0.0.1:4173'
$env:SAVE_DEMO_SCREENSHOTS = '1'
npm run e2e:typecheck
npm run test:e2e
```

测试创建唯一虚构订单，完成客服审核、仓库收货与验货、财务审批、Fake Payment、对账和结案；第二个测试断言高额退款必须由不同财务身份完成第二次审批。截图保存至 `docs/assets/`。

## 4. Webhook 幂等演示

在 n8n 导入 Intake 工作流并绑定凭证后，以相同内容和相同 `event_id` 重复投递。预期：

- 返回相同 `caseRef`，租户内只有一张工单；
- 相同幂等键改成不同请求体时，返回冲突，不覆盖原业务事实；
- API 出错时 n8n 用明确错误响应结束，不在 n8n 中直接改数据库或补发退款。

也可用受限的本地集成检查一次覆盖拒绝、校验、建单、重放和冲突路径：

```powershell
cd frontend
$env:RUN_N8N_INTEGRATION = '1'
npm run test:n8n
Remove-Item Env:RUN_N8N_INTEGRATION
```

测试固定使用合成事件 `returnflow-n8n-runtime-v1` 和 loopback Production URL；多次运行会重放同一工单，不会重复建单。无效/冲突/未授权请求不会得到成功响应。

## 5. 丢失 ACK 与 UNKNOWN 恢复

```powershell
.\scripts\run-unknown-demo.ps1 -OrderRef DEMO-ORDER-UNKNOWN-002
```

该命令暂停后台 worker，用一次性、按事件 ID 锁定的执行器处理指定退款。Fake Payment **已保存退款**，同步响应延迟到客户端超时以后，且不会发送 Webhook。执行结果将打印合成工单编号和 `refund_unknown`，不会打印 token。

在 Finance 工作区：

1. 打开「异常与对账」，找到指定的 `DEMO-ORDER-UNKNOWN-NNN`。
2. 验证页面显示 `支付结果未知`、最近异常为超时、派发次数为 1，且没有自动重试按钮。
3. 点击「查询支付方状态」。应读取 Fake Payment 已保存的成功记录，以 provider reference 与幂等键为依据补充证据并转成 `REFUNDED`。
4. 点击「确认对账完成」，再「结案」。审计记录应保留 `refund.outcome_unknown`、权威查询、`return.reconciled` 与 `return.closed`。

要让浏览器自动验收同一恢复流程，启动演示栈并完成上述脚本后执行：

```powershell
cd frontend
$env:RETURNFLOW_FRONTEND_URL = 'http://127.0.0.1:4173'
$env:RETURNFLOW_UNKNOWN_ORDER_REF = 'DEMO-ORDER-UNKNOWN-002'
$env:RUN_FAULT_E2E = '1'
npm run test:e2e:fault
```

`-OrderRef` 只接受 `DEMO-ORDER-UNKNOWN-NNN` 格式，用于在隔离演示环境多次运行时选择不同的合成订单号；它不会向公开 API 开放任意故障参数。

对尚处于 UNKNOWN 的同一 `OrderRef` 重复运行不会再次派发；完成恢复或结案后，再演示请选一个新的 `DEMO-ORDER-UNKNOWN-NNN`。只有需要清空全部本地样例时才使用带确认的 `reset-demo.ps1`。

## 6. 邮件摘要与终止

在 n8n 中手动运行 Operations Digest 工作流，然后在 Mailpit 查看 `operations@demo-store.example`。默认日程为 `Asia/Shanghai` 09:00；首次导入后先手动测试，再发布工作流。要重复验证自动调度，在 09:00 前保持本地栈运行，随后在该工作流的 **Executions** 中检查 `Succeeded` 执行并在 Mailpit 确认对应邮件。当前本地实例已于 2026-10-10 09:00:53 实际运行成功一次，详情见 [`TEST-EVIDENCE.md`](TEST-EVIDENCE.md)。摘要中的待办与角色来自 ReturnOps 当前 API 数据。

```powershell
.\scripts\verify-demo.ps1
.\scripts\stop-demo.ps1
```

停止保留命名卷。如确实要删除所有 ReturnFlow 演示状态，运行：

```powershell
.\scripts\reset-demo.ps1
```

该脚本要求准确输入 `RESET-RETURNFLOW` 才会执行 `docker compose down --volumes --remove-orphans`，并删除本地自动化 token 文件。此步骤不可逆地清空本项目演示数据；不要在任何真实/共享环境运行。
