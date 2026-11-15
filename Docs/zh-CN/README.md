# 中文文档索引

[English](../README.md) | **简体中文**

本目录是 SolidWorks MCP 分支的中文文档入口。英文文档保留为上游技术参考；
两者内容不一致时，以代码、测试和英文工程文档为准，并请提 Issue 修正。

## 建议阅读顺序

| 文档 | 适合谁 | 内容 |
|---|---|---|
| [`../../README.zh-CN.md`](../../README.zh-CN.md) | 所有人 | 项目介绍、快速开始、GB 标准、常用工具 |
| `solidworks://guide-zh` | Agent/用户 | 中文建模指南（MCP 资源，源文件 `src/solidworks_mcp/guide.zh-CN.md`） |
| [`ENGINEERING.md`](ENGINEERING.md) | 贡献者 | 工程原则、必需检查、完成定义、模块边界 |
| [`MODELING-STANDARDS.md`](MODELING-STANDARDS.md) | 所有人 | GB 建模标准、实现矩阵、非声明 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 贡献者 | 请求流、分层、Mixin 组合、状态归属 |
| [`TESTING.md`](TESTING.md) | 贡献者 | 单测/集成/覆盖率/CI 矩阵 |
| [`COMPATIBILITY.md`](COMPATIBILITY.md) | 用户 | 支持版本、自检、兼容性报告 |
| [`MAINTENANCE.md`](MAINTENANCE.md) | 维护者 | 上游同步、依赖、安全、模块归属 |
| [`RELEASING.md`](RELEASING.md) | 维护者 | 版本、CHANGELOG、发布与热修复 |
| [`../../CONTRIBUTING.zh-CN.md`](../../CONTRIBUTING.zh-CN.md) | 贡献者 | 开发环境、检查、PR 规则 |
| [`../../SECURITY.zh-CN.md`](../../SECURITY.zh-CN.md) | 所有人 | 安全报告 |
| [`../../CODE_OF_CONDUCT.zh-CN.md`](../../CODE_OF_CONDUCT.zh-CN.md) | 所有人 | 行为准则 |
| [`../../UPSTREAM.zh-CN.md`](../../UPSTREAM.zh-CN.md) | 维护者 | 上游关系与同步 |

## 文档维护规则

- 一个事实只在一个文档中维护，其他文档链接过去。
- 用户可见变更更新 `README.zh-CN.md` 和/或 `src/solidworks_mcp/guide.md`。
- 标准、公差或制图约定变更更新 `MODELING-STANDARDS.md` 和 `guide.md`。
- 模块拆分或新增层更新 `ARCHITECTURE.md`。
- 测试/CI 变更更新 `TESTING.md`。
- 发布流程变更更新 `RELEASING.md`。
- 中文与英文文档同步修改；如果暂时只能改一边，在 PR 中说明。
