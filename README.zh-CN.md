# SolidWorks MCP（中文）

[English](README.md) | **简体中文**

> **工程化增强分支。** 本仓库是
> [`hjbaard/SolidWorks-MCP`](https://github.com/hjbaard/SolidWorks-MCP) 的 fork，
> 重点做模块化、可复现开发环境、CI 和工程文档。建模内核与工具面来自上游，
> 方法体保持原样；默认建模与制图标准为 **GB（中国国家标准）**，ISO 作为显式回退。
>
> 本 fork **不发布到 PyPI 或公共 MCP Registry**。`uvx solidworks-mcp` 安装的是
> 上游项目，不是本仓库。

## 项目定位

让 AI Agent（Claude 或其他 MCP 客户端）在**你自己的 SolidWorks** 中创建真实的
参数化零件和装配体，并且**能检查自己的结果**：每次建模调用都返回实测体积、质量
和包围盒，Agent 可以对照规格自行纠错，而不是靠“看起来差不多”。

核心原则：

- **可验证，而不只是生成**：特征返回实测几何；尺寸和配合在 rebuild 后回测。
- **草图完全定义**：从原点标注尺寸，只在几何确实水平、垂直或过原点时加关系；
  工具按角色返回尺寸（如 `width@Sketch1`），零件保持可编辑。
- **失败要响亮**：做不到的调用返回 `{ok: false, error}`，绝不静默产生错误几何。
- **固定工具面**：没有“执行任意代码”工具，Agent 只能调用声明的 MCP 工具。
- **本地运行**：通过 COM 与本机 SolidWorks 通信，服务本身不联网。

## GB 建模标准

本项目默认执行 GB 标准：

| 范围 | 默认标准 |
|---|---|
| 三维建模 | GB/T 26099.1 / .2 / .3 |
| 图纸幅面 | GB/T 14689（A4） |
| 投影法 | GB/T 14692 第一角法 |
| 尺寸注法 | GB/T 4458.4 |
| 公差与配合 | GB/T 1800.1、GB/T 1801 |
| 表面粗糙度 | GB/T 1031 |
| 几何公差 | GB/T 1182、GB/T 1184 |
| 公制螺纹 | GB/T 192 / 196 / 197 |
| 螺栓/螺钉通孔 | GB/T 5277 |
| 内六角圆柱头螺钉 | GB/T 70.1 |
| 内六角沉头螺钉 | GB/T 70.3 |

实现说明：

- `add_hole_wizard(...)` 默认 `standard="GB"`，使用 SolidWorks 的 GB 表；
  需要 ISO 时传 `standard="ISO"`。
- `add_thread(...)` 使用 GB/T 196/197 公制螺纹代号（与 ISO 公制代号一致）。
- `make_drawing(path, template=...)` 使用第一角投影和 A4；传入 `gb.drwdot`
  可获得 GB 标题栏。
- **不是 GB 认证**：标题栏、公差、粗糙度、几何公差等仍需人工审核。完整说明见
  [`Docs/zh-CN/MODELING-STANDARDS.md`](Docs/zh-CN/MODELING-STANDARDS.md)。

## 快速开始

1. 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。
2. **启动 SolidWorks** 并保持运行（服务只附加到已运行实例，不会自己启动它）。
3. 克隆本仓库并创建环境：

   ```powershell
   git clone https://github.com/zmf678/solidworks-mcp-pro.git
   cd solidworks-mcp-pro
   uv sync
   ```

4. 配置 MCP 客户端。

   **Claude Code：**

   ```powershell
   claude mcp add solidworks -- C:\path\to\solidworks-mcp-pro\.venv\Scripts\python.exe -m solidworks_mcp.server
   ```

   **Claude Desktop（`claude_desktop_config.json`）或其他客户端：**

   ```json
   {
     "mcpServers": {
       "solidworks": {
         "command": "C:\\path\\to\\solidworks-mcp-pro\\.venv\\Scripts\\python.exe",
         "args": ["-m", "solidworks_mcp.server"]
       }
     }
   }
   ```

5. 试着让 Agent 建模：

   > 设计一块 100 × 80 × 8 mm 安装板，中心 Ø16 mm 通孔，四角 12 mm 处四个
   > M5 沉头孔，四角 R5。每一步用你的手算核对体积，最后导出精细 STL。

## 环境要求

- Windows，已安装、已授权并**正在运行**的 SolidWorks。
- Python 3.11+。
- **Y-up 零件模板**（SolidWorks 标准）。SOLIDWORKS 2025 起新零件也可 Z-up；
  本工具按 Y-up 建模，遇到 Z-up 模板会明确拒绝。通过 API 新建零件时，New
  Document 对话框里的 Y-up 选择不生效；请制作 Y-up 零件并保存为 `.prtdot`，
  再在“工具 > 选项 > 系统选项 > 默认模板”中设为零件模板。
- 本分支主要在 **SOLIDWORKS 2026（3DEXPERIENCE R2026x）** 上验证；代码使用的
  API 自 SOLIDWORKS 2020 SP2 起存在，但 2020–2025 **未验证**。

自检：

```powershell
uv run solidworks-mcp --selftest
```

它会创建几个小零件和装配体，逐项与手算对比，然后不保存关闭。无论成功失败，
都可以把输出贴到
[兼容性报告](https://github.com/zmf678/solidworks-mcp-pro/issues/new?template=compatibility.yml)。

## 文档

| 文档 | 内容 |
|---|---|
| [`Docs/zh-CN/README.md`](Docs/zh-CN/README.md) | 中文文档索引 |
| [`Docs/zh-CN/ENGINEERING.md`](Docs/zh-CN/ENGINEERING.md) | 工程标准、完成定义、模块边界 |
| [`Docs/zh-CN/MODELING-STANDARDS.md`](Docs/zh-CN/MODELING-STANDARDS.md) | GB 建模标准、实现矩阵、非声明 |
| [`Docs/zh-CN/ARCHITECTURE.md`](Docs/zh-CN/ARCHITECTURE.md) | 请求流、分层、Mixin 组合 |
| [`Docs/zh-CN/TESTING.md`](Docs/zh-CN/TESTING.md) | 测试分层、命令、覆盖率、CI |
| [`Docs/zh-CN/COMPATIBILITY.md`](Docs/zh-CN/COMPATIBILITY.md) | 支持版本、自检、兼容性报告 |
| [`Docs/zh-CN/MAINTENANCE.md`](Docs/zh-CN/MAINTENANCE.md) | 上游同步、依赖、安全、模块归属 |
| [`Docs/zh-CN/RELEASING.md`](Docs/zh-CN/RELEASING.md) | 版本、CHANGELOG、发布与热修复 |
| [`CONTRIBUTING.zh-CN.md`](CONTRIBUTING.zh-CN.md) | 开发环境、检查、PR 规则 |
| [`SECURITY.zh-CN.md`](SECURITY.zh-CN.md) | 安全报告 |
| [`UPSTREAM.zh-CN.md`](UPSTREAM.zh-CN.md) | 上游关系与同步 |
| [README.md](README.md) | 英文完整 README（含 88 个工具的完整表） |

Agent 连接时会收到简短的建模指引。完整英文指南是 `solidworks://guide`，中文指南
是 `solidworks://guide-zh`（源文件 `src/solidworks_mcp/guide.zh-CN.md`）。

## 工具分组

完整工具表见英文 README；下面按用途列出主要工具：

- **实体建模**：`add_box`、`add_extruded_profile`、`add_extruded_spline`、
  `add_disc`、`add_cylinder`、`add_cone`、`add_revolved_profile`、
  `add_swept_pipe`、`add_swept_profile`、`add_lofted_solid`、`loft_sketches`、
  `add_rib`
- **草图**：`add_sketch`、`read_sketch`、`extrude_sketch`、`cut_sketch`
- **孔/螺纹**：`add_hole`、`add_counterbore_hole`、`add_hole_on_face`、
  `add_hole_wizard`、`add_thread`
- **切除/型腔**：`cut_profile`、`cut_profile_on_face`、`cut_offset_pocket`、
  `cut_slot`、`add_extruded_slot`、`cut_profile_through_plane`
- **修饰**：`add_fillet`、`add_full_round`、`add_chamfer`、`add_shell`、
  `add_linear_pattern`、`add_circular_pattern`、`add_mirror`
- **参数/历史**：`set_dimension`、`set_equation`、`list_dimensions`、
  `list_features`、`delete_feature`、`suppress_feature`、`reorder_feature`
- **检查**：`get_mass_properties`、`get_bounding_box`、`list_faces`、
  `list_edges`、`list_bodies`、`check_printability`、`check_interference`
- **装配**：`new_assembly`、`insert_component`、`add_mate`、`check_motion`、
  `measure_distance`、`swept_region`
- **导出/图纸**：`export`、`screenshot`、`make_drawing`

所有线性尺寸为 **mm**，角度为 **度**。

## 开发与测试

```powershell
uv sync --extra dev
uv run pytest -m "not solidworks"          # 快速单测，不需要 SolidWorks
uv run pytest                              # 全部测试，需要 SolidWorks
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

测试分层、CI 矩阵和覆盖率门槛见
[`Docs/zh-CN/TESTING.md`](Docs/zh-CN/TESTING.md)。

## 故障排查

- **先跑自检**：`uv run solidworks-mcp --selftest` 会显示 SolidWorks 版本、
  语言、模板和可用工具区域。把输出贴到
  [Bug 报告](https://github.com/zmf678/solidworks-mcp-pro/issues/new?template=bug_report.yml)。
- **提示找不到 SolidWorks**：SolidWorks 必须已经在运行；服务通过
  `GetActiveObject` 附加，不会启动新实例。
- **第一次调用很慢 / `EnsureModule` 报错**：首次 COM 调用会生成 `gen_py`
  类型库包装；让它完成。如果缓存损坏，删除 `gen_py` 后重试。
- **返回 `{ok: false, error: ...}`**：这是设计行为。错误信息会指出原因，
  SolidWorks 中的零件会回滚到调用前状态。
- **只验证了 SOLIDWORKS 2026**：其他版本可能枚举值或签名不同；运行
  `scripts/introspect_api.py` 检查已安装类型库。

## 许可与上游

- 许可证：MIT，保留上游版权与 `NOTICE`。
- 上游：https://github.com/hjbaard/SolidWorks-MCP
- 本 fork：https://github.com/zmf678/solidworks-mcp-pro

欢迎提交 Issue 和 PR。安全漏洞请按 [`SECURITY.zh-CN.md`](SECURITY.zh-CN.md)
私下报告。
