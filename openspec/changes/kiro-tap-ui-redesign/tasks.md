# 任务清单：kiro-tap-ui-redesign

## 状态：DONE

## 任务
- [x] dashboard.html：替换 `:root` CSS 变量为深色紫黑主题，删除 `[data-theme="dark"]` 块
- [x] dashboard.html：将所有 `var(--blue)` / `var(--blue-bg)` 引用替换为 `var(--primary)` / `var(--primary-bg)`，更新卡片/表格/pill 样式（border-radius、border-color、background）
- [x] dashboard.html：添加 Google Fonts `<link>`（Inter + JetBrains Mono），移除主题切换按钮 DOM
- [x] dashboard.html：将 `.header` top-bar 改为左侧 `.sidebar` 固定布局（232px），`.main` 加 `margin-left: 232px`，添加 ≤768px 响应式规则
- [x] viewer.html：替换 `:root` CSS 变量为深色紫黑主题，删除 `[data-theme="dark"]` 块
- [x] viewer.html：将所有 `var(--blue)` / `var(--blue-bg)` 引用替换为 `var(--primary)` / `var(--primary-bg)`，更新卡片/消息/pill 样式
- [x] viewer.html：添加 Google Fonts `<link>`（Inter + JetBrains Mono），移除主题切换按钮 DOM
- [x] viewer.html：将 `.header` top-bar 改为左侧 `.sidebar` 固定布局（232px），`.main` 加 `margin-left: 232px`，添加 ≤768px 响应式规则

## 验收标准
- [ ] `grep -n 'data-theme="dark"' dashboard.html viewer.html` 无命中
- [ ] `grep -n 'var(--blue)' dashboard.html viewer.html` 无命中
- [ ] 两个页面 `body` 背景色为 `#09090b`
- [ ] sidebar 宽度 232px，`.main` 有 `margin-left: 232px`
- [ ] ≤768px 时 sidebar `position: fixed; width: 100%; height: auto`，main `margin-left: 0`
- [ ] `<link>` 标签引用 Google Fonts Inter + JetBrains Mono
- [ ] 主题切换按钮 `.theme-toggle` DOM 元素已移除
- [ ] dashboard.html JS 回归：filter chip 点击过滤会话列表正常，表格行点击进入详情正常
- [ ] viewer.html JS 回归：侧边栏条目点击展示详情正常，搜索过滤正常，消息块展开/折叠正常
