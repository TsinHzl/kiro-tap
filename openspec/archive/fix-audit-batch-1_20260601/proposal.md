# 变更提案：fix-audit-batch-1

## 背景

对仓库做了三路并行代码审计（网络代理层 / CLI·证书层 / 数据·展示层），交叉验证后确认了一批真实 bug、安全问题与性能问题。本次变更修复其中全部 Critical/High/Medium 项，外加 4 个用户明确纳入的偏门项。

## 目标范围

**在范围内（共 12 项 + 4 偏门项）：**

Critical/High：
- C1 `_kill_stale_kiro_tap_processes` 误杀（`cli.py:1066-1088,1113`）→ **直接移除调用与函数**
- H2 `--tap-no-launch` 默认绑 `0.0.0.0`（`cli.py:836-837`）→ **默认改回 127.0.0.1 + 非 loopback 绑定时打印醒目告警**
- H3 流式响应 `upstream_resp` 客户端中断时泄漏（`proxy.py:317-322`、`forward_proxy.py:573-581`）→ **两处都加 try/finally 关闭**

Medium：
- M4 `_version_tuple` 误判 rc/dev/post 版本（`cli.py:952-954`）→ **纯标准库重写为能正确比较 PEP440 预发布版本的解析**
- M5 后台自动升级风险（`cli.py` 自动升级路径）→ **改为 opt-in（默认关闭）+ 子进程 detach 防僵尸**
- M6 summary 缓存 active 会话 error 状态 sticky（`dashboard.py:219`）→ **后续成功轮次允许恢复 active**
- M7 列表页 N+1 全量 `load_records`（`dashboard.py:245`）→ **本次仅评估，若低风险则改增量；见技术方案**
- M8 正向 WS `json.loads` 未保护丢 trace（`forward_proxy.py:874,882`）→ **复用安全解析，try/except 回退 `{"raw": msg}`**
- M9 流式响应同时发 `Content-Length` + `Transfer-Encoding: chunked`（`forward_proxy.py:559-564`、`proxy.py:306-309`）→ **改 chunked 前剥除 content-length**
- M10 `make_ssl_context` 每次 CONNECT 写私钥临时文件 + 重建 context（`certs.py:256-277`）→ **按 hostname 缓存 SSLContext**
- M11 `_kill_process_on_port` 杀任意占端口进程（`shared_dashboard.py:204-235`）→ **杀前校验 cmdline 是 kiro-tap dashboard**

偏门项（用户明确纳入）：
- E1 publish.yml 加固 → **加测试/lint 门 + action 钉 SHA**
- （E2 自动升级 opt-in = M5；E3 `_kill_process_on_port` 校验 = M11；E4 summary error 恢复 = M6，已合并到上面）

**不在范围内：**
- Low 项（`_read_http_body` 静默空 body、时区不一致、CA 目录 0700、psutil 依赖声明、日志时间戳丢日期、Markdown `<details>` 转义、拼错 flag 透传）—— 本次不动
- H2 的「dashboard API token 鉴权 / CORS 收紧 / body 全量脱敏」—— 用户选择最小加固，本次仅默认 loopback + 告警
- 前端 HTML 文件 —— 本次不涉及
- 已排除的非问题（SQL 注入、viewer XSS、WAL/事务）

## 技术方案

- **C1**：删除 `_kill_stale_kiro_tap_processes` 函数定义与 `main_entry` 中的调用；依赖现有 `shared_dashboard` 端口复用机制。
- **H2**：`args.host` 默认恒为 `127.0.0.1`；在 server 启动处检测 host 非 loopback 时 `print` 醒目安全告警（无鉴权暴露）。
- **H3**：两个流式路径将 `upstream_resp` 用 `try/finally` 包裹，finally 中 `upstream_resp.close()`（硬关，body 已部分消费）。
- **M4**：纯标准库重写 `_version_tuple`（或新增比较函数），正确解析 PEP440 版本：拆分主版本数字段与预发布/dev/post 后缀，使 `0.2.0` > `0.2.0rc1`、`0.2.0` > `0.2.0.dev3`、`0.2.1` > `0.2.0` 等比较全部正确。**不引入任何新依赖。**
- **M5**：自动升级默认关闭，新增显式开启开关；`Popen` 加 `start_new_session=True`（detach）。
- **M6**：`dashboard.py:219` 缓存读取路径，active 会话 `db_count>0` 时无条件设 active（不再保留 sticky error）；需与 `merge_record_into_summary` 语义对齐。
- **M7**：评估列表路径能否改用增量/边界记录避免全量 `load_records`；若改动风险可控则改，否则降级为 Low 留待后续（实施时确认）。
- **M8**：正向 WS 路径复用 `ws_proxy.py` 的安全解析模式（try/except json.loads → `{"raw": msg}`）。
- **M9**：流式响应构造时从拷贝的上游 header 中剥除 `content-length` 再加 `Transfer-Encoding: chunked`。
- **M10**：`certs.py` 增加按 hostname 的 `SSLContext` 缓存，命中则复用，避免重复写私钥临时文件。
- **M11**：`_kill_process_on_port` SIGTERM 前用 `ps`/psutil 读目标 cmdline，确认含 `kiro-tap` + `dashboard` 才杀。
- **E1**：publish.yml 增加依赖测试/lint 的 job，publish 依赖其通过；actions 由可变 tag 改为 commit SHA 钉死。

## 预期影响

- **行为变更**：no-launch 模式默认绑定从 0.0.0.0 改为 127.0.0.1（破坏性：远程代理用户需显式 `--tap-host 0.0.0.0`）；自动升级默认关闭（用户需手动 opt-in）。
- **并发**：移除误杀后，多会话/共享 dashboard 行为更稳定。
- **性能**：M10 减少每连接磁盘 I/O；M7（若实施）减少列表接口内存与全表读。
- **兼容性**：不新增任何运行时依赖（M4 用纯标准库实现，不再引入 `packaging`）。

## 风险

- **M6 语义风险**：恢复 active 可能掩盖「会话确实出错」的状态，需确认 error 是 per-record 还是 session-level 语义后再改。
- **M7 改动风险**：summary 增量维护若遗漏边界，列表统计可能不准 —— 故设为「评估后决定」，不强行改。
- **H2 破坏性**：远程部署用户升级后代理不再对外可达，需在 commit/changelog 说明。
- **M5 破坏性**：依赖自动升级的用户升级后将不再自动更新。
- 所有改动遵循 surgical 原则，不重排无关代码。
