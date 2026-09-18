# Fault lab：把「未知」放回真实网络边界

这个目录不是压测工具，而是一组可复现的失败实验：让 `src/` 里那些抽象判断（超时预算、结果未知、幂等、对账、事务边界）在真实进程、真实网络、真实数据库上产生可观察后果。

```text
docker compose -f faultlab/docker-compose.faultlab.yml up -d --build   # postgres / payment / toxiproxy / api
uv run python faultlab/scenarios.py                                   # 全部场景
uv run python faultlab/scenarios.py --scenario ack-lost               # 单个场景
docker compose -f faultlab/docker-compose.faultlab.yml down -v
```

## 场景与它各自证明什么

| 场景 | 注入方式 | 断言的不变量 |
|---|---|---|
| `payment-latency` | Toxiproxy 给支付代理加 2000ms 延迟 | 上游慢但仍在 3s 客户端预算内时退款正常完成 |
| `ack-lost` | provider 契约 `X-Simulate: timeout_after_processing` | 上游已持久化成功但 ACK 被扣住时，本地停在 `REFUND_UNKNOWN`，由对账收敛到 `REFUNDED`，且只有一次退款 |
| `reset-request` | Toxiproxy 在请求方向 `reset_peer` | 请求未到达上游时按可重试失败处理，重试后成功，provider 侧始终只有一条退款记录 |
| `postgres-latency` | Toxiproxy 给数据库代理加 250ms 延迟 | 数据库变慢时事务边界仍可用，且只产生一个退款意图 |

每个场景开始时都会清空 fault-lab 数据库：否则上一个场景留在 outbox 里的事件会先被 claim，断言就会指向别的案子（这是第一次跑这套实验时真实踩到的坑）。

## 性能契约

```text
thresholds                        含义
  http_req_failed rate<0.01       错误率
  http_req_duration p(95)<500     常规延迟
  http_req_duration p(99)<1000    尾部延迟
  duplicate_effect count==0       同一 Idempotency-Key 不得产生两个案子（比延迟重要）
```

阈值来自 `faultlab` 栈上的实测基线，不是拍的：先跑一次记录数值，再把它写成契约。

## 退化时怎么定位（而不是先看 diff）

```text
1) k6 先看分布：是 p99 恶化（尾部/锁）还是整体抬升（资源/连接池）
2) 数据库侧：pg_stat_activity（活跃会话与等待事件）、pg_locks、pg_stat_statements（最慢/最频繁语句）
3) 单条 SQL：EXPLAIN (ANALYZE, BUFFERS) 看是否退化成顺序扫描或 N+1
4) 进程侧：py-spy dump 看栈，docker stats 看 CPU/内存是否触顶
5) 只有证据指向具体资源或具体 SQL 之后，才回去看代码改动
```

预设的「变坏版本」（用于练诊断，不在 CI 里跑）：删掉复合索引、把事务范围扩大到外部 HTTP 调用、把连接池调到 5、在循环里发查询。每一个都能被上面的证据链区分开。

## 边界

- 容器只在需要时启停：`down -v` 会连同卷一起删除；
- provider 的模拟模式由 `X-Simulate` 头驱动（`RETURNOPS_PAYMENT_SIMULATION_MODE`），场景会显式设置并在结束时复位 `normal`；
- 该实验台不承担生产验证：它证明的是这些机制在真实边界上确实起作用。

