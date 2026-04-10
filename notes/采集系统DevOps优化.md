# 采集系统 DevOps 优化方案

> 项目: `tender-scraper` (招投标采集系统)
> 分析时间: 2026-04-07
> 负责人: DevOps 自动化工程师 (Subagent)

---

## 📋 概览

| 模块 | 当前状态 | 优化优先级 |
|------|----------|-----------|
| Docker 容器化 | ⚠️ 基础但简陋 | 🔴 高 |
| CI/CD 流水线 | ❌ 不完整 | 🔴 高 |
| 监控与告警 | ❌ 无 | 🔴 高 |
| 日志收集分析 | ⚠️ 本地文件 | 🟡 中 |
| 定时任务调度 | ⚠️ APScheduler 单机 | 🟡 中 |

---

## 1. 🐳 Docker 容器化方案

### 当前问题
- 基础 Dockerfile 基于 `playwright/python` 镜像（>3GB）
- 无多阶段构建，镜像体积大
- 无 docker-compose，生产部署依赖手动操作
- 缺少 healthcheck 配置
- Playwright 浏览器未持久化，每次启动重装

### 优化方案

#### 1.1 多阶段构建 Dockerfile

```dockerfile
# === Stage 1: Builder ===
FROM python:3.12-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# === Stage 2: Playwright ===
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy AS playwright-base

WORKDIR /app
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# 预装浏览器（持久化层）
RUN playwright install chromium --with-deps

# === Stage 3: Production ===
FROM python:3.12-slim AS production

WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    dumb-init \
    tini \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖和代码
COPY --from=playwright-base /root/.local /root/.local
COPY --from=playwright-base /ms-playwright /ms-playwright
ENV PATH=/root/.local/bin:$PATH
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY requirements.txt .
COPY app/ ./app/
COPY config/ ./config/
COPY main.py web_server.py ./
COPY templates/ ./templates/
COPY --chown=nonroot:nonroot output/ ./output/
RUN mkdir -p logs && chown -R nonroot:nonroot .

# 非 root 用户运行
USER nonroot

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/n8n/health', timeout=5)"

# 信号处理
ENTRYPOINT ["tini", "--"]
CMD ["python", "web_server.py"]
```

#### 1.2 docker-compose 生产配置

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  scraper-api:
    build:
      context: .
      dockerfile: Dockerfile
      target: production
    container_name: tender-scraper-api
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - ENV=production
      - LOG_LEVEL=INFO
      - DATABASE_URL=sqlite:///data/tender_scraper.db
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./output:/app/output
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8000/api/n8n/health', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '0.5'
          memory: 1G
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

  # Redis 用于分布式锁和缓存
  redis:
    image: redis:7-alpine
    container_name: tender-scraper-redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s
      timeout: 5s
      retries: 3

  # Celery Worker 用于异步任务
  scraper-worker:
    build:
      context: .
      dockerfile: Dockerfile
      target: production
    container_name: tender-scraper-worker
    restart: unless-stopped
    command: celery -A app.tasks worker --loglevel=info
    environment:
      - ENV=production
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G

volumes:
  redis-data:
```

#### 1.3 镜像优化效果预估

| 指标 | 当前 | 优化后 | 提升 |
|------|------|--------|------|
| 镜像体积 | ~3.5GB | ~1.8GB | **-49%** |
| 构建时间 | ~10min | ~6min | **-40%** |
| 冷启动时间 | ~45s | ~15s | **-67%** |

---

## 2. 🔄 CI/CD 流水线设计

### 当前问题
- `.github/` 目录存在但无有效 workflow 文件
- 缺少自动化测试
- 无版本发布流程
- 部署依赖手动操作

### 优化方案

#### 2.1 GitHub Actions 工作流

```yaml
# .github/workflows/ci-cd.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
  release:
    types: [published]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  # === Stage 1: Code Quality ===
  lint:
    name: Lint & Format Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      
      - name: Install dependencies
        run: pip install ruff black flake8 mypy
      
      - name: Run Ruff
        run: ruff check .
      
      - name: Run Black check
        run: black --check .
      
      - name: Run MyPy
        run: mypy app/ --ignore-missing-imports

  # === Stage 2: Unit Tests ===
  test:
    name: Unit Tests
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run pytest
        run: pytest tests/ -v --cov=app --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

  # === Stage 3: Build & Push ===
  build:
    name: Build & Push Docker Image
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name != 'pull_request'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Log in to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=sha,prefix={{branch}}-
            type=raw,value=latest,enable={{is_default_branch}}
            type=semver,pattern={{version}}
      
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  # === Stage 4: Deploy to Production ===
  deploy:
    name: Deploy to Production
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main'
    environment:
      name: production
      url: https://scraper.example.com
    steps:
      - name: Deploy to server
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PROD_HOST }}
          username: ${{ secrets.PROD_USER }}
          key: ${{ secrets.PROD_SSH_KEY }}
          script: |
            cd /opt/tender-scraper
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d
            docker image prune -f

  # === Stage 5: Security Scan ===
  security:
    name: Security Scan
    runs-on: ubuntu-latest
    needs: build
    permissions:
      security-events: write
    steps:
      - uses: actions/checkout@v4
      
      - name: Run Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: '${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}'
          format: 'sarif'
          output: 'trivy-results.sarif'
      
      - name: Upload scan results
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: 'trivy-results.sarif'
```

#### 2.2 部署流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    CI/CD Pipeline Flow                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Push/PR     Lint & Format    Unit Tests    Build Image     │
│  ────────    ────────────    ──────────    ────────────     │
│     │              │              │              │            │
│     ▼              ▼              ▼              ▼            │
│  ┌──────┐    ┌──────────┐   ┌──────────┐  ┌───────────┐       │
│  │ code │───▶│ ruff     │──▶│ pytest   │──▶│ docker    │       │
│  │      │    │ black    │   │ +cov     │  │ build&push│       │
│  └──────┘    └──────────┘   └──────────┘  └─────┬─────┘       │
│                                                  │             │
│                                        ┌─────────▼────────┐   │
│                                        │ Security Scan    │   │
│                                        │ (Trivy)          │   │
│                                        └─────────┬────────┘   │
│                                                  │             │
│                                        ┌─────────▼────────┐   │
│                                        │ Deploy to Prod   │   │
│                                        │ (SSH + Compose)  │   │
│                                        └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 📊 监控与告警系统

### 当前问题
- 无监控体系，无法感知系统健康状态
- 无告警机制，问题被动发现
- 无性能指标收集
- 日志分散在多个文件

### 优化方案

#### 3.1 监控架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Monitoring Stack                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌──────────────┐     ┌──────────────┐     ┌────────────┐ │
│   │ Prometheus   │◀────│ Node Exporter │     │  Grafana   │ │
│   │ (Metrics)    │     │ (Host)        │     │  (Dash)    │ │
│   └──────┬───────┘     └──────────────┘     └─────┬──────┘ │
│          │                                          │         │
│          │            ┌──────────────┐              │         │
│          └───────────▶│ Alertmanager  │◀─────────────┘         │
│                       │ (Alerting)    │                        │
│                       └───────┬───────┘                        │
│                               │                                │
│                       ┌───────▼───────┐                        │
│                       │ Email/Slack/  │                        │
│                       │ Telegram      │                        │
│                       └───────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

#### 3.2 Docker Compose 监控栈

```yaml
# docker-compose.monitoring.yml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=15d'

  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    restart: unless-stopped
    ports:
      - "9100:9100"
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/dashboards:/etc/grafana/provisioning/dashboards
    depends_on:
      - prometheus

  alertmanager:
    image: prom/alertmanager:latest
    container_name: alertmanager
    restart: unless-stopped
    ports:
      - "9093:9093"
    volumes:
      - ./monitoring/alertmanager.yml:/etc/alertmanager/alertmanager.yml
    command:
      - '--config.file=/etc/alertmanager/alertmanager.yml'
      - '--storage.path=/alertmanager'

volumes:
  prometheus-data:
  grafana-data:
```

#### 3.3 关键告警规则

```yaml
# monitoring/alerts.yml
groups:
  - name: tender-scraper
    rules:
      # 服务不可用
      - alert: ScraperAPIDown
        expr: up{job="tender-scraper"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "采集系统 API 不可用"
          description: "tender-scraper API 已经宕机超过 1 分钟"

      # 内存使用过高
      - alert: HighMemoryUsage
        expr: (container_memory_usage_bytes{name="tender-scraper-api"} / container_spec_memory_limit_bytes{name="tender-scraper-api"}) > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "内存使用率过高"
          description: "容器内存使用率超过 85%"

      # CPU 使用过高
      - alert: HighCPUUsage
        expr: rate(container_cpu_usage_seconds_total{name="tender-scraper-api"}[5m]) > 1.8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "CPU 使用率过高"
          description: "容器 CPU 使用率持续过高，可能需要扩展"

      # 采集任务失败
      - alert: CollectionTaskFailed
        expr: scraper_tasks_failed_total > scraper_tasks_success_total * 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "采集任务失败率过高"
          description: "采集任务失败率超过 10%"

      # 磁盘空间不足
      - alert: LowDiskSpace
        expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) < 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "磁盘空间不足"
          description: "根分区可用空间低于 10%"

      # 响应时间过长
      - alert: HighResponseTime
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="tender-scraper"}[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API 响应时间过长"
          description: "P95 响应时间超过 2 秒"
```

#### 3.4 应用指标暴露

```python
# app/core/metrics.py
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# 定义指标
scrape_tasks_total = Counter('scrape_tasks_total', 'Total scrape tasks', ['status'])
scrape_duration_seconds = Histogram('scrape_duration_seconds', 'Scrape duration')
items_collected = Gauge('items_collected', 'Number of items collected')
http_requests_total = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
active_browsers = Gauge('active_browsers', 'Number of active browser instances')

# 在应用启动时暴露指标
start_http_server(9091)
```

---

## 4. 📝 日志收集与分析

### 当前问题
- 日志仅写入本地文件 `logs/scraper.log`
- 无集中式日志收集
- 日志格式不统一，难以检索
- 无结构化日志

### 优化方案

#### 4.1 ELK/EFK 日志架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Log Collection Flow                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   Container     JSON Log       Filebeat      Elasticsearch   │
│  ──────────  ─────────────  ─────────────  ──────────────   │
│     │              │              │              │            │
│     ▼              ▼              ▼              ▼            │
│  ┌──────┐    ┌──────────┐   ┌──────────┐  ┌──────────┐     │
│  │ log  │───▶│ stdout   │──▶│filebeat   │─▶│  index    │     │
│  │uru   │    │ json     │   │           │  │           │     │
│  └──────┘    └──────────┘   └──────────┘  └─────┬──────┘     │
│                                                  │             │
│                                         ┌────────▼────────┐  │
│                                         │    Kibana        │  │
│                                         │  (可视化检索)     │  │
│                                         └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

#### 4.2 结构化日志配置

```python
# config/logging_config.py
from loguru import logger
import sys
import json
from datetime import datetime

class JSONFormatter:
    """结构化 JSON 日志格式化器"""
    
    def __call__(self, message):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": message.record["level"].name,
            "message": message.record["message"],
            "module": message.record["module"],
            "function": message.record["function"],
            "line": message.record["line"],
            "extra": message.record.get("extra", {})
        }
        return json.dumps(log_data) + "\n"

# 配置 Loguru
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    level="INFO"
)
logger.add(
    "logs/scraper.json",
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
    format=JSONFormatter(),
    compression="gz"
)
```

#### 4.3 Docker 日志驱动配置

```yaml
# docker-compose.prod.yml (追加 logging 配置)
services:
  scraper-api:
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "10"
    labels:
      - "scraper.version=3.1"

  # Filebeat sidecar
  filebeat:
    image: docker.elastic.co/beats/filebeat:8.13.0
    container_name: filebeat
    restart: unless-stopped
    user: root
    volumes:
      - ./monitoring/filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    depends_on:
      - scraper-api
```

#### 4.4 Filebeat 配置

```yaml
# monitoring/filebeat.yml
filebeat.inputs:
  - type: container
    paths:
      - /var/lib/docker/containers/*/*.log
    processors:
      - add_kubernetes_metadata:
          host: ${NODE_NAME}
          matchers:
            - logs_path:
                logs_path: "/var/lib/docker/containers/"

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "tender-scraper-%{+yyyy.MM.dd}"

setup.kibana:
  host: "kibana:5601"

setup.ilm.enabled: auto
setup.ilm.rollover_alias: "tender-scraper"
setup.ilm.pattern: "{now/d}-000001"
setup.ilm.policy_name: "tender-scraper-policy"
```

#### 4.5 日志分析常用查询 (Kibana)

| 场景 | 查询 |
|------|------|
| 查找错误 | `level: ERROR` |
| 特定模块错误 | `level: ERROR AND module: cqggzy` |
| 采集性能 | `level: INFO AND message: *采集完成*` |
| 某时间段日志 | `@timestamp:[2026-04-07T00:00:00 TO 2026-04-07T23:59:59]` |
| 高频访问 | `endpoint: /api/projects AND method: GET` |

---

## 5. ⏰ 定时任务调度优化

### 当前问题
- 使用 APScheduler 单机调度
- 无分布式锁，并发部署会重复执行
- 任务状态不可视
- 无重试机制
- 无任务依赖管理

### 优化方案

#### 5.1 Celery + Redis 分布式调度

```python
# app/tasks/collection_tasks.py
from celery import Celery
from celery.schedules import crontab
from loguru import logger

app = Celery('tender_scraper')
app.config_from_object('app.tasks.celery_config')

@app.task(bind=True, max_retries=3, default_retry_delay=300)
def task_collect_tenders(self, source=None):
    """采集任务（带重试）"""
    try:
        logger.info(f"开始采集: {source}")
        # ... 采集逻辑
        return {"status": "success", "count": len(results)}
    except Exception as exc:
        logger.error(f"采集失败: {exc}")
        raise self.retry(exc=exc)

@app.task
def task_generate_report(date=None):
    """生成报表任务"""
    # ... 报表生成逻辑
    pass

# 定时调度配置
app.conf.beat_schedule = {
    'collect-ccgp-every-hour': {
        'task': 'app.tasks.collection_tasks.task_collect_tenders',
        'schedule': crontab(minute=0),  # 每小时整点
        'kwargs': {'source': 'ccgp'},
    },
    'collect-cqggzy-every-30min': {
        'task': 'app.tasks.collection_tasks.task_collect_tenders',
        'schedule': crontab(minute='*/30'),  # 每30分钟
        'kwargs': {'source': 'cqggzy'},
    },
    'generate-daily-report': {
        'task': 'app.tasks.collection_tasks.task_generate_report',
        'schedule': crontab(hour=8, minute=0),  # 每天早上8点
    },
}
```

#### 5.2 调度架构对比

| 特性 | 当前 APScheduler | 优化后 Celery |
|------|------------------|---------------|
| 分布式支持 | ❌ 单机 | ✅ 多节点 |
| 任务持久化 | ❌ 内存 | ✅ Redis |
| 失败重试 | ⚠️ 需手动 | ✅ 自动 |
| 任务监控 | ❌ 无 | ✅ Flower UI |
| 并发执行控制 | ⚠️ 基础 | ✅ 精细 |
| 任务依赖 | ❌ 无 | ✅ chain/group |

#### 5.3 调度时间表建议

| 任务 | 当前频率 | 建议频率 | 理由 |
|------|----------|----------|------|
| 政府采购网采集 | 每次运行 | 每30分钟 | 信息更新频繁 |
| 公共资源交易网 | 每次运行 | 每30分钟 | 同上 |
| 数据库备份 | 无 | 每天凌晨 | 数据安全 |
| 日志清理 | 无 | 每周 | 磁盘空间 |
| 健康检查 | 无 | 每5分钟 | 快速发现问题 |
| 报表生成 | 手动 | 每天8:00 | 工作时间前 |

#### 5.4 任务监控 (Flower)

```yaml
# docker-compose.prod.yml 添加
services:
  flower:
    image: mher/flower:latest
    container_name: tender-scraper-flower
    restart: unless-stopped
    ports:
      - "5555:5555"
    command: celery -A app.tasks worker flower
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
    depends_on:
      redis:
        condition: service_healthy
```

访问 `http://your-server:5555` 查看任务监控界面。

---

## 📈 实施优先级与工作量估算

| 阶段 | 任务 | 工作量 | 优先级 | 预期效果 |
|------|------|--------|--------|----------|
| **Phase 1** | 优化 Dockerfile | 2h | 🔴 高 | 镜像体积-50% |
| **Phase 1** | docker-compose 生产配置 | 3h | 🔴 高 | 一键部署 |
| **Phase 1** | GitHub Actions CI/CD | 4h | 🔴 高 | 自动化发布 |
| **Phase 2** | 监控部署 (Prometheus+Grafana) | 3h | 🔴 高 | 可观测性 |
| **Phase 2** | 告警规则配置 | 2h | 🔴 高 | 问题感知 |
| **Phase 2** | 结构化日志改造 | 3h | 🟡 中 | 问题定位 |
| **Phase 3** | Celery 分布式调度 | 6h | 🟡 中 | 可靠性 |
| **Phase 3** | ELK 日志收集 | 4h | 🟡 中 | 集中日志 |

---

## 🔧 快速落地建议

1. **立即可做**（1天内）：
   - 优化 Dockerfile 多阶段构建
   - 创建 docker-compose.prod.yml
   - 配置 GitHub Actions 基本流程

2. **短期目标**（1周内）：
   - 部署 Prometheus + Grafana
   - 配置基础告警
   - 改造日志为 JSON 格式

3. **中期目标**（2-4周）：
   - 迁移到 Celery 调度
   - 部署 ELK 日志栈
   - 完善 CI/CD 流程

---

*文档版本: v1.0*
*最后更新: 2026-04-07*
