# ReturnOps Mini

[![CI](https://github.com/xiongweilin/ReturnOps-Mini/actions/workflows/ci.yml/badge.svg)](https://github.com/xiongweilin/ReturnOps-Mini/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white&style=flat-square)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-required-4169E1?logo=postgresql&logoColor=white&style=flat-square)
![License](https://img.shields.io/github/license/xiongweilin/ReturnOps-Mini?style=flat-square)

ReturnOps Mini 是一个刻意控制规模、但保留真实工程风险的多租户退货退款 SaaS。它不是生产级电商平台，也不是“展示 AI 能写多少代码”的样板，而是一个用于训练**工程判断力**的小型完整产品。

这个仓库从 `commerce-orchestrator` 与 `administrative-orchestrator` 中抽取了最值得学习的可靠性问题：租户隔离、角色权限、状态机、乐观并发控制、幂等、Outbox、外部副作用、结果未知、Webhook 去重、对账、迁移与审计。与此同时，它主动删除了 DBOS、Kafka、Redis、通用工作流引擎、CQRS 等会遮蔽基本机制的基础设施。

训练目标不是逐行背下全部代码，而是达到下面的能力：

- 能画出完整状态与数据流；
- 能说清每条核心不变量由什么代码和数据库约束保证；
- 能在看到实现之前预测主要失败路径；
- 能判断一个“测试通过”的结论到底证明了什么、没有证明什么；
- 能在 AI 生成修改后判断影响半径、验证方式与回滚风险；
- 能处理“外部系统实际上成功，但本系统不知道”的不确定现实。

如果完成训练后，你仍然只能说“AI review 说没问题”，那这个项目的训练目标没有达成。最终目标是：**AI 主要负责搜索、生成、质疑和制造故障，你本人负责定义正确性、选择证据并做最终判断。**

## 一、产品是什么

一个商户团队用 ReturnOps Mini 处理退货与退款。系统有四类角色：

- `customer_service`：创建退货、审核退货资格；
- `warehouse`：确认收货、检查商品；
- `finance`：批准退款、处理不确定结果、完成对账与关闭；
- `admin`：租户管理角色；它可以执行部分业务动作，但不是“万能绕过所有规则”的超级用户。

正常业务状态：

```text
REQUESTED
  -> AUTHORIZED
  -> RECEIVED
  -> INSPECTED
  -> REFUND_APPROVED
  -> REFUND_PENDING
  -> REFUNDED
  -> RECONCILED
  -> CLOSED
```

外部退款执行可能进入异常分支：

```text
REFUND_PENDING
  -> REFUND_UNKNOWN
  -> NEEDS_RECONCILIATION
  -> REFUNDED
```

其中最重要的状态是 `REFUND_UNKNOWN`。一次 HTTP 超时只能证明“本系统没收到确定回复”，不能证明支付方没有执行退款。如果此时自动重新 POST，很可能造成重复退款。因此核心规则是：**未知结果不能盲目重试，必须通过 Webhook 或权威查询重新获得事实。**

## 二、核心不变量

完整清单见 [`docs/invariants.md`](docs/invariants.md)。最重要的规则包括：

1. 每条业务记录只属于一个 Organization。
2. 用户不能读取或修改其他 Organization 的退货记录。
3. 跨租户对象 ID 对调用者表现为 `404`。
4. 业务状态只能通过声明过的状态机转换。
5. 并发状态写入必须使用 `version` 的 compare-and-swap。
6. 退款金额必须大于 0，且不能超过申请金额。
7. 高额退款需要两个不同的财务用户对相同金额批准。
8. 一个退款意图使用稳定的 provider idempotency key。
9. 外部结果未知时禁止自动再次发起退款。
10. `REFUNDED` 必须由支付方证据产生。
11. 同一个 Webhook event 最多影响一次业务状态。
12. `CLOSED` 与 `REJECTED` 为终态。

审查 AI 代码时，首先检查“这次改动碰到了哪些不变量”，而不是先看变量名或代码风格。

## 三、架构

```text
浏览器 / API Client
        |
        v
FastAPI API  ---- 认证 + 租户成员关系
        |
        +---- Return Service ---- PostgreSQL
        |       |                   | ReturnCase / Approval / Audit
        |       |                   | IdempotencyRecord
        |       +---- Outbox -------| OutboxEvent
        |
        +---- Payment Webhook ------| WebhookReceipt
                                    |
Worker <---- FOR UPDATE SKIP LOCKED-+
  |
  v
Fake Payment Provider（独立进程 + SQLite）
  |
  +---- 同步 HTTP 响应
  +---- Webhook
  +---- 用于对账的权威查询
```

本项目故意不使用 DBOS、Kafka、Redis、CQRS、Event Sourcing 或通用工作流引擎。原因不是这些技术不好，而是当前训练目标是看清：哪一步是数据库事实，哪一步只是计划执行，哪一步已经越过网络边界，哪一步只能得到未知，以及哪一个机制真正阻止并发重复写入。

## 四、目录与阅读顺序

```text
src/returnops/
  api/                 HTTP 边界、认证与依赖注入
  domain/              状态、角色、转换规则、不变量
  services/
    returns.py          核心业务动作 + version CAS
    idempotency.py      请求 replay / conflict / 并发竞争
    outbox.py           durable event、claim、lease、retry
    payments.py         外部退款意图、结果与证据
    webhooks.py         Webhook 去重与成功确认
    reconciliation.py  UNKNOWN 的权威查询与收敛
    worker.py           Outbox 消费与网络边界
    tenancy.py          用户与 Organization 成员关系
  models.py             SQLAlchemy 持久化模型
  static/index.html     极薄的浏览器操作台

src/fake_payment/
  app.py                可故障注入的支付方模拟器

tests/
  integration/          必须依赖真实 PostgreSQL 的并发测试

docs/
  invariants.md
  failure-lab.md
  ai-judgment-training.md
```

建议第一次阅读顺序：`docs/invariants.md` → `domain/states.py` → `services/returns.py` → `services/idempotency.py` → `services/worker.py` → `services/payments.py` → `services/webhooks.py` → `services/reconciliation.py`，最后再回看 model、API 和测试。

## 五、快速启动

需要 Docker 与 Compose v2：

```bash
docker compose up --build -d
docker compose run --rm api python -m returnops.seed
```

seed 命令会输出一个 Organization ID 和多种角色的 demo bearer token。打开 `http://localhost:8000/`，在操作台中粘贴 Organization ID 与对应角色 token 即可按角色推进流程。

服务地址：API `http://localhost:8000`，API health `http://localhost:8000/health`，Fake payment `http://localhost:8090/health`。

## 六、测试与证据等级

快速测试：

```bash
pytest -q -m 'not integration'
```

真实 PostgreSQL 并发测试：

```bash
export RETURNOPS_TEST_DATABASE_URL='postgresql+psycopg://returnops:returnops@localhost:5432/returnops'
pytest -q -m integration
```

不同测试只能证明不同层面的事情：纯函数单测证明状态机与金额规则；SQLite API 测试证明 HTTP 契约、租户过滤和一般事务行为；PostgreSQL 并发测试证明 unique index 等待、row lock、CAS 竞争等真实语义；fake provider 实验证明 ACK 丢失、重复 Webhook、外部已成功但本地未知；migration round-trip 验证 schema 演进。

“测试全绿”不是完整结论。正确问题应是：**这组证据具体证明了哪些不变量？还有哪些状态空间没有覆盖？**

## 七、如何使用 AI 提升工程判断力

完整方法见 [`docs/ai-judgment-training.md`](docs/ai-judgment-training.md)。不要把仓库丢给 AI 后只说“全面 review”。推荐固定使用这个训练循环：

```text
选择一个不变量
↓
你先画状态/数据路径
↓
你先预测 3~5 个失败场景
↓
让 AI 只提问，不给答案
↓
你回答并给出“需要什么证据”
↓
AI 扮演攻击者制造故障或反例
↓
运行测试 / PostgreSQL / fake provider / migration
↓
比较“预测”与“真实结果”
↓
记录失败模式和以后自动化规则
```

AI 在训练里主要扮演四个角色：追问者、反方 Reviewer、故障注入器、证据审查员。最终决定“是否足够正确”的人仍然是你。

推荐提示词：

```text
你现在不是代码生成器，而是我的软件工程导师。
目标是训练我的判断能力，不要直接给结论。

本轮只围绕这个不变量：<填入一条 invariant>。

规则：
1. 先连续问我问题，一次只问一个；
2. 如果我的回答缺少前提、失败路径或并发语义，继续追问；
3. 不要因为代码或测试名字看起来合理就默认它正确；
4. 要求我明确：事实、推测、风险、需要的证据；
5. 在我给出完整判断之前，不要给最终答案；
6. 最后再给出最多 3 个我漏掉的关键点，并说明应怎样验证。
```

每次改动合并前，你本人必须回答：这次修改碰到了哪些不变量？改变了哪些状态、数据库行或外部副作用？最危险的失败点是什么？哪个测试或实验能证明它？如果该证明失败，系统最坏会发生什么？

## 八、建议训练阶段

阶段 A：纯状态判断，只研究 `domain/states.py` 与状态机测试。

阶段 B：数据库不变量，研究 tenant ownership、金额约束、CAS、高额双审批。

阶段 C：请求语义，研究 Idempotency-Key、replay、conflict、20 并发 caller。

阶段 D：外部现实，研究 worker、fake provider、Webhook、UNKNOWN、reconciliation。

阶段 E：系统演进，修改审批规则、增加字段、做 migration、保持旧数据兼容。

## 九、第一版本的已知边界

这是训练项目，不是可直接部署到真实金融/电商生产环境。第一版本重点是完整性与可验证性，不覆盖真实 PII 合规、生产密钥管理、复杂税务/多币种/部分退款、SSO、完整前端体验、生产级监控/SLO、多区域容灾。

第一版本本地已验证非 integration 测试与 migration round-trip；真实 PostgreSQL 并发语义由 CI/integration 测试继续验证。第二阶段会专门围绕这些未证明边界做硬化。
