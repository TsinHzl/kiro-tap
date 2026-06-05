# 项目上下文

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.11 / 3.12 / 3.13 |
| 异步框架 | asyncio（标准库）+ aiohttp 3.9–4 |
| TLS / 证书 | cryptography 42+ |
| 压缩 | backports-zstd（Python < 3.14）|
| 持久化 | SQLite（标准库 sqlite3），schema v3 |
| 打包 | setuptools + setuptools-scm（版本从 git tag `v*` 派生）|
| 构建 | `python -m build`，发布至 PyPI |
| 前端 | 纯内联 HTML/CSS/JS，无构建工具，CSS 变量驱动主题 |
| Lint | ruff 0.11+（target py311，line-length 120，select E/F/W/I）|
| 测试 | pytest 8+ + pytest-asyncio（asyncio_mode=auto）+ pexpect + coverage |

## 架构约定

### 双代理模式

| 模式 | 触发 | 传输 |
|------|------|------|
| Forward（默认） | `--tap-proxy-mode forward` | 原始 asyncio TCP；HTTP CONNECT + TLS 终止；本地 CA 证书注入（`SSL_CERT_FILE` + `HTTPS_PROXY`）|
| Reverse | `--tap-proxy-mode reverse` | aiohttp web app；设置 `KIRO_BASE_URL` 到本地端口 |

### 核心不变量
- `proxy.py:ALLOWED_PATH_PREFIXES` 是安全门控，不在列表中的路径返回 404，从不转发
- 敏感 header（`authorization`、`x-api-key`、`cosy-*`）在持久化前脱敏，逻辑集中在 `proxy.py`
- `TraceStore` 是进程级单例；测试中用 `KIROTAP_DB` env var 重定向到临时文件 + `reset_trace_store()` 清理
- SQLite 写入必须通过线程池（`run_in_executor`），不在事件循环中直接调用
- 版本号从 git tag 派生，tag 格式 `v*`（如 `v0.2.0`）

### 前端约定
- 样式全部内联在 HTML 文件的 `<style>` 标签中
- CSS 变量驱动主题（`:root` + `[data-theme="dark"]`）
- 无外部 CSS 框架、无构建步骤，直接编辑 HTML 文件

## 目录结构

```
kiro_tap/          # 主包（15 个模块）
  cli.py           # 入口点、子命令分发、参数解析、代理启动
  forward_proxy.py # ForwardProxyServer：asyncio TCP + CONNECT + 动态 TLS 证书
  proxy.py         # aiohttp 反向代理处理器、路径 allowlist、header 脱敏
  aws_event_stream.py  # AWS Event Stream 二进制帧解析（CRC32 验证）
  sse.py           # SSE 文本流重组（非 AWS Event Stream 的降级路径）
  ws_proxy.py      # WebSocket 代理支持
  trace_store.py   # TraceStore 单例（SQLite，线程安全，schema v3）
  trace.py         # TraceWriter：异步包装 TraceStore，累计 token 统计
  trace_log_handler.py  # logging.Handler：代理日志写入 SQLite logs 表
  live.py          # LiveViewerServer：aiohttp dashboard、SSE 流、HTML 导出
  shared_dashboard.py  # 跨进程共享 dashboard（文件锁，默认端口 19528）
  dashboard.py     # SQLite 查询辅助 + dashboard HTML 模板加载
  viewer.py        # 生成自包含 HTML trace 查看器
  certs.py         # 本地 CA 生成与持久化，macOS keychain 信任（无需 sudo）
  history.py       # 会话清理、JSONL→SQLite 迁移
  export.py        # CLI export：SQLite/JSONL → Markdown/JSON/HTML
  usage.py         # 标准化不同 API 响应形态的 token 用量字段
  dashboard.html   # 会话列表页前端（内联 HTML/CSS/JS）
  viewer.html      # 请求详情查看器前端（内联 HTML/CSS/JS）

tests/             # pytest 测试套件
  conftest.py      # 公共 fixture；--run-real-e2e 标志
  test_aws_event_stream.py
  test_path_allowlist.py
  test_kiro_launch.py
  test_audit_batch_3.py

openspec/          # OpenSpec 规范工作流
  config.yaml      # 项目约束注入（由 /opsx:init 维护）
  project.md       # 本文件
  changes/         # 进行中的变更
  archive/         # 已归档变更
  specs/           # 最终规范归档
```

## 开发约定

### CLI 参数命名空间
- 所有 kiro-tap 专属参数使用 `--tap-*` 前缀
- 通过 `parse_known_args` 隔离，其余参数透传给 kiro 客户端

### 测试隔离
- `KIROTAP_DB=<tmpfile>` + `reset_trace_store()` 每次测试后清理 SQLite 状态
- async 测试函数无需 `@pytest.mark.asyncio`（asyncio_mode=auto）
- `--run-real-e2e` 门控需要 `kiro-cli-chat` in PATH 的真实测试

### 虚拟环境
- `.venv/` — 生产依赖
- `.venv-test/` — 开发 + 测试依赖（`pip install -e ".[dev]"`）

### 存储路径
- SQLite 默认：`~/.local/share/kiro-tap/traces.sqlite3`
- 本地 CA：`~/.kiro-tap/ca.pem`
- Dashboard 共享锁：`~/.local/share/kiro-tap/dashboard.lock`
- 环境变量覆盖：`KIROTAP_DB`、`KIROTAP_DASHBOARD_PORT`
