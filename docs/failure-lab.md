# 故障实验室

这份文档用于训练“先预测，再验证”。不要先让 AI 告诉你答案。

每次实验固定写四项：

1. 我预测系统会发生什么；
2. 我的预测依赖哪些前提；
3. 用什么证据验证；
4. 真实结果与预测哪里不同。

## 实验 1：stale version

两个客户端都读到 version=2，然后同时尝试推进同一 Case。

先回答：最多几个能成功？哪一条 SQL 条件提供保证？loser 会留下审计记录吗？

## 实验 2：同一个 Idempotency-Key 并发到达

让多个请求同时提交完全相同的 body 和 key。

先回答：为什么它们可能都先看到“记录不存在”？真正串行化发生在哪一步？loser 应返回什么？

## 实验 3：跨租户对象 ID

A 租户创建 Case，B 租户拿到真实 Case ID 后读取。

先回答：应该是 403 还是 404？如果只在 router 检查 tenant，service 是否仍安全？

## 实验 4：高额双人审批

两个 finance 用户同时基于同一个 version 提交“第一审批”。

先回答：能否出现两条 first approval？为什么第一次审批必须推进 version？

## 实验 5：执行前明确失败

设置 `RETURNOPS_PAYMENT_SIMULATION_MODE=503_before_processing`。

先回答：这是 known failure 还是 unknown？为什么允许重试？重试是否应复用 provider idempotency key？

## 实验 6：支付方已成功但 ACK 丢失

设置 `RETURNOPS_PAYMENT_SIMULATION_MODE=timeout_after_processing`。

支付方先保存退款成功，再让 HTTP 客户端超时。

先回答：Case 应进入什么状态？worker 能否自动再次 POST？用什么证据才能最终进入 REFUNDED？

## 实验 7：Webhook 比 timeout handler 更早提交

顺序可能是：支付方成功 → Webhook 到达并把 attempt 标成 SUCCEEDED → 原 HTTP 请求超时。

先回答：晚到的 timeout handler 能否把 SUCCEEDED 降级为 UNKNOWN？应写什么回归测试证明规则？

## 实验 8：重复 Webhook

同一个 event id 连续发送两次。

先回答：数据库哪一个约束负责去重？为什么还要比较 payload hash？

## 实验 9：worker 在支付成功后、本地 commit 前 crash

支付方已经退款，但本地事务没有提交成功状态。

先回答：lease 到期后 worker 再次看到事件会怎样？为什么稳定的 provider idempotency key 很重要？

## 实验 10：一年后的规则变化

把规则改成：小额一个审批，大额两个不同审批人。假设数据库已有 10 万条历史记录。

先不要写代码，先设计 migration 顺序、历史数据解释、旧 API 兼容窗口、部署顺序和 rollback。

完成这些实验时，目标不是“找到 bug 数量最多”，而是让你越来越能提前预测系统在哪些地方会坏。
