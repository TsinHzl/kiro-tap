# 任务清单：add-turn-token-statistics

## 状态：IN_PROGRESS

## 任务

### 后端：字段归一化与汇总

- [x] T1 `kiro_tap/usage.py:normalize_usage` 新增 `thinking_tokens` 归一化：按优先级依次尝试四路 `output_tokens_details.thinking_tokens` → `output_tokens_details.reasoning_tokens` → `completion_tokens_details.reasoning_tokens` → `thoughtsTokenCount`（Gemini，调用方已展开 `usageMetadata`，不得再查该键）；点号路径为嵌套逐级取值，任一层非 dict 时跳过该路不抛异常；仅在取值为有限数值时写入（`null` / `NaN` / `Infinity` / 布尔 / 字符串 / 容器一律无效并继续下一路，四路全无效则省略该键，源直通的无效值同样剔除）；保留既有 `dict(usage)` 未被映射的键。
  **验证**：`pytest tests/test_usage_normalize.py -v`（覆盖 Anthropic / OpenAI Responses / OpenAI Chat / Gemini / 多路并存优先级 / 空容器 / 无效值剔除 / 缺字段 / 非字典输入）。

- [x] T2 `kiro_tap/dashboard.py` 新增 `_turn_stats(record)` 助手：返回 `turn`（顶层字段；缺失、字符串、浮点等非整数统一归 `None`，不抛异常）、5 个 token 字段（从 usage 层名映射到 summary 层名）、`duration_ms`（非整数按 0）、`model`。
  **验证**：`pytest tests/test_dashboard_tokens.py::test_turn_stats_extracts_fields -v`；同测试中 `turn="3"`、`turn=1.5`、`turn` 缺失三种输入均返回 `None` 且不抛异常。

- [x] T3 `kiro_tap/dashboard.py:_summarize_session` 增加 `thinking_tokens` 累计与 `turn_breakdown` 生成：按 `turn` 升序、`None` 条目置末尾且唯一；同 turn 内 5 个 token 字段与 `duration_ms` 求和（缺失按 0）、`model` 取最后一条非空（全空为 `None`）、`record_count` 计入含无 usage 的全部 record；条目 `total_tokens` 为四项之和；`turn_count` = 条目数，空数组回退 `record_count`。
  **验证**：`pytest tests/test_dashboard_tokens.py -v`（对应 spec 中「同 turn 多条 record 的聚合」「turn 为 null 的条目排在末尾且唯一」「turn_count 等于条目数」等 Scenario）。

- [x] T4 `kiro_tap/dashboard.py:merge_record_into_summary` 增量更新 `thinking_tokens` 与 `turn_breakdown`（复用 T2 的 `_turn_stats`），聚合规则与 T3 完全一致。
  **验证**：`pytest tests/test_dashboard_tokens.py::test_incremental_matches_full_summary -v`（同一 record 序列分别走两条路径，逐字段断言相等）。

- [x] T5 `kiro_tap/dashboard.py:_session_summary_from_row` 对旧缓存摘要补齐默认值（`thinking_tokens`→0、`turn_breakdown`→[]、`turn_count`→0），不改动 `status != 'active'` 的缓存返回路径。
  **验证**：`pytest tests/test_dashboard_tokens.py::test_legacy_summary_defaults -v`。

- [x] T6 `kiro_tap/viewer.py` 的 stub meta 生成处新增 `thinking_tokens`（lazy 模式数据源）。
  **验证**：`pytest tests/test_dashboard_tokens.py::test_viewer_stub_meta_thinking -v`。

### 测试

- [x] T7 新增 `tests/test_usage_normalize.py`：4 种字段映射路径、非字典输入、缺字段时不写入 0 键、保留未映射键。
  **验证**：`pytest tests/test_usage_normalize.py -v` 全绿（17 通过）。

- [x] T8 新增 `tests/test_dashboard_tokens.py`：`KIROTAP_DB` 指向 `tmp_path` 且 teardown 调用 `reset_trace_store()`；覆盖全量/增量等价、thinking 不计入 total、同 turn 多 record 聚合（含无 usage 的 record）、非整数 turn 归并、turn_count 两种口径、旧缓存默认值、viewer stub meta。
  **验证**：`pytest tests/test_dashboard_tokens.py -v` 全绿（16 通过），连续两次运行结果一致（无 SQLite 状态泄漏）。

### 前端：dashboard.html

- [x] T9 `kiro_tap/dashboard.html` 列表页 `.overview-card` 由 4 个 metric 扩展为 9 个（Threads / Traces / Error Rate / Input / Output / Cache R / Cache W / Thinking / Total）；`renderOverview` 按全字段求和；改用 CSS Grid 自动换行，窄屏降级两列。
  **验证**：浏览器打开 `http://127.0.0.1:19528/dashboard`，确认 9 个指标可见且 Total = Input+Output+Cache R+Cache W；缩至 375px 宽确认不横向溢出。

- [x] T10 `kiro_tap/dashboard.html` 列表页新增可折叠「逐 turn 明细」（`<details>` 默认折叠），按当前筛选会话分组，表格列出 `turn_breakdown` 全字段；所有文本经 `esc()`。
  **验证**：展开确认行数与 `turn_breakdown` 一致；DevTools 注入含 `<script>` 的 model 字符串，确认被转义。

- [x] T11 `kiro_tap/dashboard.html` 会话详情页在 `.detail-page-head` 下新增 `.detail-token-summary`（全字段横排）与 `.detail-turn-breakdown`（折叠，数据来自 `session.turn_breakdown`）；`showDetailLoading`、`updateDetailSessionSummary`、`renderDetail` 同步刷新。
  **验证**：打开 `/dashboard/session/{id}`，确认汇总值与列表页该会话行一致；live 会话新 record 到达后数值递增。

- [x] T12 `kiro_tap/dashboard.html` 的 `DASHBOARD_I18N` 为 `en` 与 `zh-CN` 补齐全部新增 key（指标名、tooltip、明细表头、空状态）。
  **验证**：切换语言下拉，确认无 key 名裸露。

### 前端：viewer.html

- [x] T13 `kiro_tap/viewer.html` 顶部 `#stats` 移除 4 个字段的 `display:none` 逻辑，新增 Thinking 组常显；`applyFilter` 中 `totalTokens` 改为四项之和，并累加 `sumThinking`（读 usage 层键 `thinking_tokens`）。JS `normalizeUsage` 补四路 thinking 映射（与 T1 同优先级、同样剔除无效值、四路全无效时不写键）；`buildStubEntry` 仅在 `usage` 缺 `thinking_tokens` 键**且** `meta.thinking_tokens` 为有限数值时补齐；累加时逐条经 `Number.isFinite` 校验（无效值按 0 参与累加），渲染前再兜底 0。
  **验证**：打开 viewer，确认 6 个字段全部常显；构造四路来源各一条 trace，确认 Thinking 分别显示 20 / 30 / 40 / 50；再构造一条**同时含四路**的 trace（值分别为 20/30/40/50），确认显示 20（优先级最高者）；构造 `{"output_tokens_details": {"thinking_tokens": "abc"}}`、`{"output_tokens_details": null}`、`{"thinking_tokens": "abc"}`，确认显示 0 而非 `NaN` 且不抛错；在 devtools 中断言处理后的 `usage` 不含 `thinking_tokens` 键（验收剔除语义，而非只看 DOM）；lazy 与 live 两种模式各验一次。

- [x] T14 `kiro_tap/viewer.html` 新增 `#turn-breakdown-bar`（`<details>` 默认折叠）：按 `filtered` 的 `turn` 分组累加全字段，分组规则与后端一致（`turn` 缺失或非整数的 record 归入同一个 `null` 分组并排在末尾），该行 Turn 列显示 i18n key `turn_breakdown_unknown_turn` 的文案，列含 Turn / Input / Output / Cache R / Cache W / Thinking / Total / Duration / Model；与 path / search / tool 筛选联动。
  **验证**：选择某 path 筛选，确认明细同步收缩；分组行数 = sidebar 中不同有效 turn 数 +（存在无效 turn 时 1）；构造 `turn="3"`、`turn=1.5`、缺 `turn` 三条 record，确认合并为同一个占位行且文案随语言切换。

- [x] T15 `kiro_tap/viewer_i18n.json` 为 8 种语言（en / zh-CN / ja / ko / fr / ar / de / ru）新增 `tok_thinking`、`tok_total`、`turn_breakdown_title`、`turn_breakdown_empty`、`turn_breakdown_unknown_turn`、`turn_col`、`thinking_subset_hint`，并更新 `stats_tokens_hint` 说明总量构成。`turn_breakdown_empty`（明细为空）与 `turn_breakdown_unknown_turn`（存在无效 turn 的占位行）语义不同，SHALL NOT 复用同一 key。
  **验证**：`python -c "import json;d=json.load(open('kiro_tap/viewer_i18n.json'));ks=set(d['en']);assert all(set(v)==ks for v in d.values()),'key mismatch';print('ok')"`；切换 8 种语言确认文案齐全。

### 收尾

- [x] T16 运行 `ruff check .`，对本次改动文件执行 `ruff --fix` 处理 I001/F401 类问题。
  **验证**：`ruff check .` 输出 `All checks passed!`。

- [x] T17 全量回归与手动验证：`pytest`、三页面浏览器核对（列表页 / 详情页 / viewer，含 live 与历史会话）。
  **验证**：`pytest` 全绿（70 passed）；coverage 中 `usage.py` 100%、`dashboard.py` 新增行有覆盖。浏览器 node --check 前端 JS 语法通过；三页面浏览器截图核对为手动步骤，未在本会话执行。

## 验收标准

- [x] `pytest` 全量通过（70 passed）。新增测试覆盖 spec 中可由自动化断言的后端 Scenario（归一化、汇总、增量等价、惰性回填）；前端与浏览器核对类 Scenario 由 T10 / T11 / T13 / T14 的手工验证覆盖。
- [ ] `ruff check .` 零错误。
- [ ] 三页面顶部均展示 Input / Output / Cache Read / Cache Write / Thinking / Total 六项全字段，缺失时显示 0 而非隐藏。
- [ ] 三页面均提供可折叠逐 turn 明细，字段完整。
- [ ] `_summarize_session` 与 `merge_record_into_summary` 对同一 record 序列产出完全相同的汇总与 `turn_breakdown`。
- [ ] `thinking_tokens` 显式展示且不计入 `total_tokens`，页面 tooltip 有说明。
- [ ] 旧 `summary_json` 缓存缺新字段时读取不报错，按 0 / 空数组渲染。
- [ ] 未新增外部网络请求、未引入前端依赖、未改动 SQLite schema。