## 上下文

`kiro-tap` 是 Python CLI + 本地 HTTP 服务，trace 记录写入 SQLite（`trace_store.py`），会话汇总缓存在 `sessions.summary_json`（JSON blob，非结构化列）。前端为三处纯内联 HTML：

- `dashboard.html`：列表页（`/dashboard`）与会话详情页（`/dashboard/session/{id}`），数据来自 `/api/sessions` 与 `/api/sessions/{id}/records`。
- `viewer.html`：独立的 trace 查看器，可用于 live 模式、嵌入式 JSONL、懒加载 stub 三种数据源，顶部 `#stats` 为现有统计条。

现有统计实现分散在 4 处，口径不一：

| 位置 | 字段 | 问题 |
|------|------|------|
| `usage.py:normalize_usage` | in/out/cache_read | 无 thinking |
| `trace.py:TraceWriter` | in/out/cache_read/cache_create | 仅 CLI 摘要使用 |
| `dashboard.py:_summarize_session` | in/out/cache_read/cache_create | 无 thinking，无逐 turn |
| `viewer.html:applyFilter` | in/out（total 只算这两项） | 与后端口径不一致 |

本地 SQLite 实测 usage 形态（264 records 样本）：

```
(input_tokens, output_tokens)                                      17
(cache_creation_input_tokens, cache_read_input_tokens, in, out)    20
(..., output_tokens_details)                                        9+12+24
(..., output_tokens_details, service_tier)                          24
(..., claude_cache_creation_1_h_tokens, claude_cache_creation_5_m_tokens, billing_usage) 29
(..., contextUsagePercentage)                                       26+1
```

即 `output_tokens_details.thinking_tokens` 是真实存在但当前完全丢失的字段。

## 目标 / 非目标

**目标：**

1. 三个页面顶部统一展示同一套全字段 token 统计，口径一致。
2. 每个页面顶部都能按 turn 展开明细。
3. 字段缺失时显示 0 而非隐藏，避免「看不见 = 不知道」。
4. 后端两条汇总路径（全量 / 增量）产出一致结构，避免活动会话与历史会话显示不同。

**非目标：**

1. 不解析 `billing_usage` 嵌套结构、`claude_cache_creation_5m/1h_tokens` 细分、`contextUsagePercentage`。
2. 不改 SQLite schema、不加列、不做数据迁移。
3. 不改 CLI 终端输出（`cli.py` 的 `📊 Trace summary`）。
4. 不引入前端框架或构建工具。
5. 不新增 HTTP 路由（复用 `/api/sessions` 与 `/api/sessions/{id}/records`）。

## 决策

### 决策 1：`thinking_tokens` 作为独立字段，不计入 `total_tokens`

**背景**：Anthropic `output_tokens` 已包含 thinking 部分；OpenAI `completion_tokens` 同样包含 `reasoning_tokens`。若把 thinking 再加进 total，总量会虚增。

**例外**：Gemini 的 `thoughtsTokenCount` 与 `candidatesTokenCount` 是兄弟字段，前者**不**包含在后者内；Gemini 上游 `totalTokenCount` 含 thoughts。本地 `total_tokens` 统一不含 thinking，故 Gemini 会话的本地总量会小于上游 `totalTokenCount`，由 tooltip 说明。

**决策**：`thinking_tokens` 单独展示，`total_tokens = input + output + cache_read + cache_create`。

**代价**：用户可能误以为 total 应包含 thinking。**缓解**：页面 tooltip 按 provider 区分——Anthropic / OpenAI 标注「Thinking / Reasoning 已包含在 Output 内，不重复计入 Total」；Gemini 标注「Thoughts 不计入 Candidates（Output），单独展示」；未识别 provider 不断言包含关系。

### 决策 2：`turn_breakdown` 由后端生成并随会话摘要返回

**备选 A（未采纳）**：前端从 records 计算。**否决原因**：dashboard 详情页默认只加载前 10 条 record（`MAX_INLINE_DETAIL_RECORDS = 10`），无法覆盖完整会话；viewer 的 lazy 模式下只有 stub meta。

**备选 B（未采纳）**：新增独立 API `/api/sessions/{id}/turns`。**否决原因**：多一次往返、多一处并发一致性维护点；`turn_breakdown` 与汇总同源同锁生成，绑定返回更简单。

**决策**：`turn_breakdown` 作为 `session` 对象的一部分返回。列表页的 `/api/sessions` 也会带上每个会话的 `turn_breakdown`，但用于按会话分组展开。

**代价**：`/api/sessions` 响应体增大（每会话约 turn 数 × 10 字段）。**缓解**：`turn_breakdown` 条目字段紧凑、全部为整数，单会话通常 < 100 turn；列表页默认折叠，不渲染 DOM。

### 决策 3：增量路径与全量路径共用同一「单 record 提取」函数

`_summarize_session` 与 `merge_record_into_summary` 都调用新增助手 `_turn_stats(record)`，返回该 record 的 `turn`（顶层字段，缺失或非整数归 `None`）、5 个 token 字段（已从归一化层名映射到 summary 层名）、`duration_ms`、`model`。两条路径只在「如何累加」上不同，字段提取完全共享，消除口径漂移。

累加顺序固定：`turn_breakdown` 按 `turn` 升序，`None` 条目置末尾。同一 turn 的 record 累加到同一条目，聚合规则为：

- 5 个 token 字段按 record **求和**，单条 record 缺失字段按 0 计入
- `duration_ms` 求和（缺失按 0）
- `model` 取**最后一条非空**；全部为空时取 `null`
- `record_count` 计入含无 usage 的全部 record
- 条目 `total_tokens` 为四项之和，不含 thinking
- `turn` 为字符串、浮点等非整数形态时统一归 `None`，不抛异常

**字段名分层说明（关键，易踩坑）：** 归一化层与 summary 层命名**不同**（`cache_read_input_tokens` → `cache_read_tokens`、`cache_creation_input_tokens` → `cache_create_tokens`），这是既有代码事实。`_turn_stats` 负责完成这次改名，调用方只读 summary 层名。summary 层命名**不得重命名**（否则破坏已缓存 `summary_json` 与 `dashboard.html:1381-1385` 的读取点）；`viewer.html` 直接读原始 record 的 usage 层键，同样**不得改键名**（`viewer.html:2761-2765`、`3557`）。

**写时 vs 读时：** `merge_record_into_summary` 是写时合并，在 `trace_store.append_record` 的 `_write_lock` 临界区内经 `_refresh_summary_after_append` 执行；`_summarize_session` 是读时全量汇总。两者必须产出完全相同的 token 数值与 `turn_breakdown` 结构。

### 决策 4：`viewer.html` 的 total 口径对齐后端

`applyFilter` 中 `totalTokens` 由 `in+out` 改为 `in+out+cache_read+cache_create`。这是行为变更，会导致 viewer 顶部 `Tokens` 数值变大。**该字段同时是 `#stat-tokens`（原有）与新 Total 指标的唯一来源，不保留双份。**

### 决策 5：顶部布局

**viewer.html**：沿用现有 `#stats` 横向布局，移除 4 个字段的 `display:none` 逻辑，新增 Thinking 组；在 `#stats` 下方插入 `<div id="turn-breakdown-bar">`，默认折叠（`<details>`），展开后为紧凑表格。

**dashboard.html 列表页**：`.overview-card` 由 4 个 metric 扩展为 9 个（Threads / Traces / Error Rate / Input / Output / Cache R / Cache W / Thinking / Total）。使用 CSS Grid 自动换行，窄屏降级为两列。

**dashboard.html 详情页**：在 `.detail-page-head` 下方、`.detail` 上方插入 `.detail-token-summary`（全字段横排）+ `.detail-turn-breakdown`（`<details>`）。

### 决策 6：i18n

- `dashboard.html` 内联 `DASHBOARD_I18N`，仅 `en` / `zh-CN` 两种语言，补齐两份。
- `viewer.html` 从 `viewer_i18n.json` 注入，8 种语言（en / zh-CN / ja / ko / fr / ar / de / ru），全部补齐。缺失 key 时 `t()` 回退 key 名，属可见降级，不抛错。

### 决策 7：thinking 来源覆盖四路 provider 形态

仓库当前对 thinking 完全未处理（`output_tokens_details` / `reasoning_tokens` / `thoughtsTokenCount` 在 `kiro_tap/*.py` 与 `kiro_tap/*.html` 中零命中）。四路来源与语义：

| 来源字段 | provider | thinking 是否已含于 output | 现状 |
|---|---|---|---|
| `output_tokens_details.thinking_tokens` | Anthropic | 是 | 未处理 |
| `output_tokens_details.reasoning_tokens` | OpenAI Responses | 是 | 未处理 |
| `completion_tokens_details.reasoning_tokens` | OpenAI Chat | 是 | 未处理 |
| `thoughtsTokenCount`（`usageMetadata` 展开后） | Gemini | 否（与 `candidatesTokenCount` 平级） | 未处理 |

**决策**：`normalize_usage` 与 viewer.html 的 JS `normalizeUsage` 按上述顺序取第一个「存在且为有限数值」者，写入 `thinking_tokens`。四路均缺失或均无效时**两侧一致**地不写入该键（JS 侧也不以 `0` 占位）；容器为 `null` 或非 dict 时跳过该路，不抛异常。源直通的无效 `thinking_tokens` 值同样剔除，不得留存；`buildStubEntry` 不得用 meta 中的无效值把已剔除的键补回。展示层的「缺失显示 0」在渲染与累加两处分别兜底，不影响 normalized 层的键集合。

**注意**：`usageMetadata` 已由各调用方展开后再传入归一化层（`dashboard.py:_record_usage`、`viewer.py:_extract_gemini_response_usage` 属 Python 调用链；`viewer.html:geminiUsageFromPayloads` 属 JS 侧同名归一化实现），两侧实现均 SHALL NOT 再次查找 `usageMetadata` 键。

## 风险 / 权衡

| 风险 | 影响 | 缓解 |
|------|------|------|
| `total_tokens` 口径变化导致历史数值对比困惑 | 用户看到数值变大 | tooltip 说明「总量 = Input + Output + Cache Read + Cache Write」 |
| `turn_breakdown` 让 `/api/sessions` 响应变大 | 列表页加载变慢 | 条目字段紧凑；会话数通常 < 100；实测 83 sessions 时增量可忽略 |
| 增量路径遗漏 turn 更新导致详情页与列表页不一致 | 数据错乱 | 单测断言两路径等价（spec 中已列为 Scenario） |
| 旧 `summary_json` 缓存无新字段 | 前端显示 undefined | 前端统一 `|| 0` 兜底；`_session_summary_from_row` 对 active 会话重建 |
| viewer 的 lazy stub 模式数据源受限 | 懒加载下 thinking 全为 0 | `viewer.py` 的 stub meta 增加 `thinking_tokens`；lazy 模式本就只有 meta 级别的字段，属预期限制 |
| 8 语言 i18n 手写易错 | 部分语言显示 key 名 | 任务单列；导入 JSON 后可用 `python -c "import json;json.load(...)"` 校验 |
| Gemini `thoughtsTokenCount` 与 Anthropic/OpenAI 语义相反 | 若沿用「thinking 已含于 output」假设，Gemini 会话 thinking 恒为 0 或总量虚减 | 四路映射 + 按 provider 分化 tooltip；spec 已列独立 Scenario |
| viewer JS 渲染非有限数值 | 顶部统计显示 `NaN` / `undefined`，整条统计不可读 | 渲染前经 `Number.isFinite` 兜底 0；异常容器跳过不抛错 |
| Gemini 本地 `total_tokens` 小于上游 `totalTokenCount` | 用户对比控制台数字时困惑 | tooltip 明确「本地 Total 不含 Thoughts」 |
| `input_tokens` / `output_tokens` 的存在判定由 `in` 改为「非 `null`」 | 源 usage 同时含 `null` 目标键与非零别名时，用户可见值由 0 变为别名值 | 属修正：`null` 本应视为未上报。仅在别名非 0 时可见值变化，变更说明需标注；别名缺失或为 0 时可见值不变 |

## 迁移方案

无 schema 迁移。旧 `summary_json` 缺字段时：

1. `_session_summary_from_row` 对 `status != 'active'` 的会话直接返回缓存 → 缓存缺 `thinking_tokens` / `turn_breakdown` 时，在返回前补默认值（`0` / `[]`），不重算。
2. 对 `status == 'active'` 的会话，现有逻辑已会叠加 `record_count`；新增字段同样按「缺失补默认」处理。
3. 用户如需精确历史数据，可通过重新导入 JSONL（`migrate_legacy_directory`）触发全量重算，但非必需。

## 待决问题

无。所有影响 spec / 任务拆分的歧义已在阶段 0 通过 AskUserQuestion 澄清（页面范围、展示粒度、字段范围）。