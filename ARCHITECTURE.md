# 招投标采集系统 - 架构文档

## 📁 项目结构

```
tender-scraper/
├── main.py                 # 🎯 采集任务入口
├── web_server.py           # 🌐 Web API 服务
├── requirements.txt        # 📦 Python 依赖
├── .env                    # ⚙️  环境配置
│
├── app/                    # 📂 核心应用
│   ├── api/                # 🔌 API 路由
│   │   ├── routes.py       #    主路由
│   │   └── routes_n8n.py   #    n8n 集成接口
│   │
│   ├── core/               # ⚙️ 核心组件
│   │   ├── browser.py      #    浏览器引擎
│   │   ├── concurrency_scheduler.py  # 并发调度
│   │   ├── permissions.py  #    权限管理
│   │   └── session_memory.py  # 会话记忆
│   │
│   ├── crawlers/           # 🕷️ 爬虫模块
│   │   ├── base.py         #    爬虫基类
│   │   ├── ccgp.py         #    重庆政府采购网
│   │   └── cqggzy.py       #    重庆公共资源交易网
│   │
│   ├── database/           # 💾 数据持久化
│   │   └── db.py
│   │
│   ├── models/             # 📊 数据模型
│   │   └── tender.py
│   │
│   ├── templates/          # 🎨 前端模板
│   │   ├── dashboard.html  #    仪表盘
│   │   ├── content.html    #    采集内容
│   │   ├── data.html       #    数据管理
│   │   ├── favorites.html  #    收藏夹
│   │   ├── analytics.html  #    数据分析
│   │   ├── logs.html       #    日志查看
│   │   ├── settings.html   #    设置页面
│   │   └── partials/       #    组件片段
│   │       └── animations.html  # 3D 动画
│   │
│   └── utils/              # 🛠️ 工具函数
│       ├── filter.py       #    关键词过滤
│       ├── report.py       #    报表生成
│       ├── notifications.py #    通知服务
│       ├── pdf_generator.py #   PDF 生成
│       └── tfidf_matcher.py #  TF-IDF 匹配
│
├── config/                 # 🔧 配置文件
│   ├── settings.py         #    主配置
│   ├── settings.json       #    JSON 配置
│   └── admin_users.json    #    管理员用户
│
├── docs/                   # 📚 文档
│   └── n8n_workflow_example.json  # n8n 工作流示例
│
├── archive/                # 📦 归档（旧版本）
│   └── old_versions/       #    历史版本备份
│
├── output/                 # 📤 输出目录
│   └── latest.json         #    最新采集数据
│
├── .skills/                # 🎯 Agent Skills
│   └── ui-ux-pro-max/      #    UI/UX 技能
│
├── ARCHITECTURE.md         # 📋 本文档
├── ENHANCEMENTS.md         # 🚀 改进记录
└── README.md               # 📖 项目说明
```

## 🔗 模块依赖

```
main.py / web_server.py
    │
    ├── app.crawlers.{ccgp, cqggzy}
    │       └── app.core.browser
    │
    ├── app.utils.{filter, report, ...}
    │
    ├── app.api.routes
    │       └── app.database.db
    │
    └── config.settings
```

## 🌐 API 路由

### 主 API (routes.py)
| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/projects` | GET | 获取项目列表 |
| `/api/project/{url}` | GET | 获取项目详情 |
| `/api/favorites` | GET/POST/DELETE | 收藏管理 |
| `/api/annotations` | GET/POST | 注释管理 |
| `/api/presets` | GET/POST/DELETE | 预设管理 |
| `/api/duplicates` | GET | 查重 |
| `/api/analytics` | GET | 数据分析 |

### n8n API (routes_n8n.py)
| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/n8n/trigger-collection` | POST | 触发采集 |
| `/api/n8n/status/{task_id}` | GET | 查询状态 |
| `/api/n8n/latest` | GET | 获取数据 |
| `/api/n8n/push-to-n8n` | POST | 推送数据 |
| `/api/n8n/callback/{action}` | POST | n8n 回调 |
| `/api/n8n/health` | GET | 健康检查 |

## 🕷️ 爬虫

### ccgp.py - 重庆政府采购网
- **URL**: https://www.ccgp.gov.cn/
- **类别**: 政府采购公告

### cqggzy.py - 重庆公共资源交易网
- **URL**: https://www.cqggzy.com/
- **类别**: 
  - 政府采购 (gov_purchase)
  - 工程建设 (engineering)

## 📊 数据流

```
采集 → 过滤 → 详情采集 → 标准化 → 存储/报表
  ↓       ↓         ↓         ↓
列表页   关键词    详情页    latest.json
                      ↓
                   Excel 报表
```

## 🔐 安全

- Web API 认证: session-based
- 管理后台: 独立用户系统
- n8n webhook: key 认证

## 🚀 部署

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 Web 服务
python web_server.py

# 运行采集
python main.py
```

---
*最后更新: 2026-04-04*
