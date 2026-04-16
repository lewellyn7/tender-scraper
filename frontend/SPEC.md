# 前端项目规范 (tender-scraper-frontend)

## 技术栈
- **框架**: Svelte 4 + Vite 5
- **样式**: Tailwind CSS 3 (dark mode: class)
- **路由**: Hash-based client-side routing (#/data, #/favorites...)
- **HTTP**: 原生 fetch，proxy 到后端 `/api`

## 开发
```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 → proxy /api → localhost:9099
npm run build     # 输出到 ../app/templates/spa
```

## 前后端分离
- 前端: Svelte SPA（端口 5173）
- 后端: FastAPI（端口 9099，JSON API）
- 登录状态: 后端 session cookie

## 路由
| Hash | 页面 | 组件 |
|------|------|------|
| #/data | 采集内容 | Data.svelte |
| #/favorites | 收藏 | Favorites.svelte |
| #/analytics | 分析 | Analytics.svelte |
| #/tasks | 任务 | Tasks.svelte |
| #/settings | 设置 | Settings.svelte |
| #/login | 登录 | Login.svelte |

## 规范
- 组件: PascalCase（Navbar.svelte）
- 样式: Tailwind only，不写内联 CSS
- 颜色: CSS var 或 Tailwind 类，不硬编码颜色
- dark mode: `dark:` 前缀
- 动画: CSS transition，duration-75 ~ duration-100（快，Linear风格）
