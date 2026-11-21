# 任务清单：add-top-token-stats-bar

## 状态：ARCHIVED

## 变更类型

- 本变更仅涉及 `kiro_tap/viewer.html`、`kiro_tap/dashboard.html` 两个前端文件；无 spec 级后端行为变化。

## 任务

### viewer.html 顶部统计栏
- [x] T1 新增 `.top-bar` 容器并**直接复用它承载 `id="stats"`**（即 `<div class="top-bar" id="stats" style="display:none">`）。CSS：`position: fixed; top: 0; left: 232px; right: 0; height: 44px`，横向 flex，颜色沿用 CSS 变量；`body:not(.standalone) .top-bar { display: none }`。
  - 验证：`grep -c 'id="stats"' kiro_tap/viewer.html` 输出 1 且该行同时含 `class="top-bar"`。
- [x] T2 将现有 `.stat-group` 子节点（Turns / Tokens / In / Out / Cache R / Cache W / Think / Time / `#live-status`）从 `.header` 迁入 `.top-bar#stats`，DOM id 全部保留。
  - 验证：`grep -c 'id="stat-turns"\|id="stat-tokens"\|id="stat-input"\|id="stat-output"\|id="stat-cache-read"\|id="stat-cache-write"\|id="stat-thinking"\|id="stat-duration"' kiro_tap/viewer.html` 输出 8（每个 id 恰好 1 次）。
- [x] T3 调整 `viewer.html` 布局：`.main` 增加 `padding-top: 44px`；`@media (max-width: 768px)` 内 `.top-bar` 改为流内（`position: static`）、`flex-wrap: wrap`，并把既有 `.stats` 的两处移动端规则（`flex-direction: row` / `flex-wrap: wrap` / `padding: 0` / `width: 100%` / 字号 11px）迁移到 `.top-bar` 选择器；同时修正 `.main` 的 `margin-top`（现为 110px），确保顶部条位于侧栏头之下、内容区位于顶部条之下。
  - 验证：桌面宽度 ≥1280px 统计栏单行不换行、内容区不被遮挡；375px 与 768px 下统计栏换行、内容区无重叠（截图记录，并注明顶部条底边 y 坐标 < 内容区首个元素顶边 y 坐标）。
- [x] T4 无 RTL 改动：既有 `.header` 在 `[dir="rtl"]` 下仍固定左侧，`.top-bar` 的 `left: 232px` 同样成立。仅在 DevTools 将 `<html dir="rtl">` 后确认统计栏与内容区未错位、未横向溢出（截图记录），发现问题再补规则，不得预先引入 `left: 0; right: 232px`。
  - 验证：RTL 截图，统计栏与侧栏无重叠。
- [x] T5 迁移后清理与显隐语义：`.top-bar` 即 `#stats`，`applyFilter()` / `renderEmptyTraceState()` / `renderLiveWaitingState()` 中现有的 `$('#stats').style.display` 切换**直接作用于整个顶部条**，无需改 JS；仅删除 `.header .stats` 相关死样式（含 `.header .stats .stat-group` 与移动端 `.stats` 选择器迁移）。
  - 验证：空 trace 页与 live 等待页顶部条完全消失（无 44px 空条）；加载有数据的 trace 后显示；`grep -n '\.header \.stats' kiro_tap/viewer.html` 无输出。

### dashboard.html 顶部统计栏
- [x] T6 新增 `.top-bar` 容器与其 CSS（同 viewer 侧方案，含窄屏规则），承载 `#stat-sessions`、`#stat-records`、`.live-status` 的迁移节点；删除 `.header` 内旧 `.stats` 块。`.top-bar` 自身无内联 display，列表页常驻可见。
  - 验证：`grep -c 'id="stat-sessions"' kiro_tap/dashboard.html` 输出 1；`grep -c 'id="stat-records"' kiro_tap/dashboard.html` 输出 1。
- [x] T7 在 `.top-bar` 内新增 6 个 token 统计节点：`top-total-tokens`、`top-input`、`top-output`、`top-cache-read`、`top-cache-write`、`top-thinking`，带 i18n label 与颜色圆点（`--primary` / `--green` / `--cyan` / `--amber` / `--orange`）。
  - 验证：`grep -c 'id="top-total-tokens"\|id="top-input"\|id="top-output"\|id="top-cache-read"\|id="top-cache-write"\|id="top-thinking"' kiro_tap/dashboard.html` 输出 6。
- [x] T8 扩展 `renderOverview(sessions)`：把已计算出的 `tokens` / `input` / `output` / `cacheRead` / `cacheWrite` / `thinking` 同步赋值给 `#top-*` 节点（复用同一次 `reduce`，不新增遍历）。
  - 验证：本地启动 dashboard，切换日期/状态筛选，顶部 6 个数值与 `overview-card` 对应字段逐一同值（截图记录）。该改动无自动化测试覆盖（现有前端无 UI 测试）。
- [x] T9 处理 `dashboard.html` 详情路由：`body.detail-route .top-bar { display: none }`，并让 `.main` 在该状态下恢复原始 `padding-top`；宽屏/窄屏均不得出现双重偏移。
  - 验证：进入某会话详情页，顶部条消失、iframe viewer 顶部无 44px 空白；返回列表页后顶部条恢复。
- [x] T10 `dashboard.html` i18n：`en` / `zh-CN` 两组字典补齐顶部条 token 标签（优先复用已有 `metric_total_tokens` / `metric_input_tokens` / `metric_output_tokens` / `metric_cache_read` / `metric_cache_write` / `metric_thinking`，缺哪个补哪个）。
  - 验证：切换语言后顶部 6 个标签全部渲染为对应语言，无键名裸露。

### 验证
- [x] T11 全量验证：`ruff check .` 零错误、`pytest -q` 全绿。
  - 验证：命令输出粘贴至对话。
- [x] T12 手动浏览器验证（无自动化 UI 测试）：dashboard 列表页、会话详情页（iframe viewer）、独立导出的 HTML viewer 三处顶部条截图核对；桌面 1440px、768px、375px 各一次；RTL 一次。
  - 验证：截图描述写入对话。

## 验收标准
- [ ] `dashboard.html` 列表页顶部常驻一行：Sessions / Records / Total / In / Out / Cache R / Cache W / Thinking / Live，随筛选条件实时更新。
- [ ] `viewer.html`（含 dashboard 内嵌与独立导出的 HTML）顶部常驻一行：Turns / Total / In / Out / Cache R / Cache W / Thinking / Time / Live，随路径筛选与搜索实时更新。
- [ ] 桌面宽度（≥1280px）下顶部条单行显示，所有统计项完整可见，无横向溢出。
- [ ] 窄屏 375px / 768px 下顶部条换行显示，统计项总高度 ≤ 2 行（88px），内容区首元素顶边 y 坐标大于顶部条底边 y 坐标。
- [ ] `[dir="rtl"]` 下顶部条与侧栏无重叠、无横向溢出（无需 RTL 专属定位规则）。
- [ ] `body.detail-route` 详情路由下顶部条隐藏，iframe 顶部无额外空白。
- [ ] `body:not(.standalone)` 内嵌 viewer 下顶部条隐藏（与既有 `.header` 隐藏策略一致）。
- [ ] viewer 空 trace / live 等待状态下顶部条完全隐藏（无 44px 空条）。
- [ ] dashboard 列表页顶部条与 `overview-card` 数值重复展示为刻意设计，保留双方。
- [ ] 顶部统计数值与既有 `overview-card` / `#stats` 数值同源同值；Total = In + Out + Cache R + Cache W，不含 Thinking。
- [ ] `ruff check .` 零错误；`pytest -q` 全绿。
