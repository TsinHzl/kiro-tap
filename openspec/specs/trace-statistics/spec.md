## Purpose

定义 kiro-tap 各展示页面顶部 token 统计的字段口径、汇总规则与逐 turn 明细结构，确保 dashboard 列表页、会话详情页与 viewer 详情页对同一份 trace 数据展示一致的 token 数值。

## ADDED Requirements

### Requirement: Token 字段统一归一化

系统 SHALL 在 `kiro_tap/usage.py:normalize_usage` 中将各 provider 的 usage 形态归一化为统一字段集：`input_tokens`、`output_tokens`、`cache_read_input_tokens`、`cache_creation_input_tokens`、`thinking_tokens`。

字段映射规则：

- `input_tokens` ← 按优先级取第一个存在者：`input_tokens` / `prompt_tokens` / `promptTokenCount`
- `output_tokens` ← 按优先级取第一个存在者：`output_tokens` / `completion_tokens` / `candidatesTokenCount`
- `cache_read_input_tokens` ← 按优先级取第一个存在者：`cached_tokens` / `cachedContentTokenCount` / `input_tokens_details.cached_tokens` / `prompt_tokens_details.cached_tokens`
- `cache_creation_input_tokens` ← 源 usage 同名字段直通（**无 provider 别名**）
- `thinking_tokens` ← 按优先级取第一个存在者：`output_tokens_details.thinking_tokens`（Anthropic）→ `output_tokens_details.reasoning_tokens`（OpenAI Responses）→ `completion_tokens_details.reasoning_tokens`（OpenAI Chat）→ `thoughtsTokenCount`（Gemini）；四路全部缺失时不写入该键

上述所有别名均按「第一个存在者」取值。

「存在」的定义：键存在且值不为 `null`。`0` 视为存在；`null` 视为缺失并继续尝试下一别名。该口径适用于全部五个字段的别名选择与目标键判定。

`thinking_tokens` 另加数值约束：「存在」还要求值为有限数值（int / float，不含 `NaN` / `Infinity`、布尔、字符串、容器类型）。不满足时视为缺失并继续尝试后续别名。

别名优先级仅在目标键不存在时生效；目标键存在且为有效值时以原值为准，SHALL NOT 被别名结果覆盖或删除。

规则中的点号表示嵌套字典逐级取值（如 `usage["input_tokens_details"]["cached_tokens"]`），**并非字面键名**。嵌套层为 `null` 或非 dict 时，该路视为缺失且不抛异常。

顶层 `usage` SHALL 为 dict；为 `None`、字符串、列表或其他非 dict 时，`normalize_usage` SHALL 返回空字典 `{}`，不抛异常（既有 `isinstance` 守卫）。

Gemini 的 `usageMetadata` 由调用方先行展开：所有调用方在调用 `normalize_usage` 前 SHALL 将 `usageMetadata` 的内容作为 usage 字典传入；`normalize_usage` 内 SHALL NOT 再次查找 `usageMetadata` 键。该条仅约束剥离 Gemini 外层，其他 provider 的嵌套明细（如 `input_tokens_details`）仍按点号路径逐级取值，SHALL NOT 被扁平化。

当源 usage 缺少某字段时，归一化结果中该字段 SHALL 缺失（而非写入 0），以便调用方区分「未上报」与「确认为 0」。`normalize_usage` SHALL 保留源 usage 中未被映射的键（既有 `dict(usage)` 行为），SHALL NOT 只保留字段映射表中列出的键。

已映射字段（`thinking_tokens` 除外，见下条）在源中值为 `null` 且无有效别名命中时，结果 SHALL 保留该键的 `null` 值（`dict(usage)` 拷贝语义），调用方按缺失处理；`cache_creation_input_tokens` 直通同样适用。

`thinking_tokens` 的最终结果 SHALL NOT 为无效值：源直接同名字段或四路别名任一取得的值若为 `null`、`NaN` / `Infinity`、布尔、字符串或容器类型，一律视为无效并继续尝试后续别名；四路全部无效时，结果 SHALL NOT 包含 `thinking_tokens` 键。该省略优先于「目标键已存在时以原值为准」——即源直通的无效 `thinking_tokens` 值 SHALL 被移除，不得因原值保留规则而留存。

归一化层到 summary 层的字段映射 SHALL 为：

| 归一化输出 | summary / turn_breakdown |
|---|---|
| `input_tokens` | `input_tokens` |
| `output_tokens` | `output_tokens` |
| `cache_read_input_tokens` | `cache_read_tokens` |
| `cache_creation_input_tokens` | `cache_create_tokens` |
| `thinking_tokens` | `thinking_tokens` |

#### Scenario: Anthropic 形态含 thinking 明细
- **GIVEN** usage 为 `{"input_tokens": 100, "output_tokens": 50, "output_tokens_details": {"thinking_tokens": 20}}`
- **WHEN** 调用 `normalize_usage`
- **THEN** 返回 `{"input_tokens": 100, "output_tokens": 50, "thinking_tokens": 20}`
- **AND** 返回值不新增 `cache_read_input_tokens` / `cache_creation_input_tokens` 键

#### Scenario: OpenAI Chat 形态含 reasoning 明细
- **GIVEN** usage 为 `{"prompt_tokens": 30, "completion_tokens": 12, "completion_tokens_details": {"reasoning_tokens": 4}}`
- **WHEN** 调用 `normalize_usage`
- **THEN** 返回 `input_tokens=30`、`output_tokens=12`、`thinking_tokens=4`

#### Scenario: OpenAI Responses 形态含 reasoning 明细
- **GIVEN** usage 为 `{"input_tokens": 30, "output_tokens": 12, "output_tokens_details": {"reasoning_tokens": 3}}`
- **WHEN** 调用 `normalize_usage`
- **THEN** 返回 `input_tokens=30`、`output_tokens=12`、`thinking_tokens=3`

#### Scenario: 多路 thinking 来源同时存在时取优先级最高者
- **GIVEN** usage 为 `{"output_tokens_details": {"thinking_tokens": 7, "reasoning_tokens": 9}, "thoughtsTokenCount": 11}`
- **WHEN** 调用 `normalize_usage`
- **THEN** 返回 `thinking_tokens=7`（Anthropic 分支优先，其余两路不再取值）

#### Scenario: 非字典输入
- **GIVEN** usage 为 `None`、字符串或列表
- **WHEN** 调用 `normalize_usage`
- **THEN** 返回空字典 `{}`

#### Scenario: thinking 容器为空或非字典
- **GIVEN** usage 为 `{"input_tokens": 10, "output_tokens": 5, "output_tokens_details": null, "completion_tokens_details": "x", "usageMetadata": null}` 或 `{"output_tokens_details": "x"}`
- **WHEN** 调用 `normalize_usage`
- **THEN** 不抛异常，返回结果不含 `thinking_tokens` 键
- **AND** 其余可解析字段（`input_tokens=10`、`output_tokens=5`）正常返回

### Requirement: 会话汇总包含全字段与逐 turn 明细

系统 SHALL 在 `kiro_tap/dashboard.py:_summarize_session` 与 `kiro_tap/dashboard.py:merge_record_into_summary` 两条汇总路径中，为每个会话产出下列字段：

- 汇总字段：`input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_create_tokens`、`thinking_tokens`、`total_tokens`、`record_count`、`turn_count`、`duration_ms`
- 逐 turn 字段：`turn_breakdown`，为数组，每个元素包含 `turn`、`input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_create_tokens`、`thinking_tokens`、`total_tokens`、`record_count`、`duration_ms`、`model`

`total_tokens` SHALL 等于 `input_tokens + output_tokens + cache_read_tokens + cache_create_tokens`，**不包含** `thinking_tokens`。

`turn_breakdown` SHALL 按 `turn` 升序排列；`turn` 非整数的 record 归入 `turn_breakdown` 中 `turn` 为 `null` 的单一条目。`turn` 为 `null` 的条目 SHALL 位于数组**末尾**（不含 `null` 条目时无影响）。

`turn` SHALL 取自 record 顶层 `turn` 字段（`proxy.py:_build_record` 写入的整数计数器值）。`turn` 字段缺失或非整数时 SHALL 归为 `null`，且**所有此类 record 合并为同一个 `null` 条目**，SHALL NOT 逐条生成多个 `null` 条目。

条目聚合规则：

- `duration_ms` SHALL 为该 turn 内各 record `duration_ms` 之和；record 缺失或非整数 `duration_ms` 时 SHALL 按 0 计入（不抛异常、不跳过该 record）。
- `model` SHALL 为该 turn 内**最后一条非空**模型标识，与 summary 既有 `model` 覆盖语义一致。
- `record_count` SHALL 计入该 turn 的全部 record，包括无 usage 的 record。
- 条目 `total_tokens` SHALL 为四项之和，不含 `thinking_tokens`。
- 5 个 token 字段 SHALL 按 record **求和**；单条 record 缺失某字段时 SHALL 按 0 计入。
- 5 个 token 字段 SHALL 经 `_as_int` 兜底后再累加：`int` 直接采用；`bool` 按 0；其余（`str`、`None`、`float`、缺失）按 0 计，且不抛 `TypeError` / `ValueError`。
- `duration_ms` 生产端已由 `int(monotonic 差值 * 1000)` 保证为 `int`（`proxy.py:337/381`、`ws_proxy.py:124/286`、`forward_proxy.py:447/555/598/694/832`）；汇总时非 `int` 按 0 计。
- 条目 `model` 在全部 record 均无非空 model 时 SHALL 为 `null`。

`turn_count` SHALL 等于 `len(turn_breakdown)`（含 `null` 条目）；当 `turn_breakdown` 为空时 SHALL 回退为 `record_count`。

系统 SHALL NOT 使用 `max(turn_count, record_count)` 覆盖该值。既有三处覆盖位于 `dashboard.py` 的增量合并（`merge_record_into_summary`）、活动会话缓存修正（`_session_summary_from_row`）、当前会话状态修正（`_apply_current_session_state`）中，MUST 全部移除。

**惰性回填约束：**
- `_session_summary_from_row` 判定「已回填」SHALL 以**键是否存在**为准（`"turn_breakdown" in summary`），SHALL NOT 以值为假判断（空列表 `[]` 视为已回填）。
- 回写 SHALL 采用条件更新语义：仅当磁盘摘要仍缺 `turn_breakdown` 键时写入。同一会话的第二次读取 SHALL NOT 再次触发 records 扫描或 `store_summary`。
- 惰性回填 SHALL 仅发生在**单会话详情读取路径**（`load_trace_session` / 会话详情 API）。批量列表路径（`list_trace_sessions`、`/api/sessions`、`dashboard_snapshot`）SHALL NOT 触发回填，SHALL 对缺键会话返回 `turn_breakdown: []`。

summary 层 `total_tokens` SHALL 与条目同组成（四项之和，不含 thinking），保证页面顶部总数与逐 turn 明细相加闭合。

两条路径对同一 record 序列 SHALL 产出结构相同、数值相同的结果。

#### Scenario: 全量汇总与增量汇总一致
- **GIVEN** 同一会话的 3 条 record，分别属于 turn 1、turn 2、turn 3
- **WHEN** 用 `_summarize_session` 一次性汇总，或用 `merge_record_into_summary` 逐条累加
- **THEN** 两种方式得到的 `input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_create_tokens`、`thinking_tokens`、`total_tokens`、`turn_breakdown` 完全相等

#### Scenario: thinking tokens 不计入 total
- **GIVEN** 一条 record 的 usage 为 `input_tokens=100`、`output_tokens=50`、`thinking_tokens=20`
- **WHEN** 计算会话汇总额
- **THEN** `total_tokens == 150`
- **AND** `thinking_tokens == 20`

#### Scenario: 同一 turn 多请求合并为一条明细
- **GIVEN** 同一会话中 turn 1 存在 2 条 record，`input_tokens` 分别为 10 和 20
- **WHEN** 生成 `turn_breakdown`
- **THEN** `turn_breakdown` 中 turn 1 条目只有一个
- **AND** 该条目 `input_tokens == 30`、`record_count == 2`

#### Scenario: 同 turn 多条 record 的聚合
- **GIVEN** turn 1 有 3 条 record：A `duration_ms=100`、`model="claude-sonnet-5"`、usage `{input:10, output:5, cache_read:1, cache_create:0, thinking:2}`；B `duration_ms=250`、`model="claude-opus-5"`、usage `{input:20, output:7, cache_read:4, cache_create:3, thinking:1}`；C `duration_ms=0`、`model=""`、无 usage
- **WHEN** 生成 `turn_breakdown`
- **THEN** turn 1 条目 `duration_ms == 350`
- **AND** 该条目 `model == "claude-opus-5"`（最后一条**非空**，C 的空 model 被忽略）
- **AND** 该条目 `input_tokens == 30`、`output_tokens == 12`、`cache_read_tokens == 5`、`cache_create_tokens == 3`
- **AND** 该条目 `thinking_tokens == 3`（累加，但不计入 total）
- **AND** 该条目 `total_tokens == 50`（= 30 + 12 + 5 + 3）
- **AND** 该条目 `record_count == 3`（含无 usage 的 C）

#### Scenario: turn 为 null 的条目排在末尾且唯一
- **GIVEN** 会话含 turn 2、turn 1、一条 `turn` 缺失的 record、一条 `turn="3"`（字符串）的 record、一条 `turn=1.5`（浮点）的 record
- **WHEN** 生成 `turn_breakdown`
- **THEN** 数组顺序为 `[turn=1, turn=2, turn=null]`，共 3 个条目
- **AND** 缺失、字符串、浮点三种情况全部归入同一个 `null` 条目，其 `record_count == 3`
- **AND** 该过程不抛 `ValueError` / `TypeError`

#### Scenario: turn_count 等于条目数（含 null 条目）
- **GIVEN** 会话的 `turn_breakdown` 含 turn 1、turn 2 与一个 `null` 条目
- **WHEN** 读取会话摘要
- **THEN** `turn_count == 3`

#### Scenario: 空 turn_breakdown 时 turn_count 回退
- **GIVEN** 会话 `record_count == 0` 且 `turn_breakdown == []`（无任何 record，或旧缓存摘要缺该字段）
- **WHEN** 读取会话摘要
- **THEN** `turn_count == 0`

#### Scenario: 归一化层到汇总层字段映射
- **GIVEN** 一条 record 的 usage 归一化结果为 `{"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 2, "thinking_tokens": 1}`
- **WHEN** 汇总该 record
- **THEN** summary 中 `input_tokens=10`、`output_tokens=5`、`cache_read_tokens=3`、`cache_create_tokens=2`、`thinking_tokens=1`
- **AND** `total_tokens == 20`（不含 thinking）

#### Scenario: 缺少 usage 的 record
- **GIVEN** 一条 record 的 response body 中没有任何 usage 字段
- **WHEN** 汇总该会话
- **THEN** 该 record 对全部 token 字段贡献 0
- **AND** 该 record 仍计入 `record_count` 与所在 turn 的 `record_count`

#### Scenario: token 字段类型异常不抛错
- **GIVEN** 一条 record 的 usage（归一化层命名）为 `{"input_tokens": "100", "output_tokens": 5.5, "cache_read_input_tokens": null, "cache_creation_input_tokens": "1.5", "thinking_tokens": true}`，且 `duration_ms` 为 `"88"`
- **WHEN** 汇总该 record
- **THEN** 不抛 `TypeError` / `ValueError`
- **AND** 汇总层 `input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_create_tokens`、`thinking_tokens`、`duration_ms` 均按 0 计入

#### Scenario: turn_count 不再被 record_count 覆盖
- **GIVEN** 某会话 turn 1 含 3 条 record，`record_count == 3`、`turn_breakdown` 只有 1 个条目
- **WHEN** 分别经全量路径与增量路径读取
- **THEN** 两条路径的 `turn_count` 均为 1
- **AND** 均不等于 `record_count`

#### Scenario: Gemini 形态含 thoughts 明细
- **GIVEN** usage 为 `{"promptTokenCount": 10, "candidatesTokenCount": 100, "thoughtsTokenCount": 50}`（调用方已展开 `usageMetadata`）
- **WHEN** 调用 `normalize_usage`
- **THEN** 返回 `input_tokens=10`、`output_tokens=100`、`thinking_tokens=50`
- **AND** 经会话汇总时 `total_tokens == 110`，`thinking_tokens` 不计入
- **AND** Gemini 上游 `totalTokenCount` 含 thoughts，本地 `total_tokens` 不含，二者口径差异由页面 tooltip 说明

#### Scenario: 历史会话惰性回填 turn_breakdown
- **GIVEN** `sessions.summary_json` 中缓存的摘要不含 `turn_breakdown` 键，且该会话 `record_count > 0`
- **WHEN** 经单会话详情路径首次读取该会话摘要
- **THEN** 返回结果含由 records 全量重算得到的 `turn_breakdown` 与 `thinking_tokens`
- **AND** `store_summary` 被调用 1 次，写后 `summary_json` 含 `turn_breakdown` 键
- **AND** 第二次读取 `store_summary` 被调用 0 次（以键存在为判据，即使该键值为 `[]`）

#### Scenario: 列表路径不触发惰性回填
- **GIVEN** 3 个会话的缓存摘要均缺 `turn_breakdown` 键，且各自 `record_count > 0`
- **WHEN** 请求 `/api/sessions`
- **THEN** 响应中 3 个会话的 `turn_breakdown` 均为 `[]`
- **AND** `store_summary` 被调用 0 次，未发生任何 records 全量扫描

#### Scenario: 空会话旧缓存不触发重算
- **GIVEN** 会话 `record_count == 0` 且缓存摘要不含 `turn_breakdown` 键
- **WHEN** 经单会话详情路径读取该会话摘要
- **THEN** 返回 `turn_breakdown == []`、`thinking_tokens == 0`
- **AND** 不触发 records 扫描

### Requirement: 三个页面顶部展示全字段与逐 turn 明细

系统 SHALL 在下列三个页面顶部展示 token 统计：

| 页面 | 数据来源 | 顶部汇总 | 逐 turn 明细 |
|------|---------|---------|-------------|
| `dashboard.html` 列表页 | `/api/sessions` | 全部会话合计的全字段指标卡 | 可折叠，按当前筛选的会话分组 |
| `dashboard.html` 会话详情页 | `/api/sessions/{id}/records` 的 `session` | 当前会话全字段 | 可折叠，数据来自 `session.turn_breakdown` |
| `viewer.html` | `entries` / `EMBEDDED_TRACE_META` | 当前筛选结果全字段 | 可折叠，按 `entry.turn` 分组 |

字段集 SHALL 为：Input、Output、Cache Read、Cache Write、Thinking、Total。

所有字段 SHALL 常显，值为 0 或缺失时显示 `0`，**不得**隐藏字段。

`viewer.html` 顶部 `Tokens` 汇总值 SHALL 使用四项之和（input + output + cache_read + cache_creation），与 `dashboard.py:total_tokens` 口径一致。

`viewer.html` 的 JS 侧 `normalizeUsage` SHALL 映射与后端相同的四路来源，统一按同一优先级写入 `usage.thinking_tokens`。任一路径的容器为 `null` 或非对象时 SHALL 跳过该路且不抛异常；取值非有限数值时 SHALL 视为无效并继续尝试后续别名；四路全部无效时 SHALL NOT 写入该键（与后端一致，SHALL NOT 以 `0` 占位写键）。

`buildStubEntry` SHALL 仅在 `usage` 缺少 `thinking_tokens` **且** `meta.thinking_tokens` 为有限数值时补齐；`meta` 值为无效值时 SHALL NOT 注入。响应 usage 优先于 meta。

`viewer.html` 累加 Thinking 与逐 turn 的 Total / Thinking 时 SHALL 逐条经有限数值校验（无效值按 `0` 参与累加），SHALL NOT 让单条无效值把整组求和污染为 `NaN`。

`viewer.html` 渲染 Thinking 数值前 SHALL 经数值强制转换，非有限数值（`NaN` / `undefined` / 非数字字符串）SHALL 渲染为 `0`，SHALL NOT 渲染 `NaN` 或 `undefined`。

`viewer.html` 逐 turn 分组 SHALL 复用后端规则：`turn` 缺失或非整数（字符串、浮点）归入同一个 `null` 分组。

`viewer.html` 逐 turn 分组的 `null` 分组行 Turn 列 SHALL 显示经 i18n 的占位文案（key `turn_breakdown_unknown_turn`），SHALL NOT 显示 `null` 或 `undefined`。

`Thinking` 字段的 tooltip SHALL 按 provider 区分：

- Anthropic / OpenAI：注明「Thinking / Reasoning 已包含在 Output 内，不重复计入 Total」。
- Gemini：注明「Thoughts 不计入 Candidates（Output），单独展示」。

tooltip 文案 SHALL NOT 对未识别的 provider 作任何包含关系的断言。

#### Scenario: viewer 顶部字段常显
- **GIVEN** 当前筛选结果中只有 `input_tokens=100`、`output_tokens=10`，其余字段为 0
- **WHEN** 渲染 viewer 顶部统计条
- **THEN** 显示 Input=100、Output=10、Cache Read=0、Cache Write=0、Thinking=0、Total=110
- **AND** 五个 usage 字段与派生的 Total 均可见

#### Scenario: viewer 从四路来源提取 thinking
- **GIVEN** 分别构造四条 record（分属四个独立会话，避免同页聚合），usage 各含：① `output_tokens_details.thinking_tokens=20`；② `output_tokens_details.reasoning_tokens=30`；③ `completion_tokens_details.reasoning_tokens=40`；④ 响应 payload 为 `{"response": {"usageMetadata": {"thoughtsTokenCount": 50}}}`（`geminiUsageFromPayloads` 展开后传入 `normalizeUsage`）
- **WHEN** viewer 的 `getUsage` 解析每条 record
- **THEN** 四条 record 各自的 Thinking 依次为 20 / 30 / 40 / 50（单会话视图下）
- **AND** 四条均不显示 `NaN` 或 `undefined`

#### Scenario: thinking 字段值异常时显示 0
- **GIVEN** 一条 record 的 usage 为 `{"input_tokens": 10, "output_tokens": 5, "output_tokens_details": {"thinking_tokens": "abc"}}`，且另一条为 `{"output_tokens_details": null}`
- **WHEN** viewer 渲染顶部统计
- **THEN** Thinking 显示 `0`，且不抛错中断渲染
- **AND** Total 为 15（仅由 input + output 构成）

#### Scenario: dashboard 详情页展示逐 turn 明细
- **GIVEN** 某会话的 `turn_breakdown` 含 turn 1、turn 2 两条明细
- **WHEN** 打开 `/dashboard/session/{id}`
- **THEN** 页面顶部展示该会话全字段汇总
- **AND** 存在可折叠的逐 turn 明细区域，展开后列出 turn 1 与 turn 2 的全字段数值

#### Scenario: dashboard 列表页汇总口径
- **GIVEN** 列表页显示 2 个会话，`total_tokens` 分别为 100 和 200
- **WHEN** 渲染概览区
- **THEN** Total 指标为 300
- **AND** Input/Output/Cache Read/Cache Write/Thinking 各自为两会话对应字段之和

#### Scenario: 空会话
- **GIVEN** 会话没有任何 record，或无任何 usage 字段
- **WHEN** 渲染三个页面任一顶部统计
- **THEN** 所有 token 字段显示 0
- **AND** 逐 turn 明细区域显示空状态提示，不渲染空表格

### Requirement: 前端展示无跨站请求与无外部依赖

系统 SHALL 保持 `dashboard.html` 与 `viewer.html` 的现有安全约束：token 统计数据 SHALL 通过既有同源 aiohttp 路由（`kiro_tap/live.py`）获取，SHALL NOT 引入新的外部 HTTP 端点、CDN 资源或前端构建产物。

所有新增 DOM 文本 SHALL 经既有转义函数（`esc()`）处理后插入，SHALL NOT 使用 `innerHTML` 拼接未经转义的外部值。

#### Scenario: 无新增外部资源
- **WHEN** 检查本次变更后的 `dashboard.html` 与 `viewer.html`
- **THEN** 不存在指向外部域名的 `<script>`、`<link>` 或 `fetch()` 目标
- **AND** 新增数据全部来自既有 `/api/*` 路由

#### Scenario: 逐 turn 明细的 model 字段转义
- **GIVEN** 某会话的 `turn_breakdown` 条目中 `model` 为 `<script>alert(1)</script>`
- **WHEN** 渲染逐 turn 明细
- **THEN** 页面显示该字符串的转义文本
- **AND** 不执行任何脚本

### Requirement: Token 统计跨线程边界一致性

系统 SHALL 在 `kiro_tap/trace_store.py:append_record` 经由 `_refresh_summary_after_append` 更新 `summary_json` 时，保持 SQLite 写入在调用方线程池（`TraceWriter.write` 的 `run_in_executor`）内执行，SHALL NOT 在 asyncio 事件循环中直接调用 `sqlite3`。

`turn_breakdown` 的增量更新 SHALL 与 `append_record` 处于同一 `TraceStore._write_lock` 临界区内，保证同一会话的并发追加不会产生部分更新的摘要。

#### Scenario: 并发追加不产生部分摘要
- **GIVEN** 同一会话被多线程并发调用 `append_record`
- **WHEN** 全部写入完成
- **THEN** `summary_json` 中的 `record_count` 等于实际 record 数
- **AND** `turn_breakdown` 各条目 `record_count` 之和等于实际 record 数