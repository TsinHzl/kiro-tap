## ADDED Requirements

### Requirement: 顶部统计栏常驻展示

`kiro_tap/dashboard.html`（列表页）与 `kiro_tap/viewer.html`（详情页与独立导出页）SHALL 在内容区顶部提供一条常驻横向统计栏（DOM 容器 `class="top-bar"`，内含 `id="stats"`），滚动内容区时保持可见。

顶部统计栏 SHALL 固定在内容区顶部（`position: fixed`），左边界与既有 232px 侧边栏右边缘对齐，高度 44px，横向单行排列；统计项 SHALL NOT 被压缩截断。

`kiro_tap/viewer.html` 的顶部统计栏与既有 `#stats` 节点为同一元素（容器 `class="top-bar" id="stats"`），因此既有空 trace / live 等待 / 有数据三种状态下的显隐切换 SHALL 作用于整个顶部条，SHALL NOT 出现内容隐藏而容器仍占位的空条。

`kiro_tap/viewer.html` 的顶部统计栏 SHALL 在 `body:not(.standalone)`（被 dashboard 以 iframe 内嵌）时隐藏，与既有 `.header` 的隐藏策略一致；`kiro_tap/dashboard.html` 的顶部统计栏 SHALL 在 `body.detail-route`（详情路由）时隐藏，避免与内嵌 viewer 产生双重统计与额外顶部空白。

#### Scenario: 列表页顶部统计栏可见且随筛选更新
- **GIVEN** 用户在浏览器打开 shared dashboard 的列表页
- **WHEN** 页面加载完成
- **THEN** 内容区顶部出现横向统计栏，包含 Sessions、Records、Total、In、Out、Cache R、Cache W、Thinking 与 Live 状态
- **AND** 切换日期或状态筛选后，上述 8 个数值同步刷新为当前筛选结果集合的汇总值

#### Scenario: 详情页顶部统计栏随路径筛选更新
- **GIVEN** 用户打开某个 trace 的 viewer 详情页
- **WHEN** 点击某条路径筛选 chip 或输入搜索词
- **THEN** 顶部统计栏的 Turns、Total、In、Out、Cache R、Cache W、Thinking、Time 同步刷新为当前 `filtered` 集合的汇总值
- **AND** 统计栏自身位置不随内容滚动而移动

#### Scenario: 内嵌与详情路由下隐藏
- **GIVEN** viewer 被 dashboard 以 iframe 方式内嵌（`body` 无 `standalone` class）
- **WHEN** 页面渲染完成
- **THEN** viewer 的顶部统计栏不渲染
- **AND** dashboard 进入 `body.detail-route` 状态后，其自身顶部统计栏不渲染，主内容区顶部无 44px 空白

#### Scenario: 空 trace 与 live 等待态无空条残留
- **GIVEN** viewer 加载了一个不含受支持 API 请求的 trace 文件，或处于 live 等待首个请求的状态
- **WHEN** 页面渲染完成
- **THEN** 顶部统计栏整条不可见
- **AND** 内容区首元素上方不存在 44px 空白条

#### Scenario: 窄屏换行不重叠
- **GIVEN** 视口宽度为 375px
- **WHEN** 顶部统计栏渲染
- **THEN** 统计项换行排列，全部可见
- **AND** 主内容区首个元素的上边缘位于统计栏下方，无遮挡与重叠

### Requirement: 顶部统计与既有汇总同源同值

顶部统计栏的每个数值 SHALL 复用既有汇总结果，SHALL NOT 引入独立的统计口径或第二轮数据遍历。

- `kiro_tap/dashboard.html`：Sessions / Records / Total / In / Out / Cache R / Cache W / Thinking SHALL 取自 `renderOverview(sessions)` 中既有的求和变量；Total SHALL 等于 `input + output + cache_read + cache_create`，不含 `thinking`。
- `kiro_tap/viewer.html`：各字段 SHALL 取自 `applyFilter()` 中对 `filtered` 的既有累加变量。

#### Scenario: 顶部 Total 与逐字段相加闭合
- **GIVEN** 当前筛选结果集合中 In=100、Out=50、Cache R=30、Cache W=20、Thinking=7
- **WHEN** 顶部统计栏渲染完成
- **THEN** Total 显示 200
- **AND** Thinking 显示 7，且 Thinking 未被计入 Total

#### Scenario: 无 usage 数据时字段隐藏
- **GIVEN** viewer 当前筛选集合中所有 record 均无 usage
- **WHEN** 顶部统计栏渲染完成
- **THEN** In / Out / Cache R / Cache W / Thinking 五组不显示
- **AND** Turns、Total、Time 仍显示（Total 为 0）
