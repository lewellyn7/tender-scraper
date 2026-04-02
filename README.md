# 重庆市政府采购信息采集系统

自动化采集重庆市政府采购网的采购公告和采购意向，智能筛选智能化、音视频、AI 相关项目。

## 功能特性

- ✅ **真人模拟采集**: 基于 Playwright Stealth，模拟真实用户行为
- ✅ **智能关键词过滤**: 定向筛选 AI、智能化、音视频相关项目
- ✅ **定时自动执行**: 工作日 10:00/14:00/18:00 自动运行
- ✅ **Excel 报表导出**: 自动生成结构化项目清单
- ✅ **防反爬机制**: 随机 UA、请求延迟、指纹伪装

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并修改配置。

### 3. 运行采集

```bash
python main.py
```

## 目录结构

```
tender-scraper/
├── app/
│   ├── core/          # 核心模块 (浏览器)
│   ├── crawlers/      # 采集器实现
│   ├── utils/         # 工具类 (过滤/报表)
│   └── parsers/       # 解析器 (待扩展)
├── config/            # 配置文件
├── output/            # 输出目录
├── logs/              # 日志目录
├── main.py            # 主入口
└── requirements.txt   # 依赖
```

## 定时任务

系统已配置 OpenClaw Cron，工作日自动执行。

## License

MIT
