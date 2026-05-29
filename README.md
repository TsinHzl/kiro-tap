# kiro-tap

[![Python version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

`kiro-tap` 是 Kiro CLI 和 Kiro IDE 的本地代理与请求追踪工具。通过它运行 Kiro，即可实时捕获所有 API 请求：系统提示词、对话历史、工具定义、工具调用、流式响应和 Token 用量。

支持 [Kiro CLI](https://kiro.dev)（`kiro-cli-chat`）和 [Kiro IDE](https://kiro.dev)。

## 为什么用它

- 👀 **看清真实上下文**：查看发往 Kiro API 的完整请求，包括系统提示、消息历史、工具定义、工具调用和响应内容
- 🔎 **有据可查地调试**：对比相邻请求，精确定位哪条消息、哪个工具或哪个参数发生了变化
- 📦 **一个可分享的文件**：每次运行生成本地 trace，可导出为自包含的 HTML 查看器，方便存档或分享
- 🔒 **数据留在本机**：无需任何云端 Dashboard，常见认证 Header 在记录前自动脱敏
- ⚡ **AWS Event Stream 原生支持**：正确解析 Kiro 使用的 AWS Event Stream 二进制帧协议，完整还原流式响应

## 安装

需要 Python 3.11+。

```bash
# 推荐
uv tool install kiro-tap

# 或使用 pip
pip install kiro-tap
```

升级：`kiro-tap update`、`uv tool upgrade kiro-tap` 或 `pip install --upgrade kiro-tap`

## 快速开始

```bash
# Kiro CLI（默认，实时 Dashboard 默认开启）
kiro-tap

# Kiro IDE
kiro-tap --tap-client kiro-ide

# 关闭实时 Dashboard
kiro-tap --tap-no-live

# 不自动打开浏览器
kiro-tap --tap-no-open
```

## 工作原理

```
kiro-tap 启动本地正向代理
    ↓
注入 HTTPS_PROXY + SSL_CERT_FILE 到子进程环境
    ↓
启动 kiro-cli-chat（或 kiro）
    ↓
所有 HTTPS 流量经过本地代理 → TLS 终止 → 转发到 q.us-east-1.amazonaws.com
    ↓
AWS Event Stream 二进制帧解析 → 重建完整响应
    ↓
写入本地 SQLite trace 数据库
    ↓
实时推送到浏览器 Dashboard（SSE）
```

kiro-tap 使用**正向代理模式**（CONNECT + TLS 终止），因为 Kiro CLI 没有暴露 base URL 环境变量。代理会自动生成本地 CA 证书并注入到子进程，无需 sudo。

## CLI 选项

所有 `--tap-*` 之外的参数都会透传给 Kiro 客户端。

```
--tap-client CLIENT      要启动的客户端：kiro（默认）或 kiro-ide
--tap-target URL         上游 API URL（默认：https://q.us-east-1.amazonaws.com）
--tap-live               运行时开启实时 Dashboard（默认：开）
--tap-no-live            关闭实时 Dashboard
--tap-live-port PORT     实时 Dashboard 端口（默认：19528）
--tap-no-open            不自动在浏览器中打开 Dashboard 或生成的 HTML
--tap-output-dir DIR     旧版 trace 目录（默认：./.traces）
--tap-port PORT          代理端口（默认：自动）
--tap-host HOST          绑定地址（默认：127.0.0.1）
--tap-no-launch          只启动代理，不启动客户端
--tap-max-traces N       保留的最大 trace 会话数（默认：50，0 = 不限）
--tap-store-stream-events 持久化原始 AWS Event Stream 帧数组（默认：关）
--tap-no-update-check    禁用启动时的 PyPI 更新检查
--tap-no-auto-update     检查更新但不自动下载
--tap-trust-ca           在 macOS 用户登录钥匙串中信任本地 CA（无需 sudo）
```

## 子命令

```bash
# 浏览历史 trace
kiro-tap dashboard

# 将 JSONL trace 导出为 HTML / Markdown / JSON
kiro-tap export .traces/session.jsonl -o trace.html

# 升级 kiro-tap
kiro-tap update

# 在 macOS 钥匙串中信任本地 CA（正向代理模式需要）
kiro-tap trust-ca
```

## 仅代理模式

```bash
# 只启动代理，在另一个终端手动启动 Kiro
kiro-tap --tap-no-launch --tap-port 8080

# 然后在另一个终端：
HTTPS_PROXY=http://127.0.0.1:8080 SSL_CERT_FILE=~/.kiro-tap/ca.pem kiro-cli-chat
```

## Viewer 功能

生成的 HTML 查看器（零外部依赖）支持：

- **结构化 Diff**：对比相邻请求，查看消息、系统提示、工具的变化
- **路径过滤**：按 API 端点过滤（如只看 `/generateAssistantResponse`）
- **Token 用量**：输入 / 输出 / 缓存读取 / 缓存写入
- **工具检查器**：可展开的工具卡片，含名称、描述和参数 schema
- **全文搜索**：跨消息、工具、提示词和响应搜索
- **深色模式**：跟随系统偏好
- **键盘导航**：`j`/`k` 或方向键
- **一键复制**：复制请求 JSON 或 cURL 命令
- **多语言**：English、简体中文、日本語、한국어、Français、العربية、Deutsch、Русский

## 技术说明

### AWS Event Stream 解析

Kiro API 使用 AWS Event Stream 二进制帧协议（非标准 SSE）。kiro-tap 实现了完整的帧解析器：

- CRC32 校验（ISO-HDLC，与 AWS SDK 一致）
- 所有 Header 值类型（bool、byte、short、int、long、bytes、string、timestamp、uuid）
- 事件类型：`assistantResponseEvent`、`toolUseEvent`、`meteringEvent`、`contextUsageEvent`、`codeReferenceEvent`
- 错误/异常消息类型

### 与 claude-tap 的差异

| 项目 | claude-tap | kiro-tap |
|------|-----------|---------|
| 目标客户端 | Claude Code | Kiro CLI / Kiro IDE |
| 代理模式 | 反向代理（默认） | 正向代理（唯一选项） |
| 响应格式 | SSE | AWS Event Stream 二进制 |
| CA 注入 | NODE_EXTRA_CA_CERTS | SSL_CERT_FILE + NODE_EXTRA_CA_CERTS |
| Dashboard 端口 | 19527 | 19528 |
| 上游 | api.anthropic.com | q.us-east-1.amazonaws.com |

## 许可证

MIT
