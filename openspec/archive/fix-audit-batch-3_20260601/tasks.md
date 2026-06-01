# 任务清单：fix-audit-batch-3

## 状态：ARCHIVED

## 任务

### CRITICAL / HIGH 安全
- [x] T1 [S1] `forward_proxy.py:935-944` 明文代理回退分支：非 allowlist 目标返回 403，不转发
- [x] T2 [S2] `certs.py:43,96-104` CA 目录 `mkdir(mode=0o700)`+`chmod(0o700)`；私钥用 `os.open(...,0o600)` 原子写
- [x] T3 [S3] `live.py` 新增同源校验辅助，`_handle_delete_traces_by_date` 跨源返回 403
- [x] T4 [S4] `cli.py` `dashboard_main` 绑定前加非环回暴露告警
- [x] T5 [S5] `live.py:235,275` 移除两处 SSE 的 `Access-Control-Allow-Origin: *`

### HIGH 健壮性
- [x] T6 [B1] `sse.py:95,189,224` 三处 `idx` 加 `MAX_CONTENT_INDEX` 上限校验，超限 return
- [x] T7 [B2] `sse.py`/`aws_event_stream.py` `_buf` 设上限；`forward_proxy.py` body 读取累计上限抛 `ValueError`
- [x] T8 [B3] `aws_event_stream.py:370,372` `int(cache_read)`/`int(cache_create)` 加 `isinstance` 守卫；`_drain` try 包住 `_process_frame`
- [x] T9 [B4] `proxy.py:327`/`forward_proxy.py:585` 拆分 except，`CancelledError` 重新 raise

### MEDIUM 资源/性能
- [x] T10 [R1] `trace.py:44` 热路径 `append_record` 改 `run_in_executor` 移出事件循环；`close()`/`finalize_session` 保持同步，由 RLock 串行化
- [x] T11 [R2] `trace_store.py:64` `_write_lock` 改 `threading.RLock()`
- [x] T12 [R3] `export.py:145-153` HTML 导出临时文件改单一 `try/finally`，写入异常也清理
- [x] T13 [R4] `live.py` `broadcast`/`_broadcast_dashboard_event` 遍历前 `list()` 快照 + 守卫式删除

### 测试与验证
- [x] T14 新增 `tests/test_audit_batch_3.py`：S1(403)、S3(三态)、B1(超限 return)、B3(非数值不崩) 确定性单测
- [x] T15 全量 `py_compile` + `ruff check .` 零错误 + `pytest` 全绿（含新增用例）
- [x] T16 Sub-agent 独立 Code Review，PASS 后进入归档

## 验收标准
- [ ] 非白名单绝对 URL 的明文代理请求返回 403，不转发到上游
- [ ] `~/.kiro-tap` 目录权限 0700，`ca-key.pem` 创建即 0600（无 umask 窗口）
- [ ] 跨源 `fetch(DELETE /api/traces/...)` 被拒 403；同源 dashboard 删除正常
- [ ] dashboard 绑定 `0.0.0.0` 时打印暴露告警
- [ ] 跨源 `EventSource` 无法读取 SSE；同源实时刷新正常
- [ ] 流中 `index` 为巨整数时不 OOM，安全丢弃该 block
- [ ] 流缓冲/body 读取超上限时不 OOM，抛错或重置
- [ ] token 字段为非数值类型时解析器不崩溃
- [ ] 服务关闭时取消信号正确传播，无半截 trace 写出
- [ ] SQLite 写入不在事件循环线程执行
- [ ] `_write_lock` 为 RLock，写路径经日志 handler 不死锁
- [ ] 导出写入异常时无明文临时文件残留
- [ ] 广播遍历客户端时并发增删不报错
- [ ] `pytest` 全绿，`py_compile` 无错，`ruff check .` 零错误
