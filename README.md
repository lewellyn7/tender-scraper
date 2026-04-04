# 重庆市公共资源交易采集系统

自动采集重庆市公共资源交易网 (cqggzy.com) 的招投标信息，智能筛选相关项目。

## 功能特点

- ✅ 采集政府采购公告
- ✅ 采集工程招投标信息
- ✅ 关键词智能过滤
- ✅ 自动生成 Excel 报表
- ✅ 反爬虫检测规避

## 安装

```bash
# 克隆项目
git clone <repo-url>
cd tender-scraper

# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
playwright install chromium
```

## 配置

编辑 `config/settings.py` 或创建 `.env` 文件：

```python
# 采集关键词
KEYWORDS = ["智能化", "AI", "人工智能", "智慧", "数字化", ...]

# 排除关键词
EXCLUDE_KEYWORDS = ["流标", "终止", "废标", "中标公告", "成交公告"]

# 浏览器模式
HEADLESS = True  # 生产环境设为 True
```

## 运行

```bash
# 本地运行
source venv/bin/activate
python main.py

# Docker 运行
docker build -t tender-scraper .
docker run --rm -v $(pwd)/output:/app/output tender-scraper
```

## 输出

采集结果保存在 `output/` 目录：

- `chongqing_tender_YYYYMMDD_HHMMSS.xlsx` - Excel 报表
- 包含：项目名称、类型、发布日期、匹配关键词、链接

## 项目结构

```
tender-scraper/
├── app/
│   ├── core/
│   │   └── browser.py      # Playwright 浏览器封装
│   ├── crawlers/
│   │   └── cqggzy_crawler.py  # 重庆市公共资源交易网采集器
│   └── utils/
│       ├── filter.py       # 关键词过滤
│       └── report.py       # 报表生成
├── config/
│   └── settings.py         # 配置文件
├── output/                 # 输出目录
├── main.py                 # 主入口
└── requirements.txt        # 依赖
```

## 更新日志

### 2026-04-03
- 目标网站从 `ccgp-chongqing.gov.cn` (已失效) 切换到 `cqggzy.com`
- 新增 `CQGGZYCrawler` 采集器
- 更新页面选择器适配新网站结构

## License

MIT
