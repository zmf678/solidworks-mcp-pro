## What changed / 改了什么

<!-- A short description of the change and the user-visible effect. -->
<!-- 简要说明改动内容和用户可见影响。 -->

## Why / 为什么

<!-- The problem this solves, or the issue it closes. -->
<!-- 解决了什么问题，或关闭了哪个 Issue。 -->

## Checklist / 检查清单

- [ ] `uv run pytest -m "not solidworks"` passes. / 通过。
- [ ] `uv run ruff check src tests` passes. / 通过。
- [ ] `uv run ruff format --check src tests` passes. / 通过。
- [ ] `uv run mypy` passes. / 通过。
- [ ] A SolidWorks integration test was run if the change touches COM behaviour,
      or the PR explains why it could not be run. / 涉及 COM 行为时已跑 SolidWorks
      集成测试，或说明为什么无法运行。
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`. / 已在 `[Unreleased]` 下添加条目。
- [ ] User-facing docs (`README.md`, `README.zh-CN.md`, `src/solidworks_mcp/guide.md`)
      are updated. / 已更新用户文档（英文/中文 README、建模指南）。
- [ ] Public tool names or signatures did not change, or the change is called out
      explicitly as a breaking change. / 公共工具名/参数未变，或已明确标注为破坏性变更。
- [ ] No new dependency was added without a short rationale. / 新增依赖已说明理由。
