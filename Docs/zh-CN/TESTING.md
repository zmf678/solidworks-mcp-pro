# 测试

[English](../TESTING.md) | **简体中文**

项目分两层测试，另有打包、可移植性和模块化检查。核心原则：**建模变更必须用手算
验证，不能只靠“看起来对”。**

## 测试层

| 层 | 标记/文件 | 需要 SolidWorks | 用途 |
|---|---|---|---|
| 单元 | 默认 | 否 | 纯几何、选择器、校验、打包、工具转发、模块化守卫 |
| 集成 | `@pytest.mark.solidworks` | 是，运行且已授权 | 真实建模，体积/质量/配合与手算对比 |
| 可移植性 | `tests/test_server_portability.py` | 否（屏蔽 pywin32） | 非 Windows 启动、列出 88 个工具、失败响亮 |
| 打包 | `tests/test_packaging.py` | 否 | `pyproject.toml`、`server.json`、`__version__`、README 标记一致 |
| 模块化 | `tests/test_modularity.py` | 否 | Mixin 组合、无重复辅助方法、88 个唯一工具、无跨 Mixin import |
| 自检 | `solidworks-mcp --selftest` | 是 | 用户机器冒烟测试，小零件+手算 |

## 命令

```powershell
uv sync --extra dev

uv run pytest -m "not solidworks"          # 快速层，不需要 SolidWorks
uv run pytest                              # 全部，需要 SolidWorks
uv run pytest -m solidworks                # 只跑集成层
uv run pytest tests/test_server_portability.py
uv run pytest --cov=solidworks_mcp --cov-report=term-missing
```

`pytest` 默认只收集 `tests/`，并加 `-ra` 显示简短摘要。`solidworks` 标记在
`pyproject.toml` 声明。

## 覆盖率

- 使用 `pytest-cov` 统计语句+分支覆盖率。
- CI 门槛 **35%**（`[tool.coverage.report] fail_under`）。
- 当前单测层约 **37%**。不要为了过门槛降低标准，应补测试。
- 集成测试能显著提高覆盖率，但需要 SolidWorks 授权，不能进 CI。

## CI 矩阵

| Job | Runner | 内容 |
|---|---|---|
| Lint and format | Ubuntu | `ruff check src tests`、`ruff format --check src tests` |
| Type check | Ubuntu | `mypy` 覆盖配置的核心模块 |
| Unit tests (Windows) | Windows | `pytest -m "not solidworks"` + 覆盖率 XML artifact |
| Build package | Ubuntu | `uv build`、`twine check dist/*` |

四个 job 全部通过才能合并 PR。

## 编写测试

### 纯单测

- 放到对应领域测试文件（`test_logic.py`、`test_mesh_tools.py`、`test_sketching.py` 等）。
- 只用 `SolidWorksSession()` 测纯辅助方法，不要 `connect()`。
- 在接触 SolidWorks 之前的拒绝用
  `pytest.raises(SolidWorksError, match="...")`。
- 几何断言尽量精确，浮点用 `pytest.approx`。
- 新校验规则至少一个正例 + 一个拒绝例。
- 标准选择是纯函数：`_wizard_selection` 覆盖 GB 默认、ISO 回退和非法标准。

### 集成测试

- 加 `@pytest.mark.solidworks`（`test_features.py` 整文件已标记）。
- 零件用 `part` fixture，装配用 `assembly` fixture；`part` 会断言没有欠约束草图。
- 体积、质量、包围盒、配合距离必须有显式手算；公式写进 docstring 或注释。
- 通过 fixture 关闭文档，不要留下打开的零件。
- 需要保存组件时用 `blocks` fixture，不要依赖机器专属文件。
- SolidWorks 拒绝的特征应失败响亮且回滚；两者都要断言。

### 工具转发

`tests/test_logic.py::test_tool_forwards_its_arguments_in_order` 会解析
`src/solidworks_mcp/tools/` 下所有 async 工具函数，检查它们按顺序委托给存在的
session 方法。新增工具包装会自动纳入。

### 模块化守卫

`tests/test_modularity.py` 会在以下情况失败：

- Mixin 没加入 `SolidWorksSession`；
- 两个 Mixin 定义同名辅助方法；
- 工具名重复或总数不是 88；
- Mixin 互相 import；
- `server.py` 没有 re-export 所有声明工具。

## 失败排查

1. 用最小命令复现：`uv run pytest path::test_name -q`。
2. 集成失败先确认 SolidWorks 已打开且没有模态对话框（120 秒调用超时会提示）。
3. 选择器/几何失败把实测值和手算写进断言消息。
4. Windows 可移植性失败要确保子进程显式 UTF-8；测试已这么做。
5. 不要为了让测试通过而弱化断言；修代码或记录真实平台限制。
