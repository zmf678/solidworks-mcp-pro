# 贡献指南

[English](CONTRIBUTING.md) | **简体中文**

欢迎改进 SolidWorks MCP。本项目以 Windows 为主：单测可在任何平台跑，集成测试
需要已安装、已授权并正在运行的 SOLIDWORKS。

## 开发环境

```powershell
git clone https://github.com/zmf678/solidworks-mcp-pro.git
cd solidworks-mcp-pro
uv sync --extra dev
```

所有命令都使用 `uv` 环境。要从本仓库运行服务，把 MCP 客户端指向
`.venv\Scripts\python.exe -m solidworks_mcp.server`。

## PR 前检查

```powershell
uv run pytest -m "not solidworks"
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

涉及 COM 行为时，在 SolidWorks 打开的机器上再跑：

```powershell
uv run pytest -m solidworks
```

CI 只跑单测、lint、格式、mypy 和打包；集成测试因 GitHub runner 没有 SolidWorks
而保留在本地。

## 代码放哪里

- `server.py`：只做入口和 re-export。
- `src/solidworks_mcp/tools/<domain>.py`：MCP 工具声明，薄包装。
- `src/solidworks_mcp/session/<domain>.py`：建模实现，放对应领域 Mixin。
- `src/solidworks_mcp/<helper>.py`：纯函数、可无 SolidWorks 测试。
- `tests/`：每个领域一个测试文件；集成测试加 `@pytest.mark.solidworks`。

完整模块地图见 `Docs/zh-CN/ARCHITECTURE.md`，完成定义见
`Docs/zh-CN/ENGINEERING.md`。

## 分支与提交

- 从 `main` 拉短分支（`fix/face-selection`、`refactor/session-split`）。
- 优先 Conventional Commits：`feat:`、`fix:`、`refactor:`、`test:`、`docs:`、
  `chore:`。
- 重构保持行为不变，并与功能变更分开。
- 不提交本机路径、样例 CAD 文件、生成导出物或密钥。

## Pull Request

使用 PR 模板，说明：

1. 改了什么、为什么；
2. 怎么测试，是否跑了 SolidWorks 集成测试；
3. 公共工具/API 影响；
4. CHANGELOG 条目。

小而聚焦的 PR 比“重构 + 功能”混在一起更容易审查。

## 上游

本仓库是 fork。对上游也有益的改动尽量保持独立，便于向上游提 PR。见
`UPSTREAM.zh-CN.md`。
