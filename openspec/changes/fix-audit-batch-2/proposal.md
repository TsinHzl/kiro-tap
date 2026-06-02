# 变更提案：fix-audit-batch-2

## 背景

fix-audit-batch-1 修复了全部 Critical/High/Medium 问题。本次修复剩余的 7 个 Low 级别逻辑/安全问题，以及 7 项 pre-existing ruff lint 问题（import 排序 + unused import），并恢复 publish.yml 的 ruff 阻塞门。

## 目标范围

**在范围内：**

Low 逻辑/安全：
- L1 `_read_http_body` 读失败静默返回空 body → 改为抛异常，调用方中止请求
- L2 `date_key` 用本地时区，`started_at` 用 UTC → `date_key` 改为 UTC 日期
- L3 CA 目录 `~/.kiro-tap` 权限 0755 → 改为 0700
- L4 `psutil` 未声明依赖 → `pyproject.toml` 声明为可选依赖
- L5 日志时间戳只有 `%H:%M:%S` 丢失日期 → 改为 `%Y-%m-%d %H:%M:%S`
- L6 Markdown 导出 `<details>` thinking 块不转义 → 对 thinking 内容做 HTML 实体转义
- L7 拼错的 `--tap-*` flag 被静默透传给 kiro 客户端 → `parse_known_args` 后检测并报错

Lint：
- R1 7 项 pre-existing ruff 问题（I001 import 排序 ×4 + F401 unused import ×3）→ `ruff --fix` 自动修复
- R2 publish.yml ruff 步骤恢复阻塞（移除 `continue-on-error: true`）

**不在范围内：**
- 任何 Critical/High/Medium 问题（已在 batch-1 修复）
- 前端 HTML 文件
- 数据库迁移（date_key 历史数据不回填，仅影响新会话）

## 技术方案

- **L1**：`_read_http_body` 在 `except (ValueError, asyncio.IncompleteReadError, asyncio.TimeoutError)` 分支改为 `raise`，调用方(426/928)捕获后 `break`/返回 502 并记录日志。`_read_chunked_body` 中**仅改读取错误分支**（`ValueError` on bad size token、`readexactly` 超时/不完整）为 `raise`；`size == 0` 是正常 chunked 结束信号，对应的 `break` **保持不变**。
- **L2**：`trace_store.py:78` `now.astimezone().date()` → `now.date()`（`now` 已是 UTC，直接取 `.date()` 即为 UTC 日期）。历史数据不回填；已落库的旧记录 `date_key` 仍为本地日期，与新记录在时区偏移边界附近可能出现日期错位——已知取舍，接受此不一致。
- **L3**：`certs.py:43` `ca_dir.mkdir(parents=True, exist_ok=True)` 后加 `ca_dir.chmod(0o700)`。
- **L4**：`pyproject.toml` 新增 `optional-dependencies.extras = ["psutil>=5.9"]`。调用方（`shared_dashboard.py` 两处）已有 `except ImportError: pass` fallback，无需修改调用点。
- **L5**：`trace_log_handler.py:31` `strftime("%H:%M:%S")` → `strftime("%Y-%m-%d %H:%M:%S")`。
- **L6**：`export.py:263` 对 `thinking` 内容做 HTML 实体转义（`< > & " '`），再插入 `<details>` 块。
- **L7**：`cli.py` `parse_known_args` 后，遍历 `client_args`，若有以 `--tap-` 开头的项则 `tap_parser.error(...)` 报错提示用户。`--tap-` 是本工具专属命名空间前缀，kiro/kiro-ide 客户端均不使用此前缀，不存在合法透传场景。
- **R1**：对 7 个文件跑 `ruff --fix`（仅 I001/F401，不改逻辑）。**必须在 R2 之前完成并验证 `ruff check .` 零错误。**
- **R2**：`publish.yml` 删除 ruff 步骤的 `continue-on-error: true`。**依赖 R1 完成**，否则恢复阻塞后 CI 会立即失败。

## 预期影响

- **L1**：读 body 失败的请求不再被静默转发为空 body 请求；连接会被中止，客户端收到连接断开或 502。
- **L2**：新会话的 `date_key` 与 `started_at` 时区一致；历史数据不受影响（不回填）。UTC+8 用户深夜的会话 `date_key` 会是 UTC 日期（比本地日期早一天），这是已知取舍。
- **L3**：CA 目录对其他用户不可读，防御性加固。
- **L4**：`pip install kiro-tap[extras]` 可自动装 psutil；不装时 fallback 行为不变。
- **L5**：日志跨日期时可区分，不影响现有日志格式解析。
- **L6**：Markdown 导出的 thinking 内容不再能注入 HTML/脚本。
- **L7**：`--tap-prot 8080` 等拼写错误会立即报错，不再静默透传。
- **R1/R2**：CI ruff 门恢复阻塞，代码库 lint 全干净。

## 风险

- **L1**：调用方改动需仔细，两处调用点结构不同（循环 vs 单次），需分别适配。
- **L2**：UTC+8 用户深夜会话的 date_key 会是"昨天"（UTC 日期），与本地日期不符——这是 UTC 统一的固有取舍，已在预期影响中说明。
- **L7**：若用户确实需要把 `--tap-` 前缀的参数传给 kiro（极不可能，kiro 不用此前缀），会被误报错。风险极低。
- **R1**：`ruff --fix` 只改 import 顺序和删 unused import，不改逻辑，风险极低。
