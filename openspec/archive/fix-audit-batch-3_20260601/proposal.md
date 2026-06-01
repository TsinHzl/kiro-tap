# 变更提案：fix-audit-batch-3

## 背景

对 kiro-tap 全量代码（约 8000 行）做了一次分模块安全/健壮性审计，发现一批新的 Critical/High/Medium 问题，集中在：开放正向代理、CA 私钥保护、未鉴权的破坏性 Web 端点、不可信流输入导致的 OOM/崩溃、事件循环阻塞、资源无界增长。本次按严重程度依次修复。

## 目标范围

**在范围内（按严重程度排序）：**

CRITICAL / HIGH 安全：
- S1 `forward_proxy.py:935-944` 明文代理回退分支无 allowlist 校验 → 开放正向代理/SSRF
- S2 `certs.py:43,96-104` CA 私钥写入存在 umask 窗口 + CA 目录 0755 → 私钥可被同主机其他用户读取
- S3 `live.py` `DELETE /api/traces/{date}` 等变更端点无同源/鉴权 → 任意网页可 CSRF 删除 trace
- S4 `cli.py` 独立 `dashboard` 子命令绑定非环回地址时无暴露告警
- S5 `live.py:235,275` SSE 端点 `Access-Control-Allow-Origin: *` → 任意网页可读实时 trace

HIGH 健壮性（不可信流输入）：
- B1 `sse.py:97,189,224` `index` 来自不可信流，`while len(...) <= idx: append` 巨整数触发 OOM
- B2 `sse.py:24` / `forward_proxy.py:62-95` 流缓冲与手写 body 解析无总量上限 → OOM
- B3 `aws_event_stream.py:370,372` `cacheReadInputTokens`/`cacheCreationInputTokens` 仅判 `is not None` 即 `int()`，非数值类型抛异常穿透致解析器崩溃（注：同函数 `usage_val`:364 / `pct`:376 已有 `isinstance` 守卫，本项仅补 370/372）
- B4 `proxy.py:327` / `forward_proxy.py:585` `except (..., CancelledError): pass` 吞掉取消信号

MEDIUM 资源/性能：
- R1 `trace.py:38-46` `async write()` 在锁内同步调用阻塞 SQLite 写 → 阻塞事件循环
- R2 `trace_store.py:64` `_write_lock` 非可重入，写路径经日志 handler 可二次 acquire 死锁
- R3 `export.py:147-149` `NamedTemporaryFile(delete=False)` 写入抛错则明文 trace 临时文件残留
- R4 `live.py:162-169,438` `broadcast` 遍历客户端 list 时 `await` 让出，迭代中被增删

**不在范围内：**
- 前端 HTML 文件的逻辑改造（仅 R4 涉及后端广播；viewer.html `esc()` 单引号转义留待后续 batch）
- `_records` 无界增长改环形缓冲（B2 仅处理流解析缓冲，会话级记录上限单独评估）
- AWS 重同步 O(n²) 优化（B3 仅修崩溃；性能优化单独评估）
- CA 过期检查、host 证书缓存 LRU、升级子进程 reap（low，单独 batch）
- 数据库 schema / 迁移变更

## 技术方案

- **S1**：`_handle_plain_proxy` 的回退分支（944 行）改为：非 allowlist 匹配的绝对 URL 请求返回 403 并记录日志，不再无条件转发。仅当 `_matches_path_prefix` 通过的本地反代目标才转发。
- **S2**：`ensure_ca` 中 `ca_dir.mkdir(parents=True, exist_ok=True, mode=0o700)` 后显式 `ca_dir.chmod(0o700)`（兼容已存在目录）；私钥用 `os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)` 原子创建后写入，消除 umask 窗口。
- **S3**：新增同源校验辅助函数，对所有 unsafe 方法（DELETE）校验 `Sec-Fetch-Site`（`same-origin`/`none`/`same-site` 放行）或 `Origin` 与 Host 一致；不通过返回 403。`force` query 参数不再对跨源放行（已被同源校验前置拦截）。
- **S4**：`dashboard_main` 在绑定前复用代理路径的非环回告警逻辑（`args.host not in ("127.0.0.1","::1","localhost")` 时 print 警告）。
- **S5**：移除两处 SSE 的 `Access-Control-Allow-Origin: *`。SSE 同源访问不需要该头；移除后跨源 `EventSource` 无法读取。
- **B1**：`sse.py` 三处 `while len(...) <= idx` 前对 `idx` 做上限校验（`MAX_CONTENT_INDEX = 10_000`），超限直接 return（丢弃该 block，不崩溃不分配）。
- **B2**：`SSEReassembler` 与 `AWSEventStreamReassembler` 的 `_buf` 设上限常量（64MB），超限重置缓冲并记录 warning（不崩溃）。`_read_http_body`/`_read_chunked_body` 累计字节超上限（256MB）抛 `ValueError`，由连接级 catch（`_handle_client` 的 `except Exception` / 拦截路径的连接 handler）撕掉连接。**注意**：Content-Length 分支（forward_proxy.py:86-91）外层已有 `except (ValueError, ...): return b""`，上限判定必须放在该 try **之外**（先判 `length > MAX` 再 `readexactly`），否则 ValueError 被就地吞成 `b""`；chunked 分支（94 行在 try 外）累计判定直接 `raise` 即可上抛。
- **B3**：`aws_event_stream.py:370,372` 在 `int(cache_read)`/`int(cache_create)` 前加 `isinstance(..., (int, float))` 守卫（与既有 `usage_val`/`pct` 一致）；`_drain` 中用 try 包住 `_process_frame(frame)`，解析异常不影响缓冲推进。
- **B4**：两处 `except (ConnectionError, asyncio.CancelledError): pass` 拆分为 `except asyncio.CancelledError: raise` + `except ConnectionError: pass`，恢复取消语义。
- **R1**：`TraceWriter.write` 把 `self._store.append_record(...)` 改为 `await loop.run_in_executor(None, ...)`，把**每条记录的热路径**写入移出事件循环；统计字段更新仍在锁内。`close()` 为 shutdown 时单次调用（cli.py:623，async 函数末尾，非热路径），其内部同步 `finalize_session` 保持不变——由 R2 的 RLock 串行化 finalize 与在途 append，不引入 pending-future 跟踪（避免新竞态）。close 单次阻塞为已知小取舍。
- **R2**：`trace_store.py:64` `_write_lock` 改 `threading.RLock()`，消除写路径经日志 handler 的同线程二次 acquire 死锁，并串行化 R1 后的并发 executor 写入与 finalize。
- **R3**：`export.py` HTML 导出的临时文件创建与清理改为单一 `try/finally`，先取 `tmp.name` 再写入，写入异常也能 `unlink`。
- **R4**：`broadcast` / `_broadcast_dashboard_event` 遍历前对客户端列表做快照（`list(self._sse_clients)`），避免迭代中被并发增删；移除失败客户端时用守卫式删除（`if client in self._sse_clients: remove`，与 `_handle_sse` finally 的删除方式一致），避免对已被并发移除的 client 二次 `remove` 抛 `ValueError`。

## 预期影响

- **S1**：非白名单的明文代理请求被拒（403）；正常 CONNECT 隧道与白名单本地反代不受影响。**行为变更**：任何把 kiro-tap 当通用明文正向代理的用法（GET http://任意域/...）会统一返 403；本地反代的 scheme-less 路径走 935-942 分支不受影响。
- **S2**：CA 私钥与目录对其他用户不可读；功能行为不变。
- **S3**：跨源页面无法删除 trace；同源 dashboard UI 的删除按钮正常（同源请求带 `Sec-Fetch-Site: same-origin`）。
- **S4**：dashboard 绑非环回地址时给出与代理一致的安全告警。
- **S5**：跨源 `EventSource` 无法连接 SSE；同源 dashboard/viewer 实时刷新不受影响。
- **B1/B3**：畸形或恶意流输入不再触发 OOM 或解析器崩溃，转为安全丢弃该 block / 置 0。
- **B2**：流缓冲超上限时不再 OOM；**行为变更**：超限重置会丢弃一条跨界 SSE 行、可能产出一条损坏解析行——对攻击/异常流属有意丢弃，正常响应不受影响（上限远大于正常单帧）。
- **B4**：服务关闭/客户端断开时取消信号正确传播，不再写出半截 trace。
- **R1**：每条记录的 SQLite 写入不再阻塞事件循环，提升并发抓包吞吐；close 单次 finalize 仍同步（shutdown 路径，影响可忽略）。
- **R2**：消除潜在死锁路径，并串行化 R1 后的并发写入。
- **R3**：导出异常时不残留明文临时文件。
- **R4**：广播过程中客户端增删不再导致漏发/迭代异常。

## 风险

- **S3**：同源校验依赖浏览器发送 `Sec-Fetch-Site`（现代浏览器均支持）；老旧浏览器或非浏览器客户端（如 curl）不带该头——方案对「无 Origin 且无 Sec-Fetch-Site」按 same-origin 放行（保持 CLI/本地脚本可用），仅拦截明确跨源（`Sec-Fetch-Site: cross-site`，或 Origin 与 Host 不一致）的请求。已确认 dashboard 前端删除为同源 fetch，T3 单测覆盖三态。
- **S5**：若有用户依赖跨源读取 SSE（非预期用法），会失效——属安全修复的预期取舍。
- **B2**：缓冲上限取足够大（SSE 64MB / body 256MB）以不误伤正常大响应；超限是异常路径。
- **R1**：仅热路径 `append_record` 移出事件循环，`close()`/`finalize_session` 保持同步。R2 的 RLock 串行化 finalize 与在途 executor append，二者不会真正并发写同一 SQLite 连接（连接为 thread-local，executor 用默认线程池）——需在实现时确认 executor 线程与 finalize 调用线程对同一 session 的写入由 RLock 串行。**不**引入 pending-future 跟踪，避免新竞态。
- **R2**：`RLock` 开销略高于 `Lock`，可忽略。

## 测试

为关键修复增加确定性单测（新增 `tests/test_audit_batch_3.py`），纳入 T14 验收：
- S1：明文代理非白名单绝对 URL → 403，不调用上游
- S3：DELETE 三态——Origin==Host 放行 / `Sec-Fetch-Site: cross-site` 返 403 / 无 Origin 无 Sec-Fetch 放行
- B1：`content_block_start` 的 `index` 为巨整数 → 不分配、安全 return
- B3：`cacheReadInputTokens` 为字符串/dict → 解析器不崩溃，置 0 或跳过
