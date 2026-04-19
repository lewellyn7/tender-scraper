# ============================================================
# Stage 1: Builder — 安装依赖（依赖稳定，缓存复用）
# 支持多架构构建：amd64 / arm64
# ============================================================
FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder

WORKDIR /app

# 跨架构编译依赖（仅构建期）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        gcc-aarch64-linux-gnu \
    && rm -rf /var/lib/apt/lists/*

# 用于 docker setup-buildx 自动适配架构
ARG BUILDPLATFORM
ARG TARGETPLATFORM
ARG PYTHONUARCH={"amd64":"x86_64","arm64":"aarch64"}[${TARGETPLATFORM:-amd64}]
ENV PYTHONUARCH=$PYTHONUARCH

# 先复制依赖文件（利用 Docker 缓存层）
COPY requirements.txt .

# 安装 Python 依赖（用户级安装避免 root）
RUN pip install --no-cache-dir --user -r requirements.txt

# ============================================================
# Stage 2: Base — 运行时基础环境（系统库 + Playwright）
# ============================================================
FROM --platform=$TARGETPLATFORM python:3.12-slim AS base

WORKDIR /app

# 安装运行时系统依赖（浏览器 + 系统库）
RUN apt-get update && apt-get install -y --no-install-recommends \
        # Playwright 浏览器依赖
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
        libatspi2.0-0 \
        fonts-liberation \
        # 其他运行时依赖
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get autoremove -y \
    && apt-get clean

# 安装 Playwright 浏览器（仅 chromium）
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0

RUN pip install --no-cache-dir playwright==1.44.0 \
    && mkdir -p /app/.playwright \
    && PLAYWRIGHT_BROWSERS_PATH=/app/.playwright playwright install chromium \
    && pip uninstall -y playwright \
    && find /root/.cache -type f -name "*.whl" -delete 2>/dev/null || true

# ============================================================
# Stage 3: Runtime — 生产镜像（最小权限，多架构）
# ============================================================
FROM --platform=$TARGETPLATFORM base AS runtime

# 安全：非 root 用户
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid 1000 \
        --shell /bin/bash \
        --create-home \
        appuser

# 从 builder 复制已安装的 Python 包
COPY --from=builder /root/.local /home/appuser/.local

# 从 base 复制 Playwright 浏览器（base 阶段已安装）
COPY --from=base /app/.playwright /app/.playwright

# 复制应用代码（晚于依赖，利用缓存）
# 先创建必要目录
RUN mkdir -p /app/logs /app/output /app/data \
    && chown -R appuser:appgroup /app

# 复制应用代码（使用 .dockerignore 排除 tests/ venv/ .git/）
COPY --chown=appuser:appgroup . .

# Python 环境
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

USER appuser

# 健康检查（容器内部访问 8000，不是 8888）
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5)" || exit 1

EXPOSE 8000

# 默认启动 web 服务（command 可被 docker-compose 覆盖）
# web_server.py: FastAPI 管理界面（PORT env 来自 docker-compose）
# main.py: 独立采集调度（无 uvicorn）
CMD ["python", "web_server.py"]
