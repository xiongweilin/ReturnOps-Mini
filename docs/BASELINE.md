# ReturnFlow 开发基线

记录日期：2026-10-09

> 历史记录：本文只描述首次实施前的仓库与运行环境；后续 Docker / PostgreSQL / n8n 实际验收结果见 [`TEST-EVIDENCE.md`](TEST-EVIDENCE.md)。

## Git 基线

- 开始检查时，工作树在 `main` 分支干净，基线提交为 `c2563b38bf72d160079e8ddfe7595ab0ca151466`（2026-09-29）。
- 按任务要求从干净基线创建并切换到 `feature/returnflow-portfolio`。
- 此记录之后尚无项目功能代码修改或提交。

## 已有实现

| 范围 | 基线状态 |
|---|---|
| 业务状态与权限 | FastAPI 提供 Bearer Token、组织成员与角色校验；已有客服、仓库、财务、管理员角色及退货状态机。工单状态写入使用版本 CAS。 |
| 退货与退款 | 已有建单、资格审批、收货、验货、退款审批、拒绝、退款对账、结案 API。高额退款阈值可配置，需要两名不同财务人员审批。 |
| 可靠性 | 已有请求幂等记录、Outbox worker、稳定支付幂等键、支付证据核验、Webhook 去重、未知结果暂停自动派发、支付方权威查询和审计事件。 |
| 支付模拟 | 独立 Fake Payment 服务保存模拟退款，可通过配置演示预处理失败、处理后超时、Webhook 先于超时确认及重复 Webhook。 |
| 数据库 | SQLAlchemy 模型涵盖组织、用户、成员关系、工单、审批、退款意图、Webhook 回执、审计、幂等记录和 Outbox。Alembic 目前只有初始 schema 迁移。 |
| 操作界面 | `/` 提供静态介绍页；它没有业务操作功能。API 具备工单列表、基本详情、建单和状态操作，但详情没有返回审批、退款证据或审计时间线，亦无总览摘要 API。 |
| 演示初始化 | Seed 在 `Demo Store` 不存在时建立组织及五种演示身份；已有组织时直接返回。尚未生成可重复重置的业务场景样本，也没有浏览器演示身份入口。 |

## 本任务尚缺的部分

- 独立 React、TypeScript、Vite 业务操作台及其总览、工单、详情、异常对账页面。
- 有受限服务身份的 n8n Intake 与 Operations Digest 工作流、可导入 JSON 和对应配置说明。
- Mailpit、摘要所需只读接口及邮件通知工作流。
- 本地演示模式、可重复场景数据、启动/停止/初始化/重置/验证脚本，以及面向业务演示的文档和运行截图。
- 当前 Compose 仅包含 PostgreSQL、迁移、API、worker、Fake Payment；没有前端、n8n 或 Mailpit 服务。

## 阶段 0 验证结果

| 检查 | 结果 |
|---|---|
| `docker compose config --quiet` | 通过，现有 Compose 配置可解析。 |
| `docker compose build` | 未完成。Docker CLI 无法连接本机 Docker Desktop Linux Engine 命名管道；因此尚未验证容器构建或运行。未启动容器。 |
| `.\.venv\Scripts\pytest.exe -q -m 'not integration'` | 通过：30 passed，8 deselected；出现两条来自 Starlette/httpx 的弃用警告。 |
| `.\.venv\Scripts\pytest.exe -q -m integration` | 8 skipped，30 deselected。测试 fixture 因 `RETURNOPS_TEST_DATABASE_URL` 未配置而跳过；PostgreSQL 并发和运行时语义尚未在本机验证。 |

本机仓库虚拟环境使用 Python 3.12.13，具备项目依赖。无参数的系统 `pytest` 使用 Python 3.14.8，因缺少 SQLAlchemy 无法加载测试；本次基线测试改用仓库虚拟环境执行。

## 证据边界

上述测试证明现有 SQLite 单元及 API 测试通过，不能证明 PostgreSQL 并发行为、Docker 部署、浏览器操作台、n8n 或 Mailpit 已可运行。当前没有本地企业使用数据，不能据此声称节省工时、降低差错率或达到生产可靠性。
