# 变更提案：kiro-tap-ui-redesign

## 背景
kiro-tap 的两个 HTML 页面（dashboard.html、viewer.html）使用蓝灰系亮/暗双主题，与 kiro2cc-proxy admin-ui 的深色紫黑风格不一致。需要统一视觉语言。

## 目标范围
**在范围内：**
- CSS 变量替换：固定深色紫黑主题，删除亮色模式和主题切换按钮
- 主色调：蓝色 `#3b82f6` → 紫色 `#a855f7`（neon-purple）
- 背景色系：`#09090b` / `#0f0f11` / `#18181b`
- 边框：`#27272a`
- 字体：加入 Inter（sans）、JetBrains Mono（mono）
- 圆角：`0.75rem`
- 卡片/表格/pill 样式：匹配 admin-ui 风格（border-radius 0.75rem，border-color `#27272a`，bg `#0f0f11`）
- header 改为左侧 sidebar 布局（windsurf 风格，232px 宽，固定定位）
- main 内容区加 `margin-left: 232px`
- 两个文件：`dashboard.html` 和 `viewer.html`

**不在范围内：**
- JavaScript 逻辑（不修改任何 JS 函数）
- 后端 Python 代码
- i18n 文案内容
- 移动端布局（≤768px 保持现有响应式行为，sidebar 在移动端折叠为 top-bar）

**sidebar 布局重组范围（HTML 结构变更边界）：**
- dashboard.html：将 `.header` div 改为 `.sidebar` 固定左侧栏，内含 logo、filter chips、stats、操作按钮；`.main` 加 `margin-left`
- viewer.html：同上，sidebar 内含 logo、path-filter chips、stats、viewer-actions；原 `.header` 内所有子元素移入 sidebar

## 技术方案
**色板映射（`:root` 固定深色）：**
- `--primary`: `#a855f7`（紫色，替代 `--blue`）
- `--primary-bg`: `rgba(168,85,247,0.1)`
- `--accent`: `#06b6d4`（青色）
- `--bg`: `#09090b`
- `--bg-card`: `#0f0f11`
- `--bg-hover`: `#18181b`
- `--bg-active`: `#1c1c1f`
- `--bg-code`: `#18181b`
- `--border`: `#27272a`
- `--border-light`: `#3f3f46`
- `--text`: `hsl(240 4% 85%)`
- `--text-secondary`: `hsl(240 2% 64%)`
- `--text-tertiary`: `hsl(240 2% 45%)`
- neon 色板：green `#22c55e`、yellow `#eab308`、red `#ef4444`、purple `#a855f7`、cyan `#06b6d4`

**JS DOM 兼容性：**
- sidebar 内元素保留原有 id/class，JS 查询不受影响
- 主题切换相关 JS（`initTheme`、`toggleTheme`、`applyTheme`）保留函数体但不调用，不删除（避免引用错误）

**字体引入方式：**
- 使用 `<link>` 标签引入 Google Fonts（Inter 400/500/600/700，JetBrains Mono 400/600）
- fallback 字体栈保留（`system-ui`、`Consolas` 等），网络不可用时自动降级
- ≤768px：sidebar 改为 `position: fixed; top: 0; left: 0; width: 100%; height: auto`（top-bar 模式），main 改为 `margin-left: 0; margin-top: sidebar高度`

## 预期影响
- 纯视觉变更，JS 功能不受影响
- 主题切换按钮从 UI 移除（DOM 元素删除）

## 风险
- viewer.html 有 5735 行，CSS 改动量大，需逐块验证
- sidebar 布局改动需验证 JS 中 `.header` 相关 DOM 查询（已通过保留 id/class 规避）
