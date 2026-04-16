# DESIGN.md — 招投标采集系统

> AI Agent 设计系统文档。告诉 AI「这个项目长什么样，应该怎么写 UI」。
> 设计理念融合 Linear（暗色数据台）+ ClickHouse（性能密度）。

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

## 8. Do's and Don'ts

### ✅ DO

1. **使用 Tailwind 原生类**: 所有样式通过 Tailwind CSS 类实现，不写自定义 CSS
2. **暗色优先**: 所有颜色同时提供 light/dark 版本
3. **边框透明度**: 用 `border-white/10` 而非实色边框
4. **状态用颜色**: Running=绿, Failed=红, Idle=蓝, Disabled=灰
5. **数字突出**: 关键数字用 `text-4xl+ font-bold tracking-tight`
6. **空状态要提示**: 表格为空时显示空状态文案
7. **Loading 要明显**: 骨架屏优于空白，spinner 优于无反馈
8. **操作要确认**: 删除等危险操作必须二次确认

### ❌ DON'T

1. **不要硬编码颜色**: 用 Tailwind 类而非 `#fff` / `#000`
2. **不要实色暗边框**: 在暗背景上永远用 `rgba(255,255,255,0.XX)`
3. **不要过度阴影**: 暗色表面阴影几乎不可见，用边框代替
4. **不要纯白文本**: 正文用 `text-gray-200` 而非 `#ffffff`
5. **不要宽间距**: 页面内容至少 `px-4`，卡片内至少 `p-4`
6. **不要无 Hover**: 所有可点击元素必须有 hover 态
7. **不要无滚动**: 表格外层包 `overflow-x-auto`

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
| `/data` | 采集内容 | 数据表格 + 筛选 |
| `/favorites` | 收藏 | 收藏列表 |
| `/analytics` | 数据分析 | 图表 + 趋势 |
| `/nl-query` | 智能查询 | 搜索框 + 结果 |
| `/qualifications` | 资质管理 | 表格 + 上传弹窗 |
| `/logs` | 日志 | 日志列表 |
| `/settings` | 设置 | 表单 |
| `/tasks` | 任务管理 | 统计 + 列表 + 向导 |
| `/documents/upload` | → 重定向 /qualifications | — |

---

*Last updated: 2026-04-16 — 融合 Linear + ClickHouse 设计理念*
