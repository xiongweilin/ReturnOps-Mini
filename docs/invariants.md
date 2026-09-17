# 正确性不变量

这个文件不是“设计愿望”，而是 ReturnOps Mini 的正确性边界。训练时，任何修改都应先回答：它影响了哪些不变量，证据是什么。

## 1. 租户隔离

- 每个 `ReturnCase`、`Approval`、`RefundAttempt` 都归属于一个 Organization。
- 面向用户的查询必须同时带 `organization_id` 条件。
- 用户访问其他租户已知对象 ID 时返回 404，而不是泄露对象存在性的 403。

训练问题：为什么只在 API router 做 tenant check 不够？后台 worker、service 内部调用是否可能绕过它？

## 2. 状态机

业务状态只能沿显式转换表前进。`CLOSED` 与 `REJECTED` 是终态。普通用户不能直接把 Case 写成 `REFUNDED`。

训练问题：测试“合法转换能成功”是否足以证明非法转换不会发生？还有哪些写路径可以直接改 status？

## 3. 乐观并发控制

状态更新必须把 `version` 放入同一条原子 UPDATE 的 WHERE 条件，而不是 Python 中先读再判断。

目标语义：两个并发请求读到 version=N 后，最多一个请求能把它推进到 N+1。

## 4. 退款金额

- 金额必须大于 0。
- 批准金额不能超过申请金额。
- 高额退款需要两个不同 finance 用户对相同金额批准。
- 第一次高额审批虽然不改变业务状态，也必须推进 version，避免两个并发用户都成为“第一审批人”。

## 5. 请求幂等

唯一键是 `(organization_id, scope, key)`。

相同 key + 相同 body：返回原结果。

相同 key + 不同 body：冲突。

并发相同请求：数据库唯一约束决定 winner，loser 不能变成通用 500。

## 6. 外部退款事实

`POST /refunds` 的网络超时不等于支付方失败。只要请求可能已经越过网络边界，就可能出现“支付方成功，本系统未知”。

因此：

- `UNKNOWN` 禁止盲目重新 POST；
- 必须通过 Webhook 或权威查询收敛；
- `REFUNDED` 必须有支付方证据；
- 已经 `SUCCEEDED` 的 attempt 不能因为晚到的 timeout handler 被降级成 `UNKNOWN`。

## 7. Webhook

- `(provider, event_id)` 唯一；
- 重复相同 event 应安全重放；
- 相同 event id 携带不同 payload 必须拒绝；
- Webhook 成功不能依赖同步 HTTP 请求是否收到 ACK。

## 8. Outbox

业务事务只负责记录“需要执行的外部动作”，worker 再越过网络边界。

需要区分：planned、processing、known failure、unknown outcome、done。

训练重点不是记住字段，而是能解释“数据库 commit 在哪里，网络调用在哪里，进程在两者之间 crash 会发生什么”。

## 9. 审计

关键业务动作应留下 actor、resource、action 与关键 metadata。审计不是业务事实的替代品，但应能帮助重建“谁在什么时候做了什么”。

## 10. 证据等级

不要把所有绿色测试视为同等证据：

- 纯函数测试：状态表、金额规则；
- SQLite 测试：HTTP 契约、基本事务；
- PostgreSQL 并发测试：unique/CAS/row lock 竞争；
- fake provider：网络失败、ACK 丢失、重复 Webhook；
- migration 回环：schema 可演进性。

每次 review 都要明确：当前证据证明了什么，没有证明什么。
