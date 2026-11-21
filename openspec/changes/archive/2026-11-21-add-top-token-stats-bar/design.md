## 上下文

两个前端文件同为「232px 固定侧边栏 + 右侧内容区」布局，纯内联 HTML/CSS/JS，无构建工具。

- `kiro_tap/viewer.html`：`.header` 是左侧 232px 固定侧栏，内含 logo、路径筛选、`.stats`（8 组统计）、动作按钮、语言选择器。`.main` 通过 `margin-left: 232px` 让位。`body:not(.standalone)` 时整个 `.header` 隐藏。
- `kiro_tap/dashboard.html`：`.header` 同为左侧 232px 固定侧栏，`.stats` 只有 Sessions / Records / Watching；6 个 token 字段在主内容区 `overview-card` 内。`body.detail-route` 时 `.header` 隐藏、`.main` 取消左偏移。

统计计算函数已存在且口径已固定（`openspec/specs/trace-statistics/spec.md`）；本次只调整展示位置与结构。

## 目标 / 非目标

**目标**

- 两页各新增一条常驻顶部横向统计栏，展示全部 token 字段。
- 最大化复用既有 DOM id 与既有汇总变量，避免统计口径分叉。

**非目标**

- 不改变侧边栏宽度与整体骨架；不删除 `overview-card`。
- 不改变后端 schema、归一化、汇总逻辑。
- 不重写 viewer 的响应式断点体系，只在既有 `@media (max-width: 768px)` 内追加覆盖。

## 决策

### 决策 1：新容器 `.top-bar` 而非改造 `.header`

把统计组从 `.header` 抽出到新的 `.top-bar`，`.header` 只保留 logo、路径筛选、动作按钮、语言选择器。

理由：`viewer.html` 的 `.header` 在 `body:not(.standalone)` 下整体隐藏，顶部条需要同一行为，独立容器便于按场景分别控制；同时避免改动 `.header` 的 `flex-direction: column` 布局与内部 flex 分配。

### 决策 2：保留既有 DOM id，只移动节点；`.top-bar` 直接复用 `id="stats"`

`#stat-turns` / `#stat-tokens` / `#stat-input` 等 id 在 `applyFilter()` 中直接赋值。迁移节点而不改 id，使 JS 侧只需处理 dashboard 新增的 6 个 token 节点。

进一步地，`viewer.html` 的新容器直接命名为 `<div class="top-bar" id="stats">`，而非新增独立容器再迁移。理由：JS 中三处 `$('#stats').style.display` 切换（空 trace / live 等待 / 有数据）**立即作用于整个顶部条**，不需要新增或改写任何显隐逻辑，也避免出现「内容隐藏但 44px 空条残留」的状态。

`dashboard.html` 的统计显隐由 `body.detail-route` 控制，容器注入 class 即可，不存在容器内部分隐藏的场景，故其 `.top-bar` 不挂 `id="stats"`。

### 决策 3：dashboard 顶部统计复用 `renderOverview` 的中间变量

`renderOverview(sessions)` 已经用 7 次 `reduce` 算完全部字段。顶部条赋值追加在同一函数内，零额外遍历。`overview-card` 保留，因为 Threads / Traces / Error Rate 三项不在顶部条范围内。

### 决策 4：`position: fixed` + 内容区 padding

顶部条 `position: fixed; top: 0; left: 232px; right: 0; height: 44px`。`.main` 增加 `padding-top: 44px`（viewer 为 `padding-top: 56px` 以容纳既有 trace-path-bar，若其显示）。

替代方案（sticky）在 `viewer.html` 的 `.main { overflow: hidden }` + 内部独立滚动容器结构下不可靠，固定定位更确定。

### 决策 5：窄屏改为静态布局

`@media (max-width: 768px)` 内 `.top-bar` 改为 `position: static`、`flex-wrap: wrap`，`.main` 的 `margin-top` 在既有 110px 基础上加上统计栏实际高度，或将统计栏作为流内元素（不使用 fixed），避免与既有移动端偏移叠加。

### 决策 6：RTL 不引入额外定位规则

现状核查结论：`viewer.html` 的 `[dir="rtl"]` 规则只调整 `#sidebar-wrap` 边框、`.sidebar-item` 边框方向、`.si-model` 与 `.stats` 的 `margin`，**并未镜像 232px 固定 `.header`**——RTL 下侧栏仍在左侧。因此若给 `.top-bar` 加 `left: 0; right: 232px`，顶部条会与侧栏横向重叠。正确做法是保持 `left: 232px`，仅做一次 RTL 目视验证。

## 风险 / 权衡

| 风险 | 权衡 |
|---|---|
| 44px 高度挤压内容区 | 可接受：现有 `.header` 内 `.stats` 已占 8×~22px；移出后侧栏反而更宽松 |
| dashboard 顶部与 `overview-card` 数值重复 | 保留 `overview-card` 以免丢失 Threads / Traces / Error Rate；用户明确要求顶部展示 |
| 空 trace / live 等待页需同步切换统计栏显隐 | 在两个既有状态函数中追加一行，成本低 |
| 移动端已有 `margin-top: 110px` 魔法值 | 本次不重构该值，只在末尾追加统计栏高度补偿，并在窄屏手工验证 |

## 迁移方案

无数据迁移。改动集中在两个 HTML 文件的 `<style>` 与 `<body>` 标记段、以及 `dashboard.html` 的 `renderOverview()` 追加赋值。

## 待决问题

无。用户已确认：范围 = viewer 详情页 + dashboard 列表页；侧边栏保留；口径 = 当前会话 / 当前筛选结果。
