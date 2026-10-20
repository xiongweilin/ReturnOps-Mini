# 贡献指南

## 流程

1. 从 `main` 创建聚焦的分支。
2. 运行与改动相关的检查：
   - `python scripts/check_doc_pairs.py`
   - `pytest -q -m "not integration"`
   - `ruff check .`
   - `mypy`
   - `cd frontend; npm ci; npm run build; npm run lint; npm run e2e:typecheck`
3. 只使用合成数据。不要加入凭据、个人数据或真实客户/支付记录。
4. 向 `main` 提交 Pull Request，并说明验收证据与未验证边界。

## 语言规则

- 公开文档成对保留。中文主文件使用 `*.md`，并与 `*.en.md` 成对；英文主文件使用 `*.md`，并与 `*.zh-CN.md` 成对。`LICENSE`、第三方内容与生成内容不适用。
- 第一方代码的整行注释使用中文；行内注释、docstring 与 API 文档保持原有语言。
- CI 会运行 `scripts/check_doc_pairs.py`，请保持通过。

## Commit 风格

- 保持 commit 小而聚焦，并说明改动原因。
- 不要提交 `.env`、`.local/` 内容、token 或含秘密的截图。

## 许可证

提交贡献即表示同意贡献内容按照仓库 `LICENSE` 授权。
