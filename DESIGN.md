# DESIGN.md — 招投标采集系统

> AI Agent 设计系统文档。告诉 AI「这个项目长什么样，应该怎么写 UI」。

---

## 1. Visual Theme & Atmosphere

**风格定位**: 数据密集型 SaaS 运营后台（Data-Dense Operations Dashboard）

**设计哲学**:
- **信息优先**: 屏幕上永远显示最多的有效信息，不浪费空间
- **状态清晰**: 每个元素的状态（正常/警告/危险/运行中/停用）通过颜色一目了然
- **专业克制**: 无插图、无过度动画、无装饰性元素；功能即美学
- **暗色友好**: 全系统支持 dark mode，切换无闪烁

**视觉隐喻**: 专业级数据监控台（类似 Grafana + Linear 的混合）

**情感关键词**: 可靠、高效、精确、可信赖

---

## 2. Color Palette

### Light Mode

| Token | Hex | Role | Usage |
|-------|-----|------|-------|
| `primary` | `#3b82f6` | 品牌蓝 / 主操作 | 按钮、链接、激活状态、进度条 |
| `primary-hover` | `#2563eb` | 主色悬停 | 按钮悬停态 |
| `primary-light` | `#eff6ff` | 主色背景 | 徽章背景、选中行高亮 |
| `success` | `#16a34a` | 成功绿 | 上线状态、正常指标、完成徽章 |
| `success-light` | `#dcfce7` | 成功背景 | 成功徽章背景 |
| `warning` | `#d97706` | 警告橙 | 即将过期、需要注意 |
| `warning-light` | `#fef3c7` | 警告背景 | 警告徽章背景 |
| `danger` | `#dc2626` | 危险红 | 错误、失败、删除、已过期 |
| `danger-light` | `#fee2e2` | 危险背景 | 危险徽章背景 |
| `bg-base` | `#f8fafc` | 页面背景 | `bg-gray-50` |
| `bg-card` | `#ffffff` | 卡片背景 | `bg-white` |
| `bg-nav` | `#ffffff` | 导航栏背景 | `bg-white` |
| `text-primary` | `#1e293b` | 主文本 | `text-slate-800 / text-gray-900` |
| `text-secondary` | `#64748b` | 次要文本 | `text-slate-500 / text-gray-500` |
| `border` | `#e2e8f0` | 边框色 | `border-gray-200` |
| `border-dark` | `#334155` | 暗色边框 | `dark:border-gray-700` |

### Dark Mode

| Token | Hex | Role |
|-------|-----|------|
| `bg-base` | `#0f172a` | 页面背景 (`slate-900`) |
| `bg-card` | `#1e293b` | 卡片背景 (`gray-800`) |
| `bg-nav` | `#1e293b` | 导航栏背景 (`gray-800`) |
| `text-primary` | `#f1f5f9` | 主文本 (`slate-100`) |
| `text-secondary` | `#94a3b8` | 次要文本 (`slate-400`) |
| `border` | `#334155` | 边框 (`gray-700`) |

### 状态色（Light + Dark 通用）

| State | Light Token | Dark Token | 用法 |
|-------|------------|------------|------|
| Running/Active | `#dcfce7` / green | green-900/30 | 正在执行 |
| Idle/Pending | `#dbeafe` / blue | blue-900/30 | 空闲待执行 |
| Disabled/Off | `#f1f5f9` / gray | gray-700 | 已停用 |
| Completed | `#f0fdf4` / green | green-900/20 | 已完成 |
| Failed/Error | `#fee2e2` / red | red-900/30 | 失败 |

---

## 3. Typography

**字体栈**: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
（系统原生字体，无外部字体依赖，保证加载速度）

**中文字体回退**: `'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif`

### 字号层级

| Class | Size | Weight | 用途 |
|-------|------|--------|------|
| `text-xs` | 12px | 400 | 标签、徽章、次要说明 |
| `text-sm` | 14px | 400/500 | 正文、按钮、表格内容 |
| `text-base` | 16px | 400 | 默认正文 |
| `text-lg` | 18px | 600 | 页面标题 |
| `text-xl` | 20px | 700 | 大标题 |
| `text-2xl` | 24px | 700 | 统计数字 |
| `text-3xl+` | 30px+ | 700 | Hero 数字 |

### 行高 & 字间距
- 标题: `tracking-tight` (letter-spacing: -0.025em)
- 正文: 默认 (line-height: 1.5)
- 紧凑数据: `leading-tight` (line-height: 1.25)

---

## 4. Component Styling

### 按钮系统

**主按钮 (Primary)**
```html
class="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition shadow-sm"
```
- 默认: `bg-blue-600`
- 悬停: `hover:bg-blue-700`
- 禁用: `opacity-50 cursor-not-allowed`
- 尺寸变体: `px-3 py-1.5 text-xs` (small), `px-6 py-3 text-base` (large)

**次按钮 (Secondary)**
```html
class="px-4 py-2 text-sm font-medium border border-gray-300 text-gray-700 bg-white hover:bg-gray-50 rounded-lg transition"
```
- 暗色: `dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700`

**危险按钮 (Danger)**
```html
class="px-4 py-2 text-sm font-medium text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition"
```

**图标按钮**
```html
class="p-2 rounded-md text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition"
```

### 卡片

```html
class="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 p-4"
```
- 悬停增强: `hover:shadow-md transition-shadow`
- 内边距标准: `p-4` (小卡片), `p-6` (大面板)

### 徽章 / 状态标签

```html
<!-- 运行中 -->
class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 rounded-full"

// 空闲
class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 rounded-full"

// 已停用
class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400 rounded-full"

// 危险
class="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 rounded-full"
```

### 输入框

```html
<input type="text" placeholder="搜索..."
  class="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm
         bg-white dark:bg-gray-700 dark:text-white
         focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
         placeholder-gray-400 dark:placeholder-gray-500 transition">
```

### 表格

```html
<table class="w-full text-sm text-left">
  <thead class="text-xs text-gray-500 dark:text-gray-400 uppercase bg-gray-50 dark:bg-gray-800/50">
    <tr>
      <th class="px-4 py-3 font-medium">列头</th>
    </tr>
  </thead>
  <tbody class="divide-y divide-gray-100 dark:divide-gray-700">
    <tr class="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition">
      <td class="px-4 py-3">内容</td>
    </tr>
  </tbody>
</table>
```

### 导航栏

```html
<nav class="sticky top-0 z-40 bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700">
  <!-- 桌面端 -->
  <a href="/page" class="nav-link nav-link--desk text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/30">
    📎<span class="nav-label">文字</span>
  </a>
  <!-- 移动端 -->
  <a href="/page" class="mobile-nav-item">📎 文字</a>
</nav>
```

### 模态框

```html
<!-- Overlay -->
class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"

<!-- Dialog -->
class="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-y-auto"

<!-- 暗色 Overlay -->
class="fixed inset-0 bg-black/70 backdrop-blur-sm"
```

### Toast 通知

```html
<!-- Success -->
class="border-l-4 border-green-500 bg-white shadow-lg"

<!-- Error -->
class="border-l-4 border-red-500 bg-white shadow-lg"

<!-- 动画 -->
class="transition-all duration-300 translate-x-full"
```

---

## 5. Layout Principles

### 页面结构

```
┌─────────────────────────────────────────────┐
│ Navbar (sticky, z-40)                       │
├─────────────────────────────────────────────┤
│ Page Header                                 │
│   - 标题 + 描述                             │
│   - Action Buttons (右侧对齐)                │
├─────────────────────────────────────────────┤
│ Stats Cards Row (optional)                  │
│   [ Stat ] [ Stat ] [ Stat ] [ Stat ]       │
├─────────────────────────────────────────────┤
│ Filters / Toolbar                           │
│   [ Search ] [ Filter▾ ] [ Filter▾ ] [⚡] │
├─────────────────────────────────────────────┤
│ Content Area                                │
│   - Table / Grid / Empty State              │
│   - Pagination (if needed)                  │
└─────────────────────────────────────────────┘
```

### 间距系统（Tailwind 默认）

| Token | Value | 用途 |
|-------|-------|------|
| `px-4` | 16px | 页面水平边距 |
| `py-6` | 24px | 页面垂直间距 |
| `gap-4` | 16px | 卡片间距 |
| `space-y-4` | 16px | 垂直元素间距 |
| `mb-6` | 24px | 区块底部间距 |
| `p-4` | 16px | 卡片内边距 |

### 容器宽度
- 内容区: `max-w-7xl mx-auto px-4 sm:px-6 lg:px-8`
- 窄表单: `max-w-xl mx-auto`
- 宽表格: `max-w-full overflow-x-auto`

### 响应式断点

| Breakpoint | Width | 策略 |
|------------|-------|------|
| `sm` | 640px | 双栏 → 单栏 |
| `md` | 768px | 隐藏部分导航 |
| `lg` | 1024px | 全功能展示 |

### 暗色模式
- **策略**: `darkMode: 'class'` — 通过 `html.dark` 类切换
- **无闪烁**: `<script>` 在 `<head>` 最早期执行，读取 localStorage
- **过渡**: `transition-colors duration-200` 在 `<body>` 上

---

## 6. Depth & Elevation

### 阴影层级

| Level | Class | 用途 |
|-------|-------|------|
| 无 | `shadow-none` | 背景元素 |
| 低 | `shadow-sm` | 卡片、输入框 |
| 中 | `shadow-md` | 悬停卡片、下拉菜单 |
| 高 | `shadow-lg` | 模态框、弹出层 |
| 最高 | `shadow-xl` | 大模态框 |

### 边框
- 卡片边框: `border border-gray-100 dark:border-gray-700`
- 输入框边框: `border border-gray-300 dark:border-gray-600`
- 分隔线: `divide-y divide-gray-100 dark:divide-gray-700`

---

## 7. Do's and Don'ts

### ✅ DO

1. **使用 Tailwind 原生类**: 所有样式通过 Tailwind CSS 类实现，不写自定义 CSS
2. **暗色优先考虑**: 所有颜色同时提供 light/dark 版本（`dark:text-gray-400`）
3. **状态用颜色表示**: Running=绿, Failed=红, Idle=蓝, Disabled=灰
4. **空状态要有提示**: 表格为空时显示空状态插图和引导文案
5. **loading 态要明显**: 骨架屏 (skeleton) 优于空白，spinner 优于无反馈
6. **操作要有确认**: 删除等危险操作必须二次确认
7. **数字要突出**: 关键数字用 `text-2xl font-bold` 突出
8. **Toast 要有结果**: 操作完成后显示成功/失败 Toast

### ❌ DON'T

1. **不要混用颜色**: 主色只用 blue，成功只用 green，危险只用 red
2. **不要硬编码颜色**: 用 Tailwind 类而非 `#fff` / `#000`
3. **不要全局暗色**: 只在 dark mode 区域使用 `dark:` 前缀
4. **不要 0 边距**: 页面内容至少 `px-4`，卡片内至少 `p-4`
5. **不要无限宽度**: 表格外层包 `overflow-x-auto`
6. **不要无 Hover**: 所有可点击元素必须有 hover 态

---

## 8. Responsive Behavior

### 移动端适配策略

| 场景 | 策略 |
|------|------|
| 导航 | 隐藏文字只留图标 → 底部汉堡菜单 |
| 表格 | 横向滚动 (`overflow-x-auto`) |
| 统计卡片 | `grid-cols-2` 双栏 |
| 表单 | 单栏排列，不并排 |
| 按钮 | 全宽堆叠，图标+文字 |

### 移动端导航

```html
<!-- 移动端 hamburger -->
<button @click="nav.mobileOpen = !nav.mobileOpen" class="md:hidden p-2...">
  ☰
</button>

<!-- 移动端菜单 -->
<div id="mobileNav" class="md:hidden hidden border-t ...">
  <a href="/page" class="mobile-nav-item">📎 文字</a>
</div>
```

### Touch Targets
- 最小点击区域: `min-h-[44px] min-w-[44px]`
- 按钮最小尺寸: `px-3 py-2`

---

## 9. Agent Prompt Guide

### 常用 Tailwind 快捷类

```markdown
颜色:
  primary    → blue-600 / hover:blue-700
  success    → green-600 / green-100
  warning    → orange-500 / orange-100
  danger     → red-600 / red-100
  background → gray-50 (light) / gray-900 (dark)
  card-bg    → white (light) / gray-800 (dark)
  text-main  → gray-900 (light) / white (dark)
  text-sub   → gray-500 (light) / gray-400 (dark)

组件:
  card       → bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700
  btn-primary→ px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-sm
  btn-secondary → px-4 py-2 text-sm border border-gray-300 bg-white hover:bg-gray-50 rounded-lg
  input     → border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500
  badge-green → px-2 py-0.5 text-xs rounded-full bg-green-100 text-green-700
  badge-red   → px-2 py-0.5 text-xs rounded-full bg-red-100 text-red-700
```

### 快速生成模板

```markdown
# 生成新页面模板
基于本 DESIGN.md，为 tender-scraper 创建 [页面名称] 页面：
- 使用 Tailwind CSS（dark mode 支持）
- 包含 Page Header + Stats Cards + Table/Grid + Pagination
- 风格与现有页面一致（蓝色主色调）
- 包含空状态设计
- 包含 Loading skeleton
- 移动端适配

# 生成组件
基于本 DESIGN.md，为 tender-scraper 创建 [组件名称] 组件：
- 使用 Tailwind CSS
- 支持 light/dark mode
- 包含所有状态（default/hover/active/disabled/loading）
```

---

## 附录：页面清单

| 路由 | 页面 | 核心组件 |
|------|------|---------|
| `/` | Dashboard | 统计卡片 + 快捷入口 |
| `/data` | 采集内容 | 数据表格 + 筛选 |
| `/favorites` | 收藏 | 收藏列表 |
| `/analytics` | 数据分析 | 图表 + 趋势 |
| `/nl-query` | 智能查询 | 搜索框 + 结果 |
| `/qualifications` | 资质管理 | 表格 + 上传弹窗 |
| `/logs` | 日志 | 日志列表 |
| `/settings` | 设置 | 表单 |
| `/tasks` | 任务管理 | 统计 + 列表 + 向导 |
| `/documents/upload` | → 重定向 /qualifications | — |
