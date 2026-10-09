# ReturnFlow 前端操作台

本目录是 ReturnFlow 的 React、TypeScript、Vite 业务界面。客服、仓库、财务和管理员通过浏览器查看真实工单、角色待办、审批记录、退款证据及对账状态；服务端 API 仍是业务状态和授权的唯一权威。

产品总览、完整架构和测试边界见仓库 [README](../README.md)、[演示步骤](../docs/DEMO.md) 与 [架构说明](../docs/ARCHITECTURE.md)。

## 运行完整演示栈

在 Windows PowerShell 7 的仓库根目录启动 Compose：

```powershell
.\scripts\start-demo.ps1
```

然后访问 <http://127.0.0.1:4173>。演示身份由 API 签发为短期 HttpOnly Cookie；不要在前端源码、浏览器持久存储或截图中保存凭据。第一次初始化 n8n 的步骤见 [`n8n/README.md`](../n8n/README.md)。

## 本地开发

```powershell
cd frontend
npm ci
npm run dev
```

Vite 默认将 `/v1` 请求代理到 `http://127.0.0.1:8000`。如 API 使用其他本机地址，可通过 `RETURNOPS_API_PROXY` 覆盖。独立开发服务器不能替代 Compose 集成演示；数据库、Fake Payment、worker 和 n8n 仍由根目录的 Compose 项目提供。

## 检查与浏览器测试

```powershell
npm run build
npm run lint
npm run e2e:typecheck
npm run test:e2e
```

端到端测试需要已启动的本地 ReturnFlow Compose 栈及 Playwright Chromium；完整故障恢复流程和 n8n Production Webhook 验收命令见 [`docs/DEMO.md`](../docs/DEMO.md) 与 [`n8n/README.md`](../n8n/README.md)。这些测试会在持久化演示库中留下合成工单，数据边界与重置步骤见 [`docs/TEST-EVIDENCE.md`](../docs/TEST-EVIDENCE.md)。
