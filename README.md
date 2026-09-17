# ReturnOps Mini

ReturnOps Mini 是一个刻意控制规模、但保留真实工程风险的多租户退货退款 SaaS。它不是生产级电商平台，也不是“展示 AI 能写多少代码”的样板，而是一个用于训练**工程判断力**的小型完整产品。

第一版本已经提交，核心包含：多租户、RBAC、状态机、乐观并发控制、幂等、Outbox、退款外部调用、Webhook、UNKNOWN 结果、对账、审计、基础 API/控制台、中文训练文档与基础测试。

训练目标不是逐行背下全部代码，而是达到：能画出状态与数据流、能解释不变量由什么机制保证、能预测失败路径、能判断测试到底证明了什么，并能在 AI 生成修改后判断影响半径与验证方式。

## 使用顺序

1. 阅读 `docs/invariants.md`；
2. 阅读 `docs/ai-judgment-training.md`；
3. 运行基础测试；
4. 用 `docs/failure-lab.md` 做“先预测、再验证”；
5. 第二阶段再进入真实 PostgreSQL 并发与更严格故障注入。

## 快速启动

```bash
docker compose up --build -d
docker compose run --rm api python -m returnops.seed
```

打开 `http://localhost:8000/`，API 文档在 `/docs`。

## 第一版本验证

```bash
pytest -q -m 'not integration'
python -m compileall -q src tests alembic
```

CI 还会执行 Ruff 和 SQLite migration upgrade/downgrade/upgrade 回环。

## 核心原则

- 跨租户访问必须失败；
- 业务状态只能沿显式状态机转换；
- 并发状态更新使用 version CAS；
- 高额退款要求两个不同财务审批人；
- 相同 Idempotency-Key + 相同 body replay，相同 key + 不同 body 冲突；
- 支付方结果未知时禁止盲目重试；
- `REFUNDED` 必须来自支付方证据；
- Webhook 必须去重；
- AI 是追问者、反方 Reviewer、故障注入器和证据审查员，不是最终判断者。

完整说明见 `docs/`。
