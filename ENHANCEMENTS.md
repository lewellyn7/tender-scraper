# 招投标采集系统 - 增强功能进度

> 项目路径: `/home/lewellyn/tender-scraper`
> API 服务: `http://127.0.0.1:9099`

---

## ✅ 功能清单与进度 (全部完成)

| # | 功能 | 状态 | 完成日期 | 说明 |
|---|------|------|----------|------|
| 1 | 智能匹配算法升级 | ✅ 完成 | 2026-04-04 | TF-IDF + jieba + 同义词 |
| 2 | 实时推送通知 | ✅ 完成 | 2026-04-04 | Telegram Bot + 阈值过滤 |
| 3 | 数据导出增强 | ✅ 完成 | 2026-04-04 | 分段导出 + PDF reportlab |
| 4 | 项目收藏与批注 | ✅ 完成 | 2026-04-04 | SQLite 持久化 |
| 5 | 数据分析面板 | ✅ 完成 | 2026-04-04 | Chart.js 多图表 |
| 6 | 重复项目检测 | ✅ 完成 | 2026-04-04 | TF-IDF 标题相似度 |
| 7 | 快速筛选预设 | ✅ 完成 | 2026-04-04 | CRUD + 默认预设 |
| 8 | 暗黑模式 | ✅ 完成 | 2026-04-04 | Tailwind dark: + 主题切换 |
| 9 | 运行日志查看 | ✅ 完成 | 2026-04-04 | DB 日志 + UI 查看器 |
| 10 | 配置备份/恢复 | ✅ 完成 | 2026-04-04 | JSON 版本历史 |
| 11 | 性能优化 | ✅ 完成 | 2026-04-04 | 分页 + 60s 内存缓存 |
| 12 | UI 界面平滑动画 | ✅ 完成 | 2026-04-04 | 全页动画系统 |
### 12. UI 界面平滑动画

**CSS 动画类:**
- `.anim-card` — 卡片悬停微交互 (translateY + scale + shadow)
- `.anim-btn` — 按钮 ripple 点击反馈
- `.stagger-item` — 列表依次显示 (MutationObserver 驱动)
- `.reveal` — 滚动渐入动画 (IntersectionObserver)
- `.skeleton` — 加载骨架屏 (shimmer 动画)
- `.pulse-soft` — 脉冲动画
- `.spin` — 旋转动画
- `.progress-anim` — 进度条过渡
- `.toast-*` — Toast 通知 (slide-in/out)

**JS 动画函数:**
- `showToast(msg, type, duration)` — 全局 Toast 通知
- `openModal(id) / closeModal(id)` — 模态框弹出/关闭
- 图表数据动画 (IntersectionObserver 触发)
- Alpine.js MutationObserver 监听列表变化，自动添加 stagger 动画
- 页面加载时 scroll reveal + count-up 数字动画

**已应用页面:** dashboard.html, favorites.html, analytics.html, logs.html, settings.html


---

## 新增文件

```
app/
  database/
    __init__.py          # 数据库模块导出
    db.py                # SQLite 数据库 (收藏/批注/预设/日志/备份/重复)
  utils/
    tfidf_matcher.py     # TF-IDF 语义匹配 + 同义词词库
    notifications.py       # Telegram 推送通知
    pdf_generator.py      # PDF 报表生成 (reportlab)
  api/
    routes.py             # 增强版 API 路由 (页面渲染 + REST API)
  templates/
    favorites.html        # 项目收藏页 (Alpine.js)
    analytics.html        # 数据分析面板 (Chart.js)
    logs.html            # 运行日志查看
    settings.html        # 增强设置页 (通知/预设/备份/重复检测 Tab)
    base.html            # 暗黑模式 + 新导航
```

## 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/projects` | GET | 分页项目列表，支持 `use_tfidf=true` TF-IDF 匹配 |
| `/api/project/{url}` | GET | 项目详情 (含收藏/批注状态) |
| `/api/favorites` | GET/POST | 收藏列表/添加收藏 |
| `/api/favorites/{url}` | DELETE/PATCH | 取消收藏/更新状态 |
| `/api/annotations` | GET/POST | 批注列表/添加批注 |
| `/api/presets` | GET/POST | 预设列表/保存预设 |
| `/api/presets/{key}` | DELETE | 删除预设 |
| `/api/duplicates` | GET | 重复项目检测 (TF-IDF 相似度) |
| `/api/analytics` | GET | 数据分析 (趋势/预算/关键词/来源) |
| `/api/logs` | GET/DELETE | 采集日志查看/清理 |
| `/api/config/backup` | POST | 创建配置备份 |
| `/api/config/backups` | GET | 列出备份版本 |
| `/api/config/restore/{id}` | POST | 恢复指定备份 |
| `/api/export/excel` | GET | Excel 导出，支持 `segment_by=date|type` |
| `/api/export/pdf` | GET | PDF 导出 (reportlab) |
| `/api/notifications/config` | GET/POST | 通知配置 |
| `/api/notifications/test` | POST | 测试通知 |
| `/favorites` | GET | 项目收藏页 |
| `/analytics` | GET | 数据分析面板 |
| `/logs` | GET | 运行日志查看 |
| `/settings` | GET | 设置页面 |

## 技术架构

### TF-IDF 语义匹配
- **分词**: `jieba` 中文分词
- **同义词**: 内置同义词词库 (智慧↔智能↔数字化↔信息化等)
- **相似度**: 余弦相似度，阈值 0.15
- **API参数**: `use_tfidf=true` 启用

### Telegram 通知
- Bot Token + Chat ID 配置
- 最低预算阈值过滤
- 关键词白名单过滤
- 推送阈值 (积累N条后汇总推送)

### PDF 报表
- `reportlab` 生成 A4 PDF
- 按类型分组 + 统计摘要
- 分段导出 (按日期/类型)

### 数据分析 (Chart.js)
- 采购趋势 (折线图)
- 预算分布 (环形图)
- 来源分布 (水平条形)
- 关键词热度 (标签云)

### 数据库 (SQLite)
- 收藏项目、批注、筛选预设、配置备份、采集日志、重复记录
- 线程安全 `threading.local`
- 自动迁移 (最近20个备份保留)

---

_最后更新: 2026-04-04_
