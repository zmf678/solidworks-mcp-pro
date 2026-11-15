# 架构

[English](../ARCHITECTURE.md) | **简体中文**

## 请求流

```mermaid
flowchart LR
    Client[MCP 客户端] -->|stdio JSON-RPC| Server[server.py + tools/*.py<br/>FastMCP 工具]
    Server -->|await ComWorker.call| Worker[com_worker.py<br/>专用 STA 线程]
    Worker --> Session[SolidWorksSession<br/>领域 Mixin]
    Session --> Binding[binding.py<br/>早期绑定类型库包装]
    Binding --> COM[SolidWorks COM API]
    Session --> Pure[mesh_tools / region_tools<br/>sketch_constraints / free_sketch]
    Server -->|{ok:false,error}| Client
```

服务是本地 stdio MCP 进程，不启动 SolidWorks，只通过 `GetActiveObject`
附加到已运行实例。

## 分层

| 层 | 职责 | 禁止 |
|---|---|---|
| `server.py` | CLI 入口、公共 re-export、`main()` | 放工具体或 COM 逻辑 |
| `tools/` | 按领域声明 88 个 MCP 工具，校验参数、委托、错误归一化 | 放 COM 逻辑或建模状态 |
| `app.py` | FastMCP 实例、连接说明、guide 资源、`_call`/`_failure`、worker/session 装配 | 声明领域工具 |
| `com_worker.py` | 一个 STA 线程，串行化所有 COM 调用 | 回调 asyncio 或并发执行 |
| `binding.py` | 用生成的类型库接口包装原始 dispatch；按 dispid 调用 | 假设 late binding 可用 |
| `session/` Mixin | 针对当前文档实现建模操作 | 互相 import、放模块级可变状态 |
| 纯函数 | 网格剖切、区域轮廓、草图自由度规划 | 依赖运行中的 SolidWorks |

## Session 组合

`SolidWorksSession` 由 `session/__init__.py` 按领域组合 23 个 Mixin：

```python
class SolidWorksSession(
    CoreMixin, GeometryMixin, SketchingMixin, SolidsMixin, SweepsMixin,
    HolesMixin, FaceFeaturesMixin, CutsMixin, FilletsMixin, ChamfersShellsMixin,
    MirrorsMixin, PatternsPlanesMixin, ParametersMixin, FeatureHistoryMixin,
    PersonSketchMixin, MaterialsMixin, InspectionMixin, PrintabilityMixin,
    MeshIOMixin, ExportIOMixin, AssemblyCoreMixin, AssemblyMatesMixin,
    AssemblyAnalysisMixin, SessionConstants,
):
    ...
```

拆分是行为保持的：346 个方法体从旧 `session.py` 原样迁移；唯一改动是
`_IMPORT_LIMIT_MB` 在静态辅助方法中改为 `SessionConstants._IMPORT_LIMIT_MB`。
所有方法共享同一个 `self`，跨域辅助方法照常可用。

## 状态归属

`CoreMixin.__init__` 持有可变状态：

| 属性 | 含义 |
|---|---|
| `_sw` | 早期绑定 `ISldWorks` |
| `_mod` | 生成的类型库包装模块 |
| `_model` | 当前 `IModelDoc2`（零件或装配） |
| `_quiet_depth` | “保持 UI 静止”守卫的嵌套深度 |
| `_reading` | 只读工具的嵌套深度 |
| `_to_wake` | 调用后要恢复的文档/属性 |

`SessionConstants` 持有类级常量（公差、枚举映射、限制）。不要在模块级放可变状态。

## 调用生命周期

1. MCP 客户端发送工具调用，匹配的 `tools/<domain>.py` 包装接收。
2. `_call(fn, ...)` 把 `_session.run_guarded(fn, ...)` 提交给 `ComWorker`。
3. `run_guarded` 取特征树快照、设置 `CommandInProgress`，在 COM 线程调用 Mixin。
4. 方法修改 SolidWorks，返回可 JSON 序列化的字典。
5. 失败时 `run_guarded` 删除快照后新增的特征、恢复 quiet 状态，`_call` 返回
   `{"ok": false, "error": "..."}`。
6. 纯文件工具（`slice_mesh`、`compare_with_mesh`）通过
   `_call_without_solidworks` 绕过 COM worker。

## 新增工具

1. 在对应 Mixin 实现（例如新孔型放 `session/holes.py`）。
2. 在 `src/solidworks_mcp/tools/` 下对应模块加薄 `@mcp.tool()` 包装，docstring
   写清单位、选择器和返回结构；需要保持 `server.py` 导入兼容时再 re-export。
3. 加纯逻辑单测；涉及 SolidWorks 时加 `solidworks` 标记的集成测试和手算断言。
4. 更新 `README.md`、`README.zh-CN.md`、`guide.md`、`CHANGELOG.md`。
5. 运行 `CONTRIBUTING.md` 中的检查。

## 为什么必须早期绑定 + 专用线程

在已验证版本上，`GetActiveObject` 返回的 dispatch 的 `GetTypeInfo()` 会失败，
纯 late binding 在 `IModelDoc2.FirstFeature` 等调用上会报
`DISP_E_MEMBERNOTFOUND`。`binding.py` 从已安装类型库生成 makepy 包装，把原始
dispatch 包进正确接口类，按 dispid 调用。

COM 是 STA 且线程亲和；MCP 服务跑在 asyncio 上，因此 `com_worker.py` 把所有
调用固定到一个线程。

## 失败模型

- 失败是正常结果，不是抛给 MCP 客户端的异常。
- `SolidWorksError` 带可读、可操作的错误信息。
- 原始 COM 错误被缩减成可读描述。
- 失败调用回滚本次新增特征，零件保持调用前状态。
- `CommandInProgress` 和 quiet-view 守卫在成功/失败后都恢复。

## 延伸阅读

- [`ENGINEERING.md`](ENGINEERING.md)：检查项与完成定义。
- [`TESTING.md`](TESTING.md)：测试分层与 CI。
- [`RELEASING.md`](RELEASING.md)：发布流程。
- [`MAINTENANCE.md`](MAINTENANCE.md)：依赖与上游维护。
