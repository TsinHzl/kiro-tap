# 任务清单：fix-audit-batch-1

## 状态：ARCHIVED

## 任务

### Critical / High
- [x] T1 [C1] 移除 `cli.py` 的 `_kill_stale_kiro_tap_processes` 函数定义及 `main_entry` 中的调用
- [x] T2 [H2] `cli.py` 默认 host 改回 `127.0.0.1`；非 loopback 绑定时打印安全告警
- [x] T3 [H3] `proxy.py` 与 `forward_proxy.py` 两个流式路径加 try/finally 关闭 `upstream_resp`

### Medium
- [x] T4 [M4] `cli.py` `_version_tuple` 纯标准库重写，正确比较 PEP440 预发布/dev/post 版本（不新增依赖）
- [x] T5 [M5] `cli.py` 自动升级改 opt-in（默认关闭）+ 子进程 `start_new_session=True`
- [x] T6 [M6] `dashboard.py` active 会话 error 状态允许恢复 active（统一为 last-record-wins）
- [x] T7 [M7] 评估 `dashboard.py:245` 列表 N+1 → 结论：不改。load_records 仅缓存首次未命中时跑一次，之后 store_summary 缓存兜底，非持续 N+1；summary 聚合本质需全量记录，强改增量风险>收益
- [x] T8 [M8] `forward_proxy.py` 正向 WS `json.loads` 加 try/except 回退
- [x] T9 [M9] `forward_proxy.py` / `proxy.py` 流式响应剥除 content-length 再加 chunked
- [x] T10 [M10] `certs.py` 按 hostname 缓存 `SSLContext`
- [x] T11 [M11] `shared_dashboard.py` `_kill_process_on_port` 杀前校验 cmdline（token 级判定）

### 偏门项
- [x] T12 [E1] `publish.yml` 加测试/lint 门 + action 钉 commit SHA

### 验证
- [x] T13 全量 `py_compile` + 现有 `pytest` 通过；为 M4/M11 等可单测项补测试

## 验收标准
- [ ] `pgrep`/误杀逻辑彻底移除，启动第二个 kiro-tap 不再杀掉已有会话/dashboard
- [ ] 默认绑定为 `127.0.0.1`，显式 `--tap-host 0.0.0.0` 时有醒目告警
- [ ] 客户端中断流式响应后 `upstream_resp` 被关闭（代码层面 try/finally 覆盖两处）
- [ ] `_version_tuple` 对 `0.2.0` > `0.2.0rc1` 等预发布版本比较正确
- [ ] 自动升级默认不触发；子进程不产生僵尸
- [ ] summary 缓存 active 会话在后续成功轮次能恢复 active
- [ ] 正向 WS 收到非法 JSON 不丢 trace（回退 `{"raw": msg}`）
- [ ] 流式响应不再同时出现 Content-Length 与 Transfer-Encoding: chunked
- [ ] SSLContext 按 hostname 缓存命中，不重复写私钥临时文件
- [ ] `_kill_process_on_port` 仅杀确认为 kiro-tap dashboard 的进程
- [ ] publish workflow 有测试门且 action 钉 SHA
- [ ] `pytest` 全绿，`py_compile` 无错
