# 发布

[English](../RELEASING.md) | **简体中文**

本分支**不发布**上游 PyPI 包或公共 MCP Registry 条目。这里的发布是 GitHub
Release（源码和构建产物）。上游 publish workflow 被保护，只在
`hjbaard/SolidWorks-MCP` 运行。

## 版本

遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)：

- **patch**：修 bug，不改公共工具；
- **minor**：新增工具、参数或能力；
- **major**：工具签名、返回结构或最低平台要求破坏性变更。

版本必须三处一致：

1. `pyproject.toml` → `[project].version`
2. `server.json` → `version` 和 `packages[0].version`
3. `src/solidworks_mcp/__init__.py` → `__version__`

`tests/test_packaging.py` 会强制一致。

## CHANGELOG

开发时在 `CHANGELOG.md` 的 `## [Unreleased]` 下添加条目。发布时改成新版本号和
日期，再新建一个 `[Unreleased]`。分类用 `Added`、`Changed`、`Fixed`、
`Removed`、`Security`。

## 发布检查清单

```powershell
uv sync --extra dev

uv run pytest -m "not solidworks"
uv run pytest -m solidworks          # 需要有 SolidWorks 的机器
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest -m "not solidworks" --cov=solidworks_mcp --cov-report=term-missing
uv build
uv run twine check dist/*
```

然后确认：

- [ ] `main` 上 CI 全绿；
- [ ] `CHANGELOG.md` 有本次版本段落；
- [ ] 三处版本号已更新；
- [ ] README/指南反映用户可见变化；
- [ ] 工作区干净；
- [ ] 创建并推送签名标签 `vX.Y.Z`；
- [ ] 从标签创建 GitHub Release；
- [ ] Release notes 链接 CHANGELOG，并标明破坏性变更；
- [ ] 没有从本分支尝试发布 PyPI/MCP Registry。

## 打标签和发布

```powershell
git checkout main
git pull --ff-only
git tag -a v0.21.0 -m "v0.21.0"
git push origin v0.21.0

gh release create v0.21.0 --title "0.21.0" --notes-file Docs/RELEASE_NOTES_0.21.0.md
```

可手动附加构建产物：

```powershell
uv build
gh release upload v0.21.0 dist/solidworks_mcp-0.21.0-py3-none-any.whl dist/solidworks_mcp-0.21.0.tar.gz
```

## 热修复

1. 从发布标签拉分支：`git switch -c hotfix/v0.21.1 v0.21.0`。
2. 做最小修复并加回归测试。
3. 更新 patch 版本和 CHANGELOG，向 `main` 提 PR。
4. 合并后打 `v0.21.1` 标签并发布 GitHub Release。

## 回滚

- 坏发布用新的 patch 版本覆盖，不移动或删除已发布标签。
- 发布 workflow 在真正发布前失败，修 workflow 后用同一标签重跑。
- 依赖更新导致构建失败，回退依赖提交并用 `uv lock` 刷新 `uv.lock`。

## 分支发布策略

- 本分支的 GitHub Release 只属于本仓库。
- 上游 `publish.yml` 保留作参考，并由
  `github.repository == 'hjbaard/SolidWorks-MCP'` 保护。
- 如果将来本分支要发布自己的包，先重命名 distribution 和 MCP server 身份；
  不要复用 `solidworks-mcp` 或 `io.github.hjbaard/solidworks-mcp`。
