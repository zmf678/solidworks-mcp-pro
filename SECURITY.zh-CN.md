# 安全策略

[English](SECURITY.md) | **简体中文**

## 支持版本

| 版本 | 支持 |
|---|---|
| 0.20.x | 是 |
| 更早的 0.x | 否 |

## 报告漏洞

请**不要**为安全问题开公开 Issue。使用 GitHub 私密漏洞报告：

1. 打开仓库 **Security** 标签；
2. 选择 **Report a vulnerability**；
3. 写清版本、最小复现和影响。

如果私密报告不可用，可通过仓库中列出的维护者 GitHub 主页联系。

## 范围

SolidWorks MCP 是本地桌面自动化服务：

- 通过 COM 与正在运行的 SOLIDWORKS 通信；
- 服务本身不联网，不保存凭据；
- 只暴露固定类型的 MCP 工具，没有任意代码/Shell 工具。

相关风险包括：

- 打开或导入不可信 CAD 文件（畸形 STEP/STL/3MF 可能让 SolidWorks 崩溃或耗尽内存）；
- 将导出/截图写到攻击者控制的路径；
- SolidWorks 模态对话框阻塞调用，直到 120 秒超时。

不要对不可信文件或路径运行本服务。路径处理、注入、密钥处理或拒绝服务问题请私下报告。

## 依赖与发布卫生

- 依赖固定在 `uv.lock`；Dependabot 监控 `pyproject.toml` 和 GitHub Actions，
  并启用 Dependabot 安全更新。
- 公开仓库启用了 secret scanning 和 push protection。
- CI 在每个 PR 上跑 lint、类型检查、单测和打包。
- 本分支不发布到 PyPI 或公共 MCP Registry。
