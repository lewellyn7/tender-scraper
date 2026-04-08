# 部署指南

## 快速启动

```bash
# 1. 复制环境变量模板
cp .env.example .env

# 2. 构建并启动
docker compose up -d

# 3. 查看状态
make status
```

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| Web API | 8000 | 主服务 |
| Prometheus | 9090 | 指标收集 |
| Grafana | 3000 | 可视化监控 |
| Alertmanager | 9093 | 告警管理 |

## 定时采集

调度器 (`scheduler` 容器) 默认每天 **08:00 / 12:00 / 18:00** 自动执行采集任务。

修改调度时间：
```python
# app/scheduler.py
scheduler.add_job(
    job_run_collection,
    CronTrigger(hour="08,12,18", minute="0"),  # 修改这里
    ...
)
```

## 监控告警

1. Prometheus + Grafana 已集成在 `docker-compose.yml` 中
2. 告警规则定义在 `monitoring/prometheus/rules/tender-scraper.yml`
3. 告警 Webhook 发送到 `http://web:8000/alerts/webhook`

## GitHub Actions CI/CD

需要配置以下 GitHub Secrets：
- `SSH_HOST` — 部署服务器地址
- `SSH_USER` — 部署用户
- `SSH_KEY` — SSH 私钥

推送 tag 或合并到 main 分支自动触发部署。

## 健康检查

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"tender-scraper"}
```
