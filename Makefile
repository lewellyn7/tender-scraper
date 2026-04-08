.PHONY: help build up down logs status restart health clean

DOCKER_COMPOSE := docker compose

help: ## 显示帮助
	@grep -E '^[\w-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── 构建 & 启动 ─────────────────────────────────────────
build: ## 构建 Docker 镜像
	$(DOCKER_COMPOSE) build --pull

up: ## 启动所有服务
	$(DOCKER_COMPOSE) up -d

down: ## 停止所有服务
	$(DOCKER_COMPOSE) down

restart: down up ## 重启所有服务

# ── 日志 & 状态 ─────────────────────────────────────────
logs: ## 查看所有服务日志
	$(DOCKER_COMPOSE) logs -f --tail=100

logs-web: ## 查看 Web 服务日志
	$(DOCKER_COMPOSE) logs -f web --tail=200

status: ## 查看服务状态
	$(DOCKER_COMPOSE) ps

health: ## 检查健康状态
	@curl -sf http://localhost:8000/health | python -m json.tool || echo "Web 服务未响应"

# ── 维护 ─────────────────────────────────────────────────
clean: ## 清理未使用的镜像和缓存
	$(DOCKER_COMPOSE) down --rmi local -v
	docker image prune -f

rebuild: down build up ## 重新构建并启动

# ── 开发 ─────────────────────────────────────────────────
dev-web: ## 仅启动 Web 服务(开发模式)
	$(DOCKER_COMPOSE) up -d web

shell-web: ## 进入 Web 容器 shell
	$(DOCKER_COMPOSE) exec web /bin/bash

# ── 监控 ─────────────────────────────────────────────────
monitoring: ## 启动监控栈 (Prometheus + Grafana)
	$(DOCKER_COMPOSE) up -d prometheus grafana alertmgr

grafana: ## 打开 Grafana (http://localhost:3000)
	@echo "Grafana: http://localhost:3000  (默认 admin/admin)"

prometheus: ## 打开 Prometheus (http://localhost:9090)
	@echo "Prometheus: http://localhost:9090"
