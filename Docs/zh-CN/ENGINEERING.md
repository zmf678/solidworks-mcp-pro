# 工程标准

[English](../ENGINEERING.md) | **简体中文**

本仓库是 [`hjbaard/SolidWorks-MCP`](https://github.com/hjbaard/SolidWorks-MCP)
的工程化增强分支。上游提供建模内核和工具面；本分支增加工程控制，目标是在保持
已验证行为的前提下，让代码更容易修改、审查和发布。

## 1. 不可妥协的原则

1. **行为优先。** 重构必须保持 MCP 工具名、参数和返回结构不变；改变行为属于功能
   变更，需要单独的测试和 CHANGELOG。
2. **一个 COM 会话、一个线程。** SolidWorks COM 是 STA 且线程亲和。所有 COM
   调用必须经 `ComWorker` 在专用 `solidworks-com` 线程执行，不能从 asyncio
   事件循环或普通线程池调用。
3. **错误是数据。** 工具失败返回 `{"ok": false, "error": "..."}`，原始 COM
   异常和堆栈不能直接抛给 Agent。
4. **每次修改都自验证。** 建模调用返回实测体积、质量和包围盒；尺寸/配合在
   rebuild 后回测。做不到的调用必须响亮失败，不能返回“看起来对”的几何。
5. **固定、类型化的工具面。** 没有任意代码/Shell 工具，Agent 只能调用声明的
   MCP 工具。
6. **只在本机运行。** 通过 COM 与本机 SolidWorks 通信；服务不联网，不保存凭据。
7. **模块小而明确。** 一个模块只有一个变更理由；超过约 600 行或承担第二个领域
   时应拆分。
8. **默认 GB。** 毫米、第一角投影、GB 孔/螺纹表和 GB 绘图模板；ISO 是显式
   回退。映射和非声明见 [`MODELING-STANDARDS.md`](MODELING-STANDARDS.md)。

## 2. 必需检查

| 范围 | 标准 | 执行方式 |
|---|---|---|
| Python | 3.11+、`src/` 布局、setuptools | `pyproject.toml`、CI |
| 格式 | Ruff formatter，120 列 | `ruff format --check src tests` |
| Lint | Ruff `E4`、`E7`、`E9`、`F`、`I`、`UP` | `ruff check src tests` |
| 类型 | 公共函数有注解；mypy 先覆盖核心模块 | `uv run mypy` |
| 单测 | 不需要 SolidWorks，快速、确定 | `pytest -m "not solidworks"` |
| 集成测试 | `solidworks` 标记；真实 SolidWorks；手算断言 | 本地合并前运行 |
| 覆盖率 | 语句+分支，门槛 35%，报告上传 | `pytest --cov`、CI artifact |
| 打包 | sdist + wheel，元数据检查 | `uv build`、`twine check` |
| 版本 | SemVer；`pyproject.toml`、`server.json`、`__version__` 一致 | `tests/test_packaging.py` |
| 变更日志 | 用户可见变更写入 `[Unreleased]` | PR 检查清单 |
| 安全 | 无密钥、无网络、无任意代码执行 | 审查 + `SECURITY.md` |

## 3. 完成定义

一个变更只有全部满足才算完成：

- [ ] 行为有单测覆盖；涉及 COM 时有集成测试。
- [ ] `uv run pytest -m "not solidworks"` 通过。
- [ ] `uv run ruff check src tests` 和 `uv run ruff format --check src tests` 通过。
- [ ] `uv run mypy` 通过。
- [ ] `CHANGELOG.md` 有 `[Unreleased]` 条目。
- [ ] 用户文档已更新（`README.md`、`README.zh-CN.md`、`guide.md` 或 `Docs/`）。
- [ ] 公共工具名/参数未变，或明确标注为破坏性变更。
- [ ] 新增运行时依赖有理由说明。
- [ ] 未提交密钥、令牌、本机路径或机器专属样例文件。

## 4. 模块边界

```
src/solidworks_mcp/
  server.py          入口与 re-export
  app.py             FastMCP 实例、连接说明、guide 资源、错误归一化
  tools/             按领域拆分的 MCP 工具声明（88 个）
    core.py          生命周期/连接
    solids.py        拉伸、旋转、扫掠、放样、基准面、筋
    features.py      孔、螺纹、面特征、切除、圆角、阵列、抽壳
    sketch.py        草图读取与人工草图
    inspection.py    尺寸、方程、历史、材料、实体、可打印性
    io.py            文档、导出、截图、图纸
    assembly.py      装配、组件、配合、干涉、运动
  com_worker.py      专用 STA 线程，串行化 COM
  binding.py         早期绑定/类型库包装
  constants.py       从类型库读取的枚举值
  units.py           mm <-> m、度 <-> 弧度
  errors.py          SolidWorksError -> {ok:false,error}
  mesh_tools.py      纯 STL/3MF 几何
  region_tools.py    纯扫掠区域
  sketch_constraints.py 纯草图自由度规划
  free_sketch.py     自由草图规划
  session/
    __init__.py      组合 SolidWorksSession
    _constants.py    共享类常量
    _decorators.py   _reads_only 等
    core.py          连接、文档、守卫调用、COM 线程辅助
    geometry.py      基准面、面/边选择、拉伸辅助
    sketching.py     草图绘制与约束
    solids.py        盒体、拉伸轮廓、样条、圆盘、圆柱、圆锥、旋转
    sweeps.py        扫掠、放样、筋
    holes.py         孔、沉孔、螺纹、Hole Wizard
    face_features.py 平面上的孔、凸台、垫、文字
    cuts.py          轮廓切除、型腔、槽
    fillets.py       圆角、变半径圆角、全圆角
    chamfers_shells.py 倒角、抽壳
    mirrors.py       实体/特征镜像
    patterns_planes.py 线性/圆周阵列、基准面
    parameters.py    尺寸、方程、尺寸列表
    feature_history.py 特征树、压缩、重排
    person_sketch.py 读取/使用人工草图
    materials.py     外观与材料
    inspection.py    质量属性、面、边、实体
    printability.py  悬垂、孤岛、薄壁
    mesh_io.py       网格剖切/对比
    export_io.py     导出、截图、图纸
    assembly_core.py 装配文档、组件、变换
    assembly_mates.py 配合与测量
    assembly_analysis.py 干涉、距离、运动、扫掠区域
```

规则：

- `session/` 内的方法通过 `self` 互相调用；Mixin 模块之间**不得互相 import**。
- 共享状态在 `CoreMixin.__init__`；共享常量在 `SessionConstants`。
- `SolidWorksSession` 是唯一公共类；新增 Mixin 必须加入 `session/__init__.py`，
  且方法名不得重复。
- `tools/` 只放 `@mcp.tool()` 包装：校验参数、通过 `_call` 调 `_session`、
  返回字典；文件类工具用 `_call_without_solidworks`。
- `server.py` 只做入口和 re-export，不放新工具体。
- 纯函数放 `session/` 外，便于无 Windows/SolidWorks 测试。

## 5. 测试标准

两层：

1. **单测层**：纯函数、选择器解析、几何数学、打包元数据、工具转发、模块化守卫。
   不需要 SolidWorks，秒级完成。
2. **集成层**（`-m solidworks`）：驱动真实 SolidWorks，逐特征与手算对比；每个
   零件测试用 `part` fixture，并自动断言没有欠约束草图。

覆盖率门槛 35% 是刻意保守值，因为 COM 集成测试不能进 CI。应提升纯逻辑覆盖率，
不要为了过门槛降低标准。

## 6. 版本与发布

- SemVer：patch 修 bug，minor 加工具/能力，major 破坏性变更。
- 版本同时存在于 `pyproject.toml`、`server.json`、`__version__`，由
  `tests/test_packaging.py` 强制一致。
- 发布前更新 `CHANGELOG.md`，CI 必须全绿。
- **本分支不发布到 PyPI 或公共 MCP Registry。** 上游 publish workflow 仅作参考，
  且被 `github.repository == 'hjbaard/SolidWorks-MCP'` 保护。

## 7. 文档地图

| 文档 | 负责内容 |
|---|---|
| `README.md` / `README.zh-CN.md` | 用户安装、工具概览、快速开始 |
| `Docs/README.md` / `Docs/zh-CN/README.md` | 文档索引 |
| `Docs/ENGINEERING.md` / `Docs/zh-CN/ENGINEERING.md` | 标准与完成定义 |
| `Docs/MODELING-STANDARDS.md` / `Docs/zh-CN/MODELING-STANDARDS.md` | GB 建模标准 |
| `Docs/ARCHITECTURE.md` / `Docs/zh-CN/ARCHITECTURE.md` | 分层与请求流 |
| `Docs/TESTING.md` / `Docs/zh-CN/TESTING.md` | 测试与 CI |
| `Docs/RELEASING.md` / `Docs/zh-CN/RELEASING.md` | 发布流程 |
| `Docs/COMPATIBILITY.md` / `Docs/zh-CN/COMPATIBILITY.md` | 平台与自检 |
| `Docs/MAINTENANCE.md` / `Docs/zh-CN/MAINTENANCE.md` | 上游、依赖、安全 |
| `CONTRIBUTING.md` / `CONTRIBUTING.zh-CN.md` | 开发与 PR 规则 |
| `SECURITY.md` / `SECURITY.zh-CN.md` | 安全报告 |
| `UPSTREAM.md` / `UPSTREAM.zh-CN.md` | 上游关系与同步 |

## 8. 已知债务

- Mypy 目前只覆盖核心模块；Mixin 围绕 COM 动态类型，后续需要 Protocol/stub 层。
- `tools/` 是刻意重复的 88 个 MCP 包装；逻辑在 session，包装保持薄。
- 集成测试需要 Windows + 已授权 SolidWorks，不在 CI 中运行。
- `main` 由 `main-protection` ruleset 保护：必须 PR、四个 CI 检查通过且分支最新，
  禁止删除/强推。
- 上游同步需要把旧 `session.py` 的变更映射到对应 Mixin，见 `UPSTREAM.md`。
