# 录屏提纲（约 4–5 分钟）

成品：[播放真实 UI 录制](assets/returnflow-demo.mp4) · [简体中文字幕](assets/returnflow-demo.zh-CN.srt)。如需重新录制，在本地启动 Docker/n8n 后运行 `scripts/record-demo-video.ps1`；录制会创建合成工单/UNKNOWN 案例并向本机 Mailpit 发送摘要，原始视频和 TTS 暂存于 Git 忽略的 `.local/`。

## 录屏前

1. `pwsh` 运行 `scripts/start-demo.ps1`，确认前端、API 和两个已发布 n8n 工作流健康。
2. 新建 n8n volume 无须人工导入/绑定；启动脚本已自动配置 owner、credentials 和 workflows。若完整初始化失败，先修复提示中的依赖/配置再重跑，不要删除演示卷。
3. Mailpit 用于查看演示邮件；检查屏幕没有真实个人信息、密码、token、`.env` 内容或数据库凭证。
4. 使用种子生成的虚构订单；不要在录屏里打开 `.local/automation-token.txt`。

## 时间线

| 时间 | 画面 / 旁白 |
|---|---|
| 0:00–0:30 | 业务总览：客服待办、仓库待办、财务待办、退款异常和已结案数量。说明所有样例均为虚构。 |
| 0:30–1:15 | 以客服身份创建并审核新申请；切到仓库，确认收货并记录验货。指出每个操作都受服务端角色与版本约束。 |
| 1:15–2:00 | Finance A 审批普通金额；等 Fake Payment 返回成功，查看 provider reference、证据、Outbox 执行次数和审计。 |
| 2:00–2:35 | 打开高额样例：Finance A 第一笔审批后看不到再次审批按钮；切到 Finance B，检查默认金额与第二人记录。 |
| 2:35–3:35 | 运行 `scripts/run-unknown-demo.ps1 -OrderRef DEMO-ORDER-UNKNOWN-002`；在异常中心展示 `REFUND_UNKNOWN`、一次派发、无重试；点击权威查询，显示 Fake Payment 成功证据。 |
| 3:35–4:05 | Finance 对账并结案，展示审计时间线中未知、查询、对账和结案的顺序。 |
| 4:05–4:35 | 展示 n8n Intake/Digest 节点图、Production Webhook 创建的合成申请、一次成功的 09:00 Schedule Trigger 执行记录，以及 Mailpit 中的摘要邮件。若录制环境不能运行 Docker/n8n，则跳过这些运行时画面并说明 JSON 导出与凭据绑定边界。 |
| 4:35–5:00 | 总结：API 管业务事实；n8n 管外围自动化；超时后宁可暂停并核查，不猜测支付结果或盲目重试。 |

## 建议截图清单

- ReturnFlow 业务总览：[`assets/returnflow-overview.png`](assets/returnflow-overview.png)
- ReturnFlow 已结案详情：[`assets/returnflow-closed-case.png`](assets/returnflow-closed-case.png)
- Finance B 高额第二人审批：[`assets/returnflow-second-approver.png`](assets/returnflow-second-approver.png)
- UNKNOWN 安全暂停与权威查询恢复：[`assets/returnflow-unknown-before-reconcile.png`](assets/returnflow-unknown-before-reconcile.png)、[`assets/returnflow-unknown-recovered.png`](assets/returnflow-unknown-recovered.png)
- n8n Intake 工作流节点图：[`assets/n8n-01-return-intake.png`](assets/n8n-01-return-intake.png)
- n8n Operations Digest 节点图：[`assets/n8n-02-operations-digest.png`](assets/n8n-02-operations-digest.png)
- Mailpit 实际摘要收件箱：[`assets/mailpit-summary-inbox.png`](assets/mailpit-summary-inbox.png)
