# 任务清单：fix-audit-batch-2

## 状态：DRAFT

## 任务

### Low 逻辑/安全
- [ ] T1 [L1] `forward_proxy.py` `_read_http_body`/`_read_chunked_body` 读失败改为抛异常；两处调用方捕获后中止请求
- [ ] T2 [L2] `trace_store.py:78` `date_key` 改为 UTC 日期（`now.date()` 而非 `now.astimezone().date()`）
- [ ] T3 [L3] `certs.py` CA 目录 `mkdir` 后加 `chmod(0o700)`
- [ ] T4 [L4] `pyproject.toml` 声明 `psutil` 为可选依赖（`[project.optional-dependencies] extras`）
- [ ] T5 [L5] `trace_log_handler.py` 日志时间戳改为 `%Y-%m-%d %H:%M:%S`
- [ ] T6 [L6] `export.py` Markdown 导出 thinking 内容做 HTML 实体转义
- [ ] T7 [L7] `cli.py` `parse_known_args` 后检测 `client_args` 中的 `--tap-*` 残留并报错

### Lint
- [ ] T8 [R1] 对 7 个文件跑 `ruff --fix`（I001 ×4 + F401 ×3），验证 `ruff check .` 零错误
- [ ] T9 [R2] `publish.yml` 移除 ruff 步骤的 `continue-on-error: true`（依赖 T8 完成）

### 验证
- [ ] T10 全量 `py_compile` + `pytest` 24 项全绿 + `ruff check .` 零错误

## 验收标准
- [ ] `_read_http_body` 读失败时请求被中止，不再发空 body 给上游
- [ ] 新会话的 `date_key` 与 `started_at` 均为 UTC 日期，无时区不一致
- [ ] `~/.kiro-tap` 目录权限为 0700
- [ ] `pip install kiro-tap[extras]` 可安装 psutil
- [ ] 日志时间戳格式为 `YYYY-MM-DD HH:MM:SS`
- [ ] Markdown 导出的 thinking 内容中 `<>&"'` 被转义，无法注入 HTML
- [ ] `kiro-tap --tap-prot 8080` 等拼写错误立即报错，不透传
- [ ] `ruff check .` 零错误
- [ ] publish.yml ruff 步骤无 `continue-on-error`，lint 失败会阻塞发布
- [ ] `pytest` 24 项全绿，`py_compile` 无错
