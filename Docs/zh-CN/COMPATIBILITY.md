# 兼容性

[English](../COMPATIBILITY.md) | **简体中文**

## 支持环境

| 组件 | 支持 | 说明 |
|---|---|---|
| 操作系统 | Windows | COM 自动化；其他平台可启动服务，但工具调用会响亮失败 |
| SOLIDWORKS | 2026（3DEXPERIENCE R2026x）已验证 | 所用 API 自 SOLIDWORKS 2020 SP2 存在，但 2020–2025 未验证 |
| Python | 3.11+ | 本机验证用 3.12；CI 使用 runner 可用的 3.11+ |
| MCP SDK | `mcp>=1.26,<2` | `mcp` 2.x 重命名了 `FastMCP`，放宽前需要迁移 |
| pywin32 | `>=306`（仅 Windows） | 由 `sys_platform == 'win32'` 条件安装 |
| 零件模板 | Y-up | Z-up 模板会被拒绝并给出修正提示 |
| 建模标准 | GB 默认；ISO 显式回退 | 见 [`MODELING-STANDARDS.md`](MODELING-STANDARDS.md) |
| 单位 | 工具边界 mm / 度 | COM 内部转换为米/弧度 |

## 自检

SolidWorks 运行中，在本仓库执行：

```powershell
uv sync
uv run solidworks-mcp --selftest
```

自检会报告 SOLIDWORKS 版本、语言、模板和单位，创建小零件和装配体，逐项与手算
对比，然后不保存关闭。报告兼容问题前先运行它。

如果使用的是**上游 PyPI 包**而不是本分支，对应命令是
`uvx solidworks-mcp --selftest`；该命令不会安装本分支。

## 已知限制

- 本分支只验证 SOLIDWORKS 2026。
- 服务附加到**正在运行**的 SOLIDWORKS，不会自己启动。
- 已验证版本必须使用早期绑定；生成的 `gen_py` 包装要与已安装类型库匹配。
- Z-up 零件模板会被拒绝；工具按 Y-up 建模。
- 服务不联网，不保存凭据。
- 集成测试需要已授权 SOLIDWORKS，不在 CI 运行。

## 报告兼容性

打开 **Compatibility report** Issue，粘贴完整自检输出（成功或失败都要），并包括：

- SOLIDWORKS 年份、Service Pack、语言；
- Windows 版本；
- Python 版本；
- 实际使用的 `uv run` 或 `uvx` 命令；
- 自检输出和出现的任何对话框。

如果是 Bug 而不是兼容性问题，用 Bug report 模板，并附最小复现工具调用。

## API 变更策略

- 工具名和参数名视为公共 API。
- 增量能力走 minor；破坏性变更走 major。
- `SolidWorksSession` 是内部实现，但公共方法尽量保持稳定，便于 `scripts/` 使用。
- MCP 服务身份仍是 `solidworks-mcp`；本分支不占用上游 PyPI 或 MCP Registry 身份。
