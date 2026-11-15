# 上游关系

[English](UPSTREAM.md) | **简体中文**

本仓库是 [`hjbaard/SolidWorks-MCP`](https://github.com/hjbaard/SolidWorks-MCP)
的 **fork**，基于上游 `main` 的提交 `58ca7bf`（`v0.20.0`，2026-11-13）创建。

## 来自上游的内容

- SolidWorks COM 集成、常量、建模知识和 `SolidWorksSession` 方法体；
- 建模指南 `src/solidworks_mcp/guide.md`、工具面和文档；
- MIT 许可代码；原始版权声明保留在 `LICENSE` 和 `NOTICE`。

## 本分支增加的内容

- 领域模块化的 `session/` 包（上游单文件 `session.py` 拆成 Mixin，方法体不变）；
- PR CI（lint、格式、mypy、单测、打包）、Dependabot、覆盖率报告和 `uv.lock`；
- 工程标准、架构文档、贡献/安全模板；
- fork 安全保护：上游 publish workflow 不能从本仓库发布；
- 中文文档入口和 GB 建模标准。

本分支**不占用**上游 PyPI 包或 `io.github.hjbaard/solidworks-mcp` MCP Registry
身份。不要用该身份发布。

## 同步上游

上游仍使用单文件 `session.py`，直接 `git merge upstream/main` 会冲突。实用流程：

```powershell
git fetch upstream
git log --oneline HEAD..upstream/main
git diff HEAD..upstream/main -- src/solidworks_mcp/session.py
```

然后：

1. 找出上游 `session.py` 改动的方法；
2. 把每个改动应用到 `src/solidworks_mcp/session/` 下对应 Mixin（用
   `rg "def <method>" src/solidworks_mcp/session` 定位）；
3. 非 session 改动正常应用（`server.py`、`constants.py`、文档、测试）；
4. 跑 `uv run pytest -m "not solidworks"`、Ruff 和 mypy；
5. 合并前跑相关 SolidWorks 集成测试。

大版本同步可先在临时分支合并上游提交，再用 `git diff` 和映射表重放拆分。保持拆分
机械进行：同步时不要重写上游方法体。

## 署名

上游作者：Henk Jan Baard（`hjbaard`）。再分发时请保留 MIT 许可和 `NOTICE`。
