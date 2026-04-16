# DESIGN.md — 招投标采集系统

> AI Agent 设计系统文档。告诉 AI「这个项目长什么样，应该怎么写 UI」。
> 设计理念融合 **Linear**（暗色命令台 + 微交互）+ **ClickHouse**（数据密度 + 性能优先）。

---

## 1. Visual Theme & Atmosphere

**风格定位**: 数据密集型 SaaS 运营后台（Data-Dense Operations Dashboard）

**设计哲学**:
- **信息优先**: 屏幕上永远显示最多的有效信息，不浪费空间
- **状态清晰**: 每个元素的状态（正常/警告/危险/运行中/停用）通过颜色一目了然
- **专业克制**: 无插图、无过度动画、无装饰性元素；功能即美学
- **暗色友好**: 全系统支持 dark mode，切换无闪烁

**视觉隐喻**: 专业级数据监控台（Linear + Grafana 混合）

**情感关键词**: 可靠、高效、精确、可信赖

---

## 2. Color Palette

### Dark Mode（主模式）

| Token | Hex | Role | Usage |
|-------|-----|------|-------|
| `bg-base` | `#0f1011` | 页面背景 | 最深背景 |
| `bg-panel` | `#191a1b` | 面板背景 | 侧边栏、卡片 |
| `bg-elevated` | `#28282c` | 悬浮表面 | Hover 态、dropdown |
| `bg-surface` | `rgba(255,255,255,0.03)` | 半透明卡片 | 透明背景卡片 |
| `primary` | `#5e6ad2` | 品牌靛蓝 | 主操作（Linear 风格） |
| `primary-accent` | `#7170ff` | 交互强调 | 链接、激活态 |
| `success` | `#10b981` | 成功绿 | 运行中、完成 |
| `warning` | `#d97706` | 警告橙 | 即将过期 |
| `danger` | `#dc2626` | 危险红 | 错误、失败 |
| `text-primary` | `#f7f8f8` | 主文本 | 近白色，防眼疲劳 |
| `text-secondary` | `#d0d6e0` | 次要文本 | 银灰 |
| `text-muted` | `#8a8f98` | 弱化文本 | 占位符、元数据 |
| `text-subtle` | `#62666d` | 最弱文本 | 时间戳、禁用 |
| `border-subtle` | `rgba(255,255,255,0.05)` | 细微边框 | 默认 |
| `border-standard` | `rgba(255,255,255,0.08)` | 标准边框 | 卡片、输入框 |
| `border-strong` | `rgba(255,255,255,0.12)` | 强调边框 | 选中态 |

### Light Mode

| Token | Hex | Role |
|-------|-----|------|
| `bg-base` | `#f7f8f8` | 页面背景 |
| `bg-panel` | `#f3f4f5` | 面板背景 |
| `bg-elevated` | `#f5f6f7` | 悬浮表面 |
| `bg-surface` | `#ffffff` | 卡片背景 |
| `primary` | `#3b82f6` | 品牌蓝 |
| `text-primary` | `#1e293b` | 主文本 |
| `text-secondary` | `#64748b` | 次要文本 |
| `border` | `#e2e8f0` | 边框 |

### 状态色（Light + Dark 通用）

| State | Light Token | Dark Token | 用法 |
|-------|------------|------------|------|
| Running/Active | `green-100` / green | `green-900/30` | 正在执行 |
| Idle/Pending | `blue-100` / blue | `blue-900/30` | 空闲待执行 |
| Completed | `green-50` / green | `green-900/20` | 已完成 |
| Failed/Error | `red-100` / red | `red-900/30` | 失败 |
| Disabled/Off | `gray-100` / gray | `gray-700` | 已停用 |

---

## 3. Typography

### 字体栈

```css
/* 西文 */
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
/* 中文回退 */
font-family: 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', sans-serif;
/* 代码 */
font-family: 'Berkeley Mono', 'SF Mono', ui-monospace, Menlo, monospace;
```

> **OpenType 特性**: 启用 `"cv01", "ss03"` 使 Inter 更几何化（可选，通过 CSS `font-feature-settings`）

### 字号层级（融合 Linear + ClickHouse）

| Role | Size | Weight | Line Height | Letter Spacing | 用途 |
|------|------|--------|-------------|----------------|------|
| Display XL | 72px | 510 | 1.00 | -1.584px | Hero 大标题 |
| Display L | 64px | 510 | 1.00 | -1.408px | 次级 Hero |
| Display | 48px | 510 | 1.00 | -1.056px | 区块标题 |
| Heading 1 | 32px | 400 | 1.13 | -0.704px | 页面标题 |
| Heading 2 | 24px | 400 | 1.33 | -0.288px | 副标题 |
| Heading 3 | 20px | 590 | 1.33 | -0.24px | 卡片标题 |
| Body Large | 18px | 400 | 1.60 | -0.165px | 描述文本 |
| Body | 16px | 400 | 1.50 | normal | 默认正文 |
| Body Medium | 16px | 510 | 1.50 | normal | 导航、标签 |
| Small | 15px | 400 | 1.60 | -0.165px | 次要正文 |
| Caption | 13px | 400-510 | 1.50 | -0.13px | 元数据、时间戳 |
| Label | 12px | 400-590 | 1.40 | normal | 按钮、徽章 |
| Overline | 11px | 510 | 1.40 | normal | 分类标签 |
| Stat Display | 48-72px | 700 | 1.00 | -0.5px | 关键数字（ClickHouse 风格） |

### 关键原则

- **510 是签名字重**: Linear 的独特字重（介于 400 和 500 之间），用于强调和导航
- **字号越大，tracking 越紧**: 72px 时 -1.584px，48px 时 -1.056px，32px 时 -0.704px
- **小于 24px 不再收紧**: 正文和标签用 normal tracking
- **关键数字突出**: 用 `text-4xl font-bold tracking-tight` 显示统计数字

---

## 4. Spacing System

### 基础单位: 8px

| Token | Value | 用途 |
|-------|-------|------|
| `px-1` | 4px | 微调 |
| `px-2` | 8px | 紧凑间距 |
| `px-3` | 12px | 小按钮内距 |
| `px-4` | 16px | 标准间距 |
| `px-5` | 20px | 中等间距 |
| `px-6` | 24px | 页面水平 |
| `px-8` | 32px | 大区块 |
| `space-y-8` | 32px | 区块间距 |
| `mb-6` | 24px | 底部间距 |

### Border Radius Scale（融合 Linear + ClickHouse）

| Scale | Value | 用途 |
|-------|-------|------|
| Micro | 2px | 标签、徽章 |
| Small | 4px | 按钮、输入框 |
| Standard | 6px | 功能元素 |
| Card | 8px | 卡片、容器 |
| Panel | 12px | 大面板 |
| Pill | 9999px | 状态标签、胶囊按钮 |

---

## 5. Component Styling

### 按钮系统（Linear 风格）

**主按钮**
```html
class="px-4 py-2 text-sm font-medium rounded-md
       bg-blue-600 hover:bg-blue-700 text-white
       shadow-sm transition-colors"
```

**Ghost 按钮（默认）**
```html
class="px-4 py-2 text-sm font-medium rounded-md
       bg-white/5 hover:bg-white/10 text-gray-200
       border border-white/10 transition-colors"
```
暗色背景用 `rgba(255,255,255,0.02)` → `rgba(255,255,255,0.05)` 透明度层级

**图标按钮（圆形）**
```html
class="p-2 rounded-full bg-white/5 hover:bg-white/10
       border border-white/10 transition-colors"
```

**胶囊切换**
```html
class="px-4 py-1.5 text-xs font-medium rounded-full
       bg-transparent border border-gray-700
       hover:bg-white/5 transition-colors"
```

### 卡片系统（Linear + ClickHouse 融合）

**标准卡片**
```html
class="bg-white/5 border border-white/10 rounded-lg p-4
       hover:bg-white/8 transition-colors"
```

**透明背景卡片**（ClickHouse 风格）
```html
class="bg-transparent border border-white/10 rounded-lg p-4"
```

**悬浮卡片**
```html
class="bg-white/10 border border-white/15 rounded-lg p-4
       shadow-lg transition-all"
```

### 状态徽章

```html
<!-- Running -->
<span class="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium
            rounded-full bg-emerald-500/20 text-emerald-400">
  <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
  运行中
</span>

<!-- Idle -->
<span class="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium
            rounded-full bg-blue-500/20 text-blue-400">
  <span class="w-1.5 h-1.5 rounded-full bg-blue-400"></span>
  空闲
</span>

<!-- Failed -->
<span class="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium
            rounded-full bg-red-500/20 text-red-400">
  <span class="w-1.5 h-1.5 rounded-full bg-red-400"></span>
  失败
</span>
```

### 输入框

```html
<input type="text" placeholder="搜索..."
  class="w-full bg-transparent border border-white/10 rounded-md px-3 py-2 text-sm
         text-gray-200 placeholder-gray-500
         focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50
         transition-colors">
```

### 表格

```html
<table class="w-full text-sm text-left">
  <thead class="text-xs text-gray-400 uppercase tracking-wider">
    <tr class="border-b border-white/10">
      <th class="px-4 py-3 font-medium">列头</th>
    </tr>
  </thead>
  <tbody class="divide-y divide-white/5">
    <tr class="hover:bg-white/5 transition-colors">
      <td class="px-4 py-3 text-gray-200">内容</td>
    </tr>
  </tbody>
</table>
```

### 导航栏

```html
<nav class="sticky top-0 z-40 bg-[#0f1011]/80 backdrop-blur-md
           border-b border-white/5">
  <!-- 链接 -->
  <a href="/page" class="nav-link text-sm font-medium text-gray-400
                        hover:text-white transition-colors">
    文字
  </a>
  <!-- 激活态 -->
  <a href="/page" class="nav-link text-sm font-medium text-white
                        bg-white/10 rounded-md px-3 py-1.5">
    文字
  </a>
</nav>
```

### 统计数字（ClickHouse 风格）

```html
<div class="stat-card">
  <span class="text-5xl font-bold tracking-tight text-white">2,847</span>
  <span class="text-sm text-gray-400 mt-2">采集项目总数</span>
</div>
```

### 模态框

```html
<!-- Overlay -->
<div class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50"></div>
<!-- Dialog -->
<div class="fixed inset-0 z-50 flex items-center justify-center p-4">
  <div class="bg-[#191a1b] border border-white/10 rounded-xl shadow-2xl
              max-w-lg w-full max-h-[90vh] overflow-y-auto">
  </div>
</div>
```

### Toast 通知

```html
<div class="fixed bottom-4 right-4 z-50
            bg-[#191a1b] border border-white/10 rounded-lg shadow-2xl
            px-4 py-3 flex items-center gap-3">
  <!-- Success -->
  <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
  <span class="text-sm text-gray-200">操作成功</span>
</div>
```

---

## 6. Depth & Elevation

### 层级系统（Linear 风格）

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat | 无阴影，`#0f1011` bg | 页面背景 |
| Surface | `bg-white/5` + `border-white/10` | 卡片、输入框 |
| Elevated | `bg-white/8` + `border-white/15` + 微弱阴影 | 悬浮态 |
| Overlay | 多层阴影堆叠 | Popover、Dropdown |
| Dialog | `bg-[#191a1b]` + 粗边框 | 模态框 |
| Inset | `inset shadow` | 凹陷面板（点击态） |

### 阴影策略

暗色表面上阴影几乎不可见，**边框透明度**比阴影更有效：
- 用 `border-white/10` 而非阴影表示"容器"
- 用 `bg-white/5` → `bg-white/10` 的亮度递增表示层级
- 必要时使用 inset shadow: `inset 0 2px 4px rgba(0,0,0,0.3)`

### 边框策略（Linear 核心原则）

- **永远不用实色暗边框**: 在暗色背景上用 `rgba(255,255,255,0.05)` → `rgba(255,255,255,0.12)`
- **默认**: `border-white/5` (几乎看不见)
- **标准**: `border-white/10` (卡片、输入框)
- **强调**: `border-white/15` (选中态)

---

## 6.1 Interactions & Motion（Linear 微交互）

### 动效哲学
**微妙克制** — 动效是反馈，不是装饰。所有动画服务于状态切换的清晰感知。

### 核心原则
- **Fast by default**: 默认 `150ms`，hover/focus `100ms`，modal `200ms`
- **Ease-out dominant**: 进入动画用 `ease-out`，离开用 `ease-in`
- **Scale minimal**: modal/dropdown 进入 `scale(0.96)→scale(1)`，非大幅弹跳
- **No bounce**: 禁止弹簧/弹性动画，保持 Linear 的专业克制感

### 时长层级

| 场景 | 时长 | 缓动 |
|------|------|------|
| Hover/Focus 状态 | 100ms | ease-out |
| 颜色/透明度切换 | 150ms | ease-out |
| Dropdown/Popover 展开 | 150ms | ease-out |
| Modal/Dialog 打开 | 200ms | ease-out (scale 0.96→1) |
| Sidebar 折叠/展开 | 200ms | ease-in-out |
| Toast 滑入 | 250ms | ease-out (translateY) |
| 页面切换 | 0ms | 无动画（防止阅读中断） |

### CSS 示例

```html
<!-- Hover: 背景亮度 + 边框增强 -->
<button class="transition-colors duration-100 hover:bg-white/10">

<!-- Dropdown: scale + opacity -->
<div class="origin-top-right transition-all duration-150 ease-out
            scale-95 opacity-0 scale-100 opacity-100">

<!-- Modal: scale + backdrop -->
<div class="transition-all duration-200 ease-out scale-96 → scale-100">
<div class="transition-opacity duration-200 bg-black/80 → bg-black/60">

<!-- Toast: translateY 滑入 -->
<div class="transition-all duration-250 ease-out translate-y-2 → translate-y-0">
```

### 可点击元素状态

| State | 反馈 |
|-------|------|
| Hover | `bg-white/5 → bg-white/10`，100ms |
| Active/Pressed | `scale(0.98)`，50ms |
| Focus | `ring-2 ring-blue-500/50`，即时 |
| Disabled | `opacity-40`，禁止 cursor |
| Loading | 替换文字为 spinner，禁用交互 |

### 禁止
- ❌ 页面切换过渡动画（阅读打断）
- ❌ 卡片 hover 大幅上浮 + 阴影（眩晕感）
- ❌ 加载时骨架屏闪烁动画
- ❌ Bounce / spring / elastic 缓动
- ❌ 超过 250ms 的任何进入动画

---

## 7. Layout Principles

### 页面结构

```
┌──────────────────────────────────────────────────┐
│ Navbar (sticky, blur backdrop, border-bottom)    │
├──────────────────────────────────────────────────┤
│ Page Header                                      │
│   - 页面标题 (text-2xl font-bold tracking-tight) │
│   - 副标题 (text-sm text-gray-400)              │
│   - Action Buttons (右侧对齐)                    │
├──────────────────────────────────────────────────┤
│ Stats Bar (ClickHouse 风格)                      │
│   [ 2,847 项目 ] [ 128 运行中 ] [ 12 失败 ]     │
│   oversized numbers, minimal labels             │
├──────────────────────────────────────────────────┤
│ Filters / Toolbar                                │
│   [ Search........ ] [ Filter▾ ] [ ⚡ 执行 ]    │
│   bg-white/5 border-white/10 rounded-md         │
├──────────────────────────────────────────────────┤
│ Content Area                                     │
│   - Table / Grid / Empty State                  │
│   - Pagination                                   │
└──────────────────────────────────────────────────┘
```

### 容器宽度
- 内容区: `max-w-7xl mx-auto px-4 sm:px-6 lg:px-8`
- 全宽: `w-full`
- 窄表单: `max-w-xl mx-auto`

### 响应式断点

| Breakpoint | Width | 策略 |
|------------|-------|------|
| Mobile | <640px | 单栏、统计数字缩小 |
| Tablet | 640-768px | 双栏网格 |
| Desktop | 768-1024px | 全功能 |
| Wide | >1280px | 最大宽度约束 |

---

## 6.2 Command Palette（Linear Cmd+K 模式）

### 触发与布局
```html
<!-- 遮罩 -->
<div class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50">
  <!-- 输入框 -->
  <div class="absolute top-[20vh] left-1/2 -translate-x-1/2 w-full max-w-xl
              bg-[#191a1b] border border-white/15 rounded-xl shadow-2xl overflow-hidden">
    <input type="text" placeholder="Search or type a command..."
      class="w-full bg-transparent px-4 py-3.5 text-base text-white
             placeholder-gray-500 outline-none border-b border-white/5">
    <!-- 结果列表 -->
    <div class="max-h-80 overflow-y-auto py-2">
      <!-- Group: Recent -->
      <div class="px-3 py-1.5 text-xs font-medium text-gray-500 uppercase tracking-wider">Recent</div>
      <div class="px-3 py-2 text-sm text-gray-200 hover:bg-white/5 cursor-pointer">
        Dashboard
      </div>
      <!-- Group: Actions -->
      <div class="px-3 py-1.5 text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</div>
      <div class="px-3 py-2 text-sm text-gray-200 hover:bg-white/5 cursor-pointer flex items-center gap-2">
        <span class="text-gray-400">⌘</span> 触发采集
      </div>
    </div>
    <!-- 底部快捷键提示 -->
    <div class="px-4 py-2 border-t border-white/5 flex items-center gap-4 text-xs text-gray-500">
      <span><kbd class="px-1.5 py-0.5 bg-white/10 rounded text-gray-400">↑↓</kbd> 导航</span>
      <span><kbd class="px-1.5 py-0.5 bg-white/10 rounded text-gray-400">↵</kbd> 确认</span>
      <span><kbd class="px-1.5 py-0.5 bg-white/10 rounded text-gray-400">Esc</kbd> 关闭</span>
    </div>
  </div>
</div>
```

### 交互规范
- **↑↓ 键**: 列表内上下导航
- **Enter**: 确认选择
- **Escape**: 关闭
- **输入过滤**: 实时搜索，200ms 防抖
- **空状态**: 显示"No results for 'xxx'"

### 数据模型（Entity System — Linear Issue 模式）

Linear 以 Issue 为核心抽象。参照本项目，数据实体抽象：

| Entity | Linear 对应 | 本项目实体 |
|--------|------------|-----------|
| Issue | 招标/采集项目 | `TenderInfo` |
| Project | 采集任务集 | `CollectionTask` |
| Team | 站点/采集源 | `CrawlerSource` (ccgp/cqggzy) |
| Cycle | 采集周期 | `ScheduleRun` |
| View | 视图预设 | `Preset` |

### Entity 卡片（ClickHouse 表格行升级版）

```html
<!-- Entity 行：紧凑，信息密度高 -->
<div class="group flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors duration-100">
  <!-- 状态指示点 -->
  <span class="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0"></span>
  <!-- 标题 + 标签 -->
  <div class="flex-1 min-w-0">
    <div class="text-sm font-medium text-gray-200 truncate">某单位智慧城市建设项目采购公告</div>
    <div class="flex items-center gap-2 mt-0.5">
      <span class="text-xs text-gray-500">ccgp-chongqing.gov.cn</span>
      <span class="px-1.5 py-0.5 text-xs rounded bg-blue-500/20 text-blue-400">采购公告</span>
    </div>
  </div>
  <!-- 元数据 -->
  <div class="text-right flex-shrink-0">
    <div class="text-xs text-gray-400">2026-04-15</div>
    <div class="text-xs text-gray-500">预算: ¥520万</div>
  </div>
  <!-- 快捷操作（hover 显示） -->
  <div class="opacity-0 group-hover:opacity-100 transition-opacity duration-100 flex items-center gap-1">
    <button class="p-1.5 rounded hover:bg-white/10 text-gray-400 hover:text-white">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>
    </button>
  </div>
</div>
```

---

## 6.3 Sidebar Navigation（Linear 多级导航）

### 结构规范

```html
<aside class="w-56 bg-[#0f1011] border-r border-white/5 flex flex-col h-full">
  <!-- Logo / Branding -->
  <div class="px-4 py-4 border-b border-white/5">
    <span class="text-base font-semibold tracking-tight text-white">Tender Scraper</span>
  </div>
  
  <!-- Primary Nav -->
  <nav class="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
    <!-- Nav Item -->
    <a href="/" class="group flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm
                   text-gray-400 hover:text-white hover:bg-white/5 transition-colors duration-100">
      <svg class="w-4 h-4 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>
      Dashboard
    </a>
    
    <!-- 激活态 Nav Item -->
    <a href="/data" class="group flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm
                   bg-white/8 text-white font-medium">
      <svg class="w-4 h-4 opacity-80" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7c0-2-1-3-3-3H7C5 4 4 5 4 7z"/></svg>
      采集内容
    </a>
    
    <!-- Separator -->
    <div class="h-px bg-white/5 my-2"></div>
    
    <!-- Section Label -->
    <div class="px-2.5 py-1.5 text-xs font-medium text-gray-600 uppercase tracking-wider">数据</div>
    
    <a href="/favorites" class="group flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm
                   text-gray-400 hover:text-white hover:bg-white/5 transition-colors duration-100">
      收藏夹
      <span class="ml-auto text-xs text-gray-600 group-hover:text-gray-400">253</span>
    </a>
    
    <a href="/analytics" class="group flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm
                   text-gray-400 hover:text-white hover:bg-white/5 transition-colors duration-100">
      数据分析
    </a>
    
    <!-- Collapsible Group -->
    <button class="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm
                   text-gray-500 hover:text-gray-300 transition-colors duration-100"
            onclick="toggleSection('settings')">
      <svg class="w-3.5 h-3.5 transition-transform duration-200" id="settings-arrow" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
      <span class="text-xs uppercase tracking-wider font-medium">设置</span>
    </button>
    <div id="settings-section" class="ml-4 space-y-0.5 hidden">
      <a href="/settings" class="block px-2.5 py-1.5 rounded text-xs text-gray-500 hover:text-gray-300">通用设置</a>
      <a href="/settings/sources" class="block px-2.5 py-1.5 rounded text-xs text-gray-500 hover:text-gray-300">采集源</a>
    </div>
  </nav>
  
  <!-- Bottom: Status / User -->
  <div class="px-3 py-3 border-t border-white/5">
    <div class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/5 cursor-pointer transition-colors duration-100">
      <div class="w-6 h-6 rounded-full bg-blue-600 flex items-center justify-center text-xs font-medium text-white">L</div>
      <div class="flex-1 min-w-0">
        <div class="text-xs font-medium text-gray-300 truncate">lewellyn</div>
        <div class="text-xs text-gray-600">Admin</div>
      </div>
    </div>
  </div>
</aside>
```

### 关键规范
- **宽度**: 固定 `14rem` (224px)，不可拖拽调整
- **Hover**: `bg-white/5`，100ms
- **激活**: `bg-white/8` + `text-white` + 左 border-left 高亮
- **分组标题**: `text-xs uppercase tracking-wider text-gray-600`，不可点击
- **Badge**: 显示计数（右对齐，hover 时变色）

---

## 6.4 Data Visualization（ClickHouse 密度优先）

### Bar Chart（ClickHouse 风格 — 数字即主角）

```html
<!-- ClickHouse metric bar: 标签 + 数字 + 进度条 -->
<div class="space-y-4">
  <!-- 单项 bar -->
  <div>
    <div class="flex items-center justify-between mb-1.5">
      <span class="text-xs text-gray-400">采购公告</span>
      <span class="text-sm font-semibold text-white">1,284</span>
    </div>
    <div class="h-1.5 bg-white/5 rounded-full overflow-hidden">
      <div class="h-full bg-blue-500/70 rounded-full" style="width: 72%"></div>
    </div>
  </div>
  <!-- 多项对比 bar（同类数据等宽对比） -->
  <div class="space-y-3">
    <div class="flex items-center gap-3">
      <span class="w-20 text-xs text-gray-400 truncate">采购意向</span>
      <div class="flex-1 h-5 bg-white/5 rounded relative overflow-hidden">
        <div class="h-full bg-emerald-500/60 rounded-r" style="width: 45%"></div>
        <span class="absolute inset-0 flex items-center justify-end pr-2 text-xs font-medium text-white/80">45%</span>
      </div>
    </div>
  </div>
</div>
```

### Stat Card（ClickHouse 超大数字）

```html
<div class="bg-white/5 border border-white/10 rounded-lg p-5">
  <div class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">采集项目总数</div>
  <div class="text-5xl font-bold tracking-tight text-white">2,847</div>
  <div class="flex items-center gap-1.5 mt-2">
    <span class="text-xs text-emerald-400">↑ 12.3%</span>
    <span class="text-xs text-gray-500">较上周</span>
  </div>
</div>
```

### Sparkline（迷你趋势线）

```html
<!-- SVG inline sparkline，宽度 80px -->
<svg class="w-20 h-6" viewBox="0 0 80 24" fill="none">
  <polyline points="0,20 10,16 20,18 30,10 40,12 50,6 60,8 70,4 80,2"
            stroke="#10b981" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
```

### 趋势指示

| 趋势 | 颜色 | 示例 |
|------|------|------|
| 正向增长 | `text-emerald-400` | `↑ 12.3%` |
| 负向下降 | `text-red-400` | `↓ 3.1%` |
| 持平 | `text-gray-400` | `→ 0%` |
| 警告 | `text-amber-400` | `⚠ 即将过期` |

---

## 6.5 Keyboard Shortcuts（效率优先）

### 全局快捷键

| 快捷键 | 功能 | 触发场景 |
|--------|------|---------|
| `⌘ K` / `Ctrl K` | 打开命令面板 | 全局 |
| `G then D` | 跳转 Dashboard | 全局 |
| `G then A` | 跳转 Analytics | 全局 |
| `C` | 快速触发采集 | Dashboard |
| `R` | 刷新当前数据 | 全局 |
| `/` | 聚焦搜索框 | 数据列表页 |
| `Esc` | 关闭模态/面板 | 全局 |
| `?` | 显示快捷键列表 | 全局 |

### 列表操作

| 快捷键 | 功能 |
|--------|------|
| `J` / `↓` | 下移选中项 |
| `K` / `↑` | 上移选中项 |
| `O` / `Enter` | 打开选中详情 |
| `F` | 收藏/取消收藏 |
| `D` | 打开详情页 |
| `N` | 新建采集任务 |

### 命令面板操作

```javascript
// 键盘监听逻辑示例
document.addEventListener('keydown', (e) => {
  // Cmd+K / Ctrl+K → 打开命令面板
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    toggleCommandPalette(true);
  }
  // Esc → 关闭
  if (e.key === 'Escape') {
    toggleCommandPalette(false);
    closeAllModals();
  }
  // G + D → Dashboard
  if (e.key === 'd' && _lastKey === 'g') {
    window.location.href = '/';
  }
  // / → 聚焦搜索
  if (e.key === '/' && !isInputFocused()) {
    e.preventDefault();
    document.querySelector('[data-search-input]')?.focus();
  }
});
```

### 快捷键提示规则
- **所有可点击元素**：hover 时显示 `title="... (快捷键: K)"`
- **模态框**：底部显示快捷键列表（与 Command Palette 保持一致）
- **帮助面板**：按 `?` 显示全量快捷键覆盖图

### ✅ DO

1. **使用 Tailwind 原生类**: 所有样式通过 Tailwind CSS 类实现，不写自定义 CSS
2. **暗色优先**: 所有颜色同时提供 light/dark 版本
3. **边框透明度**: 用 `border-white/10` 而非实色边框
4. **状态用颜色**: Running=绿, Failed=红, Idle=蓝, Disabled=灰
5. **数字突出**: 关键数字用 `text-4xl+ font-bold tracking-tight`
6. **空状态要提示**: 表格为空时显示空状态文案
7. **Loading 要明显**: 骨架屏优于空白，spinner 优于无反馈
8. **操作要确认**: 删除等危险操作必须二次确认
9. **动效克制**: Hover 100ms，Modal 200ms，scale 幅度 ≤ 0.04
10. **键盘优先**: 常用操作提供快捷键（Cmd+K, G+D, C 等）
11. **Entity 行**: 列表优先使用 Entity 卡片模式（非纯表格）
12. **数据可视化**: 趋势数字 + Bar chart 结合，ClickHouse 密度优先

### ❌ DON'T

1. **不要硬编码颜色**: 用 Tailwind 类而非 `#fff` / `#000`
2. **不要实色暗边框**: 在暗背景上永远用 `rgba(255,255,255,0.XX)`
3. **不要过度阴影**: 暗色表面阴影几乎不可见，用边框代替
4. **不要纯白文本**: 正文用 `text-gray-200` 而非 `#ffffff`
5. **不要宽间距**: 页面内容至少 `px-4`，卡片内至少 `p-4`
6. **不要无 Hover**: 所有可点击元素必须有 hover 态
7. **不要无滚动**: 表格外层包 `overflow-x-auto`
8. **不要页面切换动画**: 阅读时禁止过渡动画打断
9. **不要 Bounce/Spring 缓动**: 只用 ease-out / ease-in
10. **不要超过 250ms 的进入动画**
11. **不要隐藏快捷键**: 所有关键操作 hover 时显示快捷键提示

---

## 9. Agent Prompt Guide

### 常用 Tailwind 快捷类

```
颜色:
  primary       → blue-600 / hover:blue-700
  primary-dark → indigo-500 (#5e6ad2)
  success       → emerald-500 (#10b981)
  warning       → orange-500
  danger        → red-500
  bg-base       → gray-900 (light) / #0f1011 (dark)
  bg-panel      → gray-800 (light) / #191a1b (dark)
  text-main     → gray-900 (light) / gray-100 (dark)
  text-sub      → gray-500 (light) / gray-400 (dark)
  border-subtle → border-white/5 (dark) / border-gray-100 (light)
  border-std    → border-white/10 (dark) / border-gray-200 (light)

组件:
  card-dark     → bg-white/5 border border-white/10 rounded-lg
  card-elevated → bg-white/8 border border-white/15 rounded-lg
  btn-primary   → px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 rounded-md
  btn-ghost     → px-4 py-2 text-sm font-medium bg-white/5 hover:bg-white/10 border border-white/10 rounded-md
  input-dark    → bg-transparent border border-white/10 rounded-md px-3 py-2
  badge-running → inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded-full bg-emerald-500/20 text-emerald-400
  badge-failed  → inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded-full bg-red-500/20 text-red-400
  badge-idle    → inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded-full bg-blue-500/20 text-blue-400
  stat-number   → text-5xl font-bold tracking-tight
```

### 快速生成模板

```markdown
# 生成新页面模板
基于本 DESIGN.md，为 tender-scraper 创建 [页面名称] 页面：
- 使用 Tailwind CSS（dark mode 支持）
- 融合 Linear 暗色台风格 + ClickHouse 数据密度
- 包含 Page Header (大标题 + 副标题) + Stats Bar + Table + Filters
- 统计数字用 oversized 样式 (text-5xl font-bold)
- 卡片用 bg-white/5 border border-white/10
- 状态徽章用圆点 + 颜色组合
- 移动端适配

# 生成组件
基于本 DESIGN.md，为 tender-scraper 创建 [组件名称] 组件：
- 使用 Tailwind CSS
- 支持 light/dark mode（用 dark: 前缀）
- 融合 Linear 的边框透明度和层级系统
- 包含所有状态 (default/hover/active/disabled/loading)
```

---

## 附录：页面清单

| 路由 | 页面 | 核心组件 |
|------|------|---------|
| `/` | Dashboard | 统计卡片 + 快捷入口 |
| `/data` | 采集内容 | Entity 列表 + 筛选 + 批量操作 |
| `/favorites` | 收藏 | Entity 列表 + 快速操作 |
| `/analytics` | 数据分析 | Bar Chart + Stat Display + Trend |
| `/nl-query` | 智能查询 | Command Palette + 结果 |
| `/qualifications` | 资质管理 | 表格 + 上传弹窗 |
| `/logs` | 日志 | 紧凑列表 + 时间戳 |
| `/settings` | 设置 | 表单 + 分组设置 |
| `/tasks` | 任务管理 | Entity 卡片 + Schedule Cycle |
| `/documents/upload` | → 重定向 /qualifications | — |
| `/cmd` | 命令面板 | Cmd+K 浮层 + 快捷命令 |

---

## 附录：设计变更日志

| 日期 | 变更 |
|------|------|
| 2026-04-16 | 新增 6.1 动效与微交互规范（Linear 克制原则） |
| 2026-04-16 | 新增 6.2 Command Palette + Entity Model（Linear Issue 模式） |
| 2026-04-16 | 新增 6.3 Sidebar Navigation（多级可折叠结构） |
| 2026-04-16 | 新增 6.4 Data Visualization（ClickHouse 密度优先 Bar Chart） |
| 2026-04-16 | 新增 6.5 Keyboard Shortcuts（全局 + 列表操作） |

---

*Last updated: 2026-04-16 — Linear(微交互+命令面板) + ClickHouse(数据密度) 深度融合*
