# 变更提案：add-turn-token-statistics

## 背景

当前 kiro-tap 三个页面（dashboard 列表页、dashboard 会话详情页、viewer 详情页）的 token 统计口径不一致且字段不全：

- `viewer.html:#stats` 的 `totalTokens` 只累加 `input_tokens + output_tokens`，而 `dashboard.py` 的 `total_tokens` 是 `input + output + cache_read + cache_creation` 四项之和，同一会话在两个页面显示不同数值。
- `viewer.html` 对 `In/Out/Cache R/Cache W` 四项做「值为 0 则隐藏」处理，用户无法判断某字段是缺失还是确实为 0。
- 本地 SQLite 实测（83 sessions / 264 records）显示 usage 形态多样，已存在 `output_tokens_details.thinking_tokens`、`claude_cache_creation_5m/1h_tokens`、`contextUsagePercentage` 等字段，但 `usage.py:normalize_usage` 只映射 4 个字段，`thinking_tokens` 完全丢失。
- `dashboard.html` 列表页仅有一个 `Total Tokens` 指标，会话详情页头部完全没有 token 统计。
- 三个页面都没有「按 turn 分组」的 token 明细，用户无法定位某一轮对话的消耗。

## 目标范围

**在范围内：**

- `kiro_tap/usage.py:normalize_usage` 增加 `thinking_tokens` 归一化（来源 `output_tokens_details.thinking_tokens` / `completion_tokens_details.reasoning_tokens`）。
- `kiro_tap/dashboard.py` 会话汇总新增 `thinking_tokens` 累计字段，并新增 `turn_breakdown` 数组（每个 turn 一条：`turn`、`input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_create_tokens`、`thinking_tokens`、`total_tokens`、`record_count`、`duration_ms`、`model`）。`_summarize_session` 与 `merge_record_into_summary` 两条路径必须产出一致结果。
- `kiro_tap/viewer.py` 的 stub meta（lazy 模式）新增 `thinking_tokens`，使懒加载模式下前端统计不缺失。
- `kiro_tap/viewer.html` 顶部 `#stats` 扩展为全字段常显（In / Out / Cache R / Cache W / Thinking / Total / Turns / Time），并新增可折叠的逐 turn 明细面板。
- `kiro_tap/dashboard.html` 列表页概览卡扩展为全字段汇总指标，并新增可折叠的逐 turn 明细区域（按当前筛选的会话分组）。
- `kiro_tap/dashboard.html` 会话详情页头部新增全字段 token 统计条 + 可折叠逐 turn 明细，数据来自后端 `turn_breakdown`。
- `kiro_tap/viewer_i18n.json` 为 8 种语言新增全部新文案 key。
- 新增 `tests/test_usage_normalize.py`、`tests/test_dashboard_tokens.py`。

**不在范围内：**

- 不改 SQLite schema（`summary_json` 是 JSON blob，新增字段无需 `PRAGMA user_version` 变更）。
- 不改 `TraceWriter.get_summary` 与 CLI 终端汇总输出。
- 不引入 `contextUsagePercentage` 百分比、缓存命中率等派生指标，不拆分 `claude_cache_creation_5m/1h_tokens`。
- 不引入 `billing_usage` 嵌套结构解析。
- 不引入前端构建工具，不新增依赖。

## 技术方案

1. **统一字段口径（5 项输入 + 1 项派生）**：`input_tokens`、`output_tokens`、`cache_read_input_tokens`、`cache_creation_input_tokens`、`thinking_tokens`，`total_tokens = input + output + cache_read + cache_create`。
   **`thinking_tokens` 不计入 `total_tokens`**：Anthropic 的 thinking 已包含在 `output_tokens` 内，OpenAI 的 `reasoning_tokens` 同理，重复相加会虚增总量。该语义需在前端 tooltip 与 design.md 中显式标注为 subset。

   **字段命名分层映射表（四层，实现必须按此映射）：**

   | 层 | 读取来源 | cache read 键 | cache create 键 | thinking 键 |
   |---|---|---|---|---|
   | usage 归一化输出（`usage.py`） | 原始 record | `cache_read_input_tokens` | `cache_creation_input_tokens` | `thinking_tokens` |
   | summary / turn_breakdown（`dashboard.py`） | `summary_json` | `cache_read_tokens` | `cache_create_tokens` | `thinking_tokens` |
   | `dashboard.html` 前端 | `/api/sessions` 的 session 对象 | `cache_read_tokens` | `cache_create_tokens` | `thinking_tokens` |
   | `viewer.html` 前端 | 原始 record 的 `response.body.usage` | `cache_read_input_tokens` | `cache_creation_input_tokens` | `thinking_tokens` |

   （四个层的 `input_tokens` / `output_tokens` / `total_tokens` 命名一致，不单列。）

   `cache_creation_input_tokens` 无 provider 别名，仅为源 usage 同名字段直通；其余四项均有别名回退（见 spec）。
   summary 层保留既有 `cache_read_tokens` / `cache_create_tokens` 命名，**不重命名**；`viewer.html` 保留既有 usage 层读取，**不改键名**。两层之间由 `_turn_stats` 完成改名，前端各自读取本层已有键。
2. **`total_tokens` 口径统一**：`viewer.html:applyFilter` 中的 `totalTokens` 从 `in+out` 改为四项之和，与 `dashboard.py` 对齐。这是对既有数值不一致的修复，会改变 viewer 顶部 `Tokens` 显示值。
3. **`turn_breakdown` 作为会话汇总的一部分返回**：dashboard 详情页只加载前 10 条 record（`MAX_INLINE_DETAIL_RECORDS`），无法从 records 完整重算 turn 明细，因此由后端在 `_summarize_session` / `merge_record_into_summary` 中维护。`turn_count` 定义为 `len(turn_breakdown) if turn_breakdown else record_count`。

   **必须移除既有三处 `max(turn_count, record_count)` 覆盖**（`dashboard.py:147` 增量路径、`:218` 活缓存路径、`:277` 当前会话路径）。这三处会让「同一 turn 含 2 条 record」的会话在增量路径得 2、全量路径得 1，直接违反「两条路径等价」要求。
4. **增量路径一致性**：`merge_record_into_summary` 是**写时合并**——由 `trace_store.append_record` 在 `_write_lock` 临界区内经 `_refresh_summary_after_append` 调用，每写入一条 record 就更新 `turn_breakdown` 中对应 turn 的条目（不存在则插入并按 turn 排序，`null` turn 置末尾）。该路径与 `_summarize_session` 的读时全量汇总共享同一 `_turn_stats(record)` 提取函数。

   **逐 turn 聚合规则（两条路径共用）：**
   - `turn` 取自 record 顶层 `turn` 字段；缺失或非整数归为 `null`，全部合并进**同一个** `null` 条目并排在数组末尾。
   - `duration_ms`：同 turn 内各 record 的 `duration_ms` **求和**；缺失或非整数按 0 计。
   - `model`：同 turn 内取**最后一条非空** `_record_model(record)`，与 summary 既有 `model` 覆盖语义一致。
   - `record_count`：计入该 turn 的全部 record，含无 usage 的 record。
   - 无 usage 或 usage 缺失的 record：token 字段贡献 0，仍计入 `record_count`。
   - `total_tokens`（条目内）= 四项之和，不含 thinking。
5. **历史会话惰性回填**：现库 82/83 会话已有 `summary_json` 且**全部不含** `turn_breakdown`。`_session_summary_from_row` 在读取缓存摘要时检测 `turn_breakdown` 缺失且 `record_count > 0`，则从 records 全量重算一次并 `store_summary` 回写。这是唯一能让历史会话获得逐 turn 明细的路径——`migrate_legacy_directory` 只导入外部 JSONL，不会重算已入库会话。
6. **token 字段类型兜底**：`_turn_stats` 对 5 个 token 字段与 `duration_ms` 统一做「非整数按 0」处理（`isinstance(v, int) and not isinstance(v, bool)`），避免源 usage 出现字符串/浮点时 `+=` 抛 `TypeError`。
7. **前端纯内联实现**：沿用 config 约束，dashboard.html / viewer.html 内联 HTML/CSS/JS，无构建工具；dashboard i18n 补 `en` / `zh-CN` 两份，viewer i18n 补 8 份。**viewer 的 JS 侧 `normalizeUsage`（`viewer.html:4623`）必须补 thinking 映射，`buildStubEntry` 必须透传 `meta.thinking_tokens`**，否则前端 Thinking 恒为 0。

## 预期影响

- 所有页面顶部 token 统计数值可能变化：viewer 的 `Tokens` 从 in+out 变为四项之和，数值变大但与此前后端一致。
- `summary_json` 内容增加 `thinking_tokens` 与 `turn_breakdown`。历史会话（82 个）通过读取时惰性回填获得明细，回填为一次性开销（每会话一次全量 records 扫描 + 一次写回）。
- 既有测试 `tests/test_aws_event_stream.py` 不受影响（它断言 `_metering` 原始字段）。
- 性能：`turn_breakdown` 长度等于会话 turn 数，单会话内可忽略；`_summarize_session` 已在遍历 records，分组为同一次遍历的增量开销。

## 风险

| 风险 | 应对 |
|------|------|
| `total_tokens` 口径变更导致用户对比历史截图时产生困惑 | 在 design.md 记录旧/新口径，页面 tooltip 说明总量构成 |
| `thinking_tokens` 被误认为应计入 total | 代码注释 + i18n tooltip 标注为 output 子集；测试断言 total 不含 thinking |
| dashboard 列表页展开 turn 明细后 DOM 节点过多 | 默认折叠；展开时受当前筛选约束；单会话最多 record 数级别 |
| 活动会话增量路径与全量路径产出不一致 | 单测同时覆盖 `_summarize_session` 与 `merge_record_into_summary`，断言两条路径结果等价 |
| 8 语言 i18n 遗漏 key | 任务中单列 i18n 补齐项，缺失时 `t()` 回退 key 名可见 |
| 现有 `max(turn_count, record_count)` 覆盖逻辑未移除导致两路径不等价 | 删除 `dashboard.py:147/218/277` 三处 `max`；并明确 `:348` 的 `count` 在 `turns` 为空时的取值；测试覆盖「同 turn 多 record 且 record_count > 条目数」 |
| 历史 82 个会话无 `turn_breakdown` | `_session_summary_from_row` 惰性回填 + 回写；测试断言首次读取后缓存含明细、第二次读取不重复回写（幂等） |
| viewer 的 JS `normalizeUsage`（`viewer.html:4623`）未映射 thinking 导致前端恒 0 | 同时修 `normalizeUsage` 与 `buildStubEntry`（`:2057-2061`）透传 `meta.thinking_tokens` |
| token 值类型异常：`str` / `None` 触发 `TypeError`，浮点导致截断或非整数 | `_as_int(value)` 兜底（`int(float(value))` + 捕获 `TypeError`/`ValueError`/`OverflowError` 归 0 并记录一次 warning）；测试覆盖 `"100"`、`"1.5"`、`5.5`、`None`、缺失键五类输入 |