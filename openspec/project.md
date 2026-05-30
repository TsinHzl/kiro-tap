# 项目上下文

## 技术栈
- Python 3.x，纯标准库 + 少量第三方依赖
- 前端：纯 HTML/CSS/JS（内联，无构建工具），两个独立 HTML 文件
  - `dashboard.html`：会话列表 + 概览指标，1716 行
  - `viewer.html`：单次请求详情查看器，5735 行
- 打包：pyproject.toml，pip 安装

## 架构约定
- 前端样式全部内联在 HTML 文件的 `<style>` 标签中
- CSS 变量驱动主题（`:root` + `[data-theme="dark"]`）
- 无外部 CSS 框架，无构建步骤
- JS 全部内联在 HTML 底部 `<script>` 标签中

## 目录结构
```
kiro_tap/
  dashboard.html   # 会话列表页
  viewer.html      # 请求详情页
  dashboard.py     # 后端路由
  viewer.py        # viewer 后端
```

## 开发约定
- 前端改动直接编辑 HTML 文件
- 无测试框架，手动验证
