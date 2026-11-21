# 变更提案：add-top-token-stats-bar

## 背景

当前 token 统计的位置与信息密度不一致：

- `viewer.html`：Turns / Tokens / In / Out / Cache R / Cache W / Think / Time 全部竖向堆在 232px 侧边栏的 `.stats` 容器里，侧边栏被撑高、可视区变窄，扫读成本高。
- `dashboard.html`：侧边栏只有 Sessions / Records / Watching；6 个 token 字段散落在主内容区的 `overview-card` 里，滚动后即消失。

截图中参考实现（claude-tap）把统计压成一行常驻顶部：`Turns N · Total API tokens N · ● In N · ● Out N · ● Cache R N · Time Ns · Live`。用户要求在本仓库两个页面复刻同样的顶部统计栏，并且展示**全部** token 字段。

## 目标范围

**在范围内：**

- `kiro_tap/viewer.html`：新增常驻顶部统计栏，承载现有 `#stats` 全部字段（Turns / Total / In / Out / Cache R / Cache W / Thinking / Time）与 Live 状态；侧边栏保留 logo、路径筛选、动作按钮、语言选择器。
- `kiro_tap/dashboard.html`：新增常驻顶部统计栏，承载 Sessions / Records / Live 状态与 token 全字段（Total / In / Out / Cache R / Cache W / Thinking），数据源为当前筛选后的会话集合。
- 两页顶部统计栏复用既有 DOM id 与既有汇总函数，不改动 token 汇总口径。
- 窄屏（≤768px）下顶部统计栏允许换行，不遮挡内容。
- RTL 下无需额外规则：既有 232px `.header` 在 `[dir="rtl"]` 下仍固定左侧（现有 RTL 规则只调整 `#sidebar-wrap` 边框与条目方向），`.top-bar` 的 `left: 232px` 在 RTL 下同样正确。

**不在范围内：**

- 不改变 232px 侧边栏宽度与「侧栏 + 内容」整体骨架。
- 不改变 `usage.py` / `dashboard.py` 的归一化与汇总逻辑，不新增 SQLite 字段。
- 不改 dashboard 详情路由（`body.detail-route`）内嵌 iframe viewer 的行为；该页已有 `#detail-token-summary` 与逐 turn 明细。
- 不实现截图中的悬停提示气泡与语言下拉以外的交互；`stats_tokens_hint` 已有，仅作为 `title` 属性复用。

## 技术方案

- 两页各新增一个 `.top-bar` 固定定位容器，`left: 232px; right: 0; top: 0`，`height: 44px`，横向 flex，`overflow: hidden`，内部统计项 `flex-shrink: 0`。
- 内容区相应下移：`viewer.html` 的 `.main` 与 `dashboard.html` 的 `.main` 增加顶部内边距；`dashboard.html` 的 `body.detail-route` 下隐藏顶部条并取消下移。
- 把既有统计 DOM 节点（`viewer.html: #stats` 内各 `.stat-group`、`dashboard.html: .stats` 内 `#stat-sessions` / `#stat-records` / `.live-status`）整体迁移到新顶部条，**保留原 id**，因此 `applyFilter()` / `renderOverview()` 的赋值代码不需要重写，仅新增 dashboard 侧 token 字段的赋值。
- `dashboard.html` 新增 6 个 token 统计节点 id（`top-total-tokens` / `top-input` / `top-output` / `top-cache-read` / `top-cache-write` / `top-thinking`），在 `renderOverview(sessions)` 已有的求和结果上直接赋值，避免二次遍历。
- 顶部条颜色沿用现有 CSS 变量（`--primary` / `--green` / `--cyan` / `--amber` / `--orange`），与 `tok_*` 字段颜色语义保持一致。
- 无新增依赖，无构建步骤，纯内联 HTML/CSS/JS。

## 预期影响

- 可视区高度减少 44px；侧边栏内部空出竖向空间（`viewer.html` 的 `.stats` 移出后，路径筛选区获得更多高度）。
- `viewer.html` 在 `body:not(.standalone)`（dashboard iframe 内嵌）下原本隐藏 `.header`，顶部条同理隐藏，因此内嵌场景无回归。
- `dashboard.html` 列表页顶部条与 `overview-card` 出现同值重复展示；`overview-card` 保留（含 Threads / Traces / Error Rate 三个卡片独有指标）。
- 无后端行为变化，无数据库 schema 变化，无 CLI 参数变化。

## 风险

| 风险 | 应对 |
|---|---|
| 固定定位顶部条遮挡内容（漏加 padding）或与移动端 `margin-top: 110px` 叠加导致双重偏移 | 在 `@media (max-width: 768px)` 内显式覆盖 `.top-bar` 定位与 `.main` 偏移，手动在窄屏验证 |
| 迁移 DOM 节点时 id 重复或遗漏，导致统计不更新 | 迁移后全局 grep 校验 id 唯一；用本地 dashboard 实测筛选/切会话后数值变化 |
| `dashboard.html` 详情路由下顶部条残留，挤压 iframe 布局 | `body.detail-route .top-bar { display: none }` + `.main { padding-top: 原值 }` |
| 长数字（百万级）在窄屏溢出 | 顶部条 `overflow-x: auto`，统计项 `white-space: nowrap`，移动端允许换行 |
| RTL 布局下顶部条位置错位 | 现状核查：`[dir="rtl"]` 未镜像 232px 固定 `.header`，故保持 `left: 232px` 不变；RTL 仅做目视验证，发现问题再补规则（不预先引入 `left: 0; right: 232px`） |
