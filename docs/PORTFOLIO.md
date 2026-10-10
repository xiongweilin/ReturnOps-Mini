# 作品集案例：ReturnFlow

## 业务背景

模拟一家中小型电商商户。退货退款需要客服确认资格、仓库收货验货、财务审批与对账；实际支付状态还可能在超时或 Webhook 延迟时不确定。

## 原始问题

跨团队信息容易分散在表格、聊天记录与支付后台；重复录入会产生重复工单；退款响应超时若被当成失败而直接重试，可能造成重复退款；财务难以从本地状态判断支付方的真实结果。

## 解决方案

用 n8n 接收外部退货事件并调用 ReturnOps API 建单；由 API 保存唯一业务状态、租户权限、审批、审计和 Outbox 退款意图；用 React 工作台给客服、仓库、财务展示真实待办和可执行操作。`REFUND_UNKNOWN` 不自动重试，财务先通过 Fake Payment 权威查询恢复事实，再对账和结案。

## 实际实现

- **业务状态与权限：**[`states.py`](../src/returnops/domain/states.py)、[`routes.py`](../src/returnops/api/routes.py)、[`returns.py`](../src/returnops/services/returns.py) 实现状态门禁、租户隔离、服务身份和业务操作；[`operator_queries.py`](../src/returnops/services/operator_queries.py) 提供真实运营总览、角色待办和异常列表。
- **退款可靠性：**[`outbox.py`](../src/returnops/services/outbox.py)、[`worker.py`](../src/returnops/services/worker.py)、[`payments.py`](../src/returnops/services/payments.py)、[`webhooks.py`](../src/returnops/services/webhooks.py) 与 [`reconciliation.py`](../src/returnops/services/reconciliation.py) 保留稳定退款意图、单次派发、Webhook 去重、外部证据核验及 UNKNOWN 恢复。
- **操作台：**[`frontend/src/App.tsx`](../frontend/src/App.tsx) 与 [`api.ts`](../frontend/src/api.ts) 实现中文总览、列表/搜索/筛选、详情、角色允许动作、金额最小单位提交和异常对账中心。
- **外围自动化：**[`01-return-intake.json`](../n8n/workflows/01-return-intake.json) 接单并传稳定幂等键；[`02-operations-digest.json`](../n8n/workflows/02-operations-digest.json) 汇总 API 返回的真实待办及负责角色后将信息性摘要交给 Mailpit。
- **部署与复现：**[`docker-compose.yml`](../docker-compose.yml) 编排 PostgreSQL、API、worker、前端、Fake Payment、n8n 与 Mailpit；[`scripts/`](../scripts/) 提供启动、种子、验证、停止、重置及 UNKNOWN 演示命令。

## 可验证结果

- 本地完整 Compose 栈运行；Python 全量测试 **49 passed**，其中包含 PostgreSQL integration 测试；Ruff、前端 production build、Lint 与 E2E 类型检查通过。
- Playwright 通过本地操作台完成正常退款闭环、高额不同审批人验证、UNKNOWN 权威查询恢复，以及客服身份无法审批的浏览器/API 验收。
- n8n **2.42.5** 两条工作流已在 Web UI 导入、凭据绑定并发布。生产 Intake Webhook 集成检查实测：无 Basic Auth 返回 401、无效请求返回 400、有效请求创建 `requested` 工单、相同事件重放返回同一工单、同幂等键改内容返回 409。
- 更新后的 Digest 手动执行成功；随后每日 09:00 Schedule Trigger 于 2026-10-10 09:00:53（Asia/Shanghai）实际触发，n8n 执行记录 ID `20` 显示 Succeeded（110 ms）。Mailpit 最新邮件包含 API 汇总的待处理工单、负责角色和下一步动作。
- 未删除卷而重启整个长驻 Compose 栈后，API 工单、Fake Payment 的权威退款记录（`post_count=1`）、n8n 发布状态和 Mailpit 邮件均保留；重启后的 Intake 集成检查与 Digest 手动发送仍成功。
- 界面及工作流截图：[总览](assets/returnflow-overview.png)、[正常闭环](assets/returnflow-closed-case.png)、[高额第二人审批](assets/returnflow-second-approver.png)、[UNKNOWN 暂停](assets/returnflow-unknown-before-reconcile.png)、[恢复证据](assets/returnflow-unknown-recovered.png)、[n8n Intake](assets/n8n-01-return-intake.png)、[n8n Digest](assets/n8n-02-operations-digest.png)、[n8n 定时执行成功](assets/n8n-02-scheduled-execution.png)、[Mailpit 收件箱](assets/mailpit-summary-inbox.png)。

逐项测试命令、持久化演示数据说明和证据边界见 [`TEST-EVIDENCE.md`](TEST-EVIDENCE.md)。

## 未验证效果与限制

- 没有真实企业客户试用数据，因此不能声称已经节省工时、降低财务差错率、提升采用率或验证长期维护成本。
- 未接入真实支付、SMTP、ERP 或客户个人信息；Fake Payment 与 Mailpit 仅在本地演示。
- 日报邮件采用普通 SMTP/Mailpit，不承诺 exactly-once。计划触发已实测一次；单次观测不代表长期调度可靠性。
- Demo Mode 仅供隔离本地演示，不是生产级身份认证。Playwright 与 n8n 集成检查会在持久化演示库留下合成订单。

## 设计取舍

1. **n8n 不拥有业务授权。**它做映射、幂等请求、只读摘要和通知；状态转换、角色权限、退款调用与审计只由 ReturnOps API 执行。
2. **保留 Outbox 与 `REFUND_UNKNOWN`。**外部调用发生后，客户端超时并不能证明支付失败。系统先暂停，财务以支付方权威记录核实，而不是重放不确定的退款。
3. **高额退款仍由不同财务用户审批同一金额。**阈值来自可配置规则，只是本演示商户策略，不代表通用企业标准。
4. **不引入 AIOS 整体运行时或独立工作流引擎。**现有 ReturnOps 已负责可靠业务核心，新增组件只为真实的前端和外围自动化需求服务。

## 演示讲述顺序

先展示总览与真实待办，再用客服/仓库/财务完成普通工单；接着展示高额退款第二人审批；最后运行 `scripts/run-unknown-demo.ps1` 展示单次派发后的 UNKNOWN、权威支付查询、对账与结案，收尾展示 n8n 两条工作流和 Mailpit。准确操作步骤见 [`DEMO.md`](DEMO.md)。
