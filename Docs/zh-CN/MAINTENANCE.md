# 维护

[English](../MAINTENANCE.md) | **简体中文**

## 上游同步

本仓库跟踪 [`hjbaard/SolidWorks-MCP`](https://github.com/hjbaard/SolidWorks-MCP)。
fork 关系、基线提交和逐步合并流程见
[`../../UPSTREAM.zh-CN.md`](../../UPSTREAM.zh-CN.md)。

关键规则：上游仍是单个 `session.py`；同步时把每个改动的方法映射到
`src/solidworks_mcp/session/` 下对应 Mixin，不要在同步时重写方法体。

## 依赖策略

- 运行时依赖刻意很少：`mcp` 和 Windows 专用 `pywin32`。
- `mcp` 固定在 2.0 以下，因为 2.x 重命名了 `FastMCP`；主版本升级需要专门迁移
  PR，不能直接合并 Dependabot。
- Dependabot 每周检查 `pip` 和 GitHub Actions。
- 依赖 PR 只有四个 CI job 全绿、且 CHANGELOG 说明行为变化时才能合并。
- 修改 `pyproject.toml` 后运行 `uv lock` 并提交 `uv.lock`。
- GitHub Actions 按版本标签固定；优先通过 Dependabot 更新，并要求 CI 全绿。

## 安全响应

- 使用 GitHub 私密漏洞报告（Security → Report a vulnerability）；见
  [`../../SECURITY.zh-CN.md`](../../SECURITY.zh-CN.md)。
- 修复发布前不要在公开 Issue 披露漏洞。
- 安全修复走 patch release，并在 CHANGELOG 的 `Security` 分类记录。
- 任何曾提交的凭据都要轮换；不要只依赖改写历史。

## 模块归属

| 领域 | 模块 | 负责人 |
|---|---|---|
| MCP 工具面 | `app.py`、`server.py`、`tools/` | maintainer |
| COM 管道 | `com_worker.py`、`binding.py`、`constants.py`、`units.py` | maintainer |
| 零件建模 | `session/solids.py`、`sweeps.py`、`holes.py`、`face_features.py`、`cuts.py` | maintainer |
| 修饰 | `session/fillets.py`、`chamfers_shells.py`、`mirrors.py`、`patterns_planes.py` | maintainer |
| 参数/历史 | `session/parameters.py`、`feature_history.py`、`person_sketch.py` | maintainer |
| 检查/可打印性 | `session/inspection.py`、`printability.py`、`mesh_io.py` | maintainer |
| 装配 | `session/assembly_core.py`、`assembly_mates.py`、`assembly_analysis.py` | maintainer |
| 导出/IO | `session/export_io.py`、`session/mesh_io.py` | maintainer |
| 纯辅助 | `mesh_tools.py`、`region_tools.py`、`sketch_constraints.py`、`free_sketch.py` | maintainer |

这张表是路由辅助，不是锁定：跨领域的真实变更可以同时修改多个模块。

## 弃用

- 在 `CHANGELOG.md` 和工具 docstring 中公告弃用。
- 旧工具至少保留一个 minor 版本。
- 只在 major 版本移除。
- 同一变更中更新 `README.md`、`README.zh-CN.md`、`guide.md` 和测试。

## 文档维护

- `Docs/zh-CN/README.md` 是中文文档索引，`Docs/README.md` 是英文索引。
- 流程变更更新 `Docs/ENGINEERING.md` / `Docs/zh-CN/ENGINEERING.md`。
- 标准/公差/制图约定变更更新 `Docs/MODELING-STANDARDS.md` /
  `Docs/zh-CN/MODELING-STANDARDS.md` 和 `guide.md`。
- 模块/分层变更更新 `Docs/ARCHITECTURE.md` / `Docs/zh-CN/ARCHITECTURE.md`。
- 测试/CI 变更更新 `Docs/TESTING.md` / `Docs/zh-CN/TESTING.md`。
- 发布流程变更更新 `Docs/RELEASING.md` / `Docs/zh-CN/RELEASING.md`。
- 平台/版本变更更新 `Docs/COMPATIBILITY.md` / `Docs/zh-CN/COMPATIBILITY.md`。
