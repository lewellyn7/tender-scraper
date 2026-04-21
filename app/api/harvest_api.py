"""
api_server.py — 采集系统 FastAPI 服务
======================================
集成 SmartScheduler + HumanCrawlerBase + db_models

端点:
    POST /crawl           - 触发采集任务
    GET  /status/{task_id} - 获取任务状态
    GET  /results/{task_id} - 获取采集结果
    GET  /stats           - 获取统计信息
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import uvicorn
from app.crawlers.async_base import HumanCrawlerBase
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

# 本地模块
from app.core.harvest.smart_scheduler import (
    CrawlTask,
    DatabaseManager,
    SmartScheduler,
    init_tables,
    save_harvest_records,
)

# ─────────────────────────────────────────────────────────────────────────────
# 日志
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("api_server")

# ─────────────────────────────────────────────────────────────────────────────
# 动态配置（可被环境变量覆盖）
# ─────────────────────────────────────────────────────────────────────────────
import os

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://scraper:changeme_pg_password_2026@localhost:5432/tender_scraper",
)
MAX_CONCURRENT: int = int(os.getenv("MAX_CONCURRENT", "20"))

# ─────────────────────────────────────────────────────────────────────────────
# 全局状态
# ─────────────────────────────────────────────────────────────────────────────

# 调度器实例
_scheduler: Optional[SmartScheduler] = None

# 任务结果缓存  {task_id: {status, result, error, created_at, finished_at}}
_task_results: dict[str, dict[str, Any]] = {}

# 全局锁，保护调度器并发写入
_scheduler_lock = asyncio.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# 爬虫实现（默认）
# ─────────────────────────────────────────────────────────────────────────────


class DefaultCrawler(HumanCrawlerBase):
    """
    默认爬虫实现 — 仅演示用。
    实际使用时替换为具体站点爬虫子类。
    """

    async def parse(self, page):
        # 演示：等待页面加载后提取标题和链接
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        title = await page.title()
        links = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                .slice(0, 20)
                .map(a => ({ text: a.textContent.trim(), href: a.href }))
        """)

        return {
            "title": title,
            "links_count": len(links),
            "sample_links": links[:5],
            "url": page.url,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 请求/响应模型
# ─────────────────────────────────────────────────────────────────────────────


class CrawlRequest(BaseModel):
    """POST /crawl 请求体"""

    source: str = Field(..., description="站点标识，如 'cqggzy', 'ccgp'")
    url: str = Field(..., description="采集目标 URL")
    info_type: str = Field(default="招标公告", description="信息类型")
    region: str = Field(default="重庆", description="地区")
    keywords: list[str] = Field(default_factory=list, description="关键词匹配列表")
    priority_static: int = Field(default=5, ge=1, le=10, description="静态优先级 1-10")
    max_retries: int = Field(default=3, ge=0, le=10, description="最大重试次数")
    use_browser: bool = Field(default=False, description="是否启用浏览器（Playwright）")

    model_config = {
        "json_schema_extra": {
            "example": {
                "source": "cqggzy",
                "url": "https://www.ccgp.gov.cn/cggg/dfgg/index.htm",
                "info_type": "招标公告",
                "region": "重庆",
                "keywords": ["智慧城市", "数字化"],
                "priority_static": 7,
                "max_retries": 3,
                "use_browser": False,
            }
        }
    }


class CrawlResponse(BaseModel):
    """POST /crawl 响应"""

    task_id: str
    message: str
    priority_score: float
    status: str


class TaskStatusResponse(BaseModel):
    """GET /status/{task_id} 响应"""

    task_id: str
    status: str
    source: str
    url: str
    priority_dynamic: float
    retry_count: int
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result_cached: bool = False


class CrawlResultItem(BaseModel):
    """单条采集结果"""

    record_id: Optional[int] = None
    title: str
    source_url: str
    source_name: str
    publish_date: Optional[str] = None
    matched_keywords: list[str]
    raw_data: dict[str, Any]
    created_at: Optional[str] = None


class CrawlResultResponse(BaseModel):
    """GET /results/{task_id} 响应"""

    task_id: str
    status: str
    records: list[CrawlResultItem]
    total: int
    finished_at: Optional[str] = None


class SourceStatItem(BaseModel):
    """单个站点统计"""

    success_rate: float
    avg_response_ms: float
    is_banned: bool
    ban_until: Optional[str] = None
    error_counts: dict[str, int]


class StatsResponse(BaseModel):
    """GET /stats 响应"""

    scheduler: dict[str, Any]
    database: dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
# 内部函数
# ─────────────────────────────────────────────────────────────────────────────


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run_crawl_task(
    task_id: str,
    crawler: HumanCrawlerBase,
    db_url: str,
    task_keywords: list[str],
    source_name: str,
) -> None:
    """
    后台执行单个采集任务（asyncio task body）。
    1. 调用 crawler.crawl() 采集
    2. 结果写入 _task_results
    3. 持久化到数据库
    """
    global _task_results

    logger.info(f"[{task_id}] 开始采集: {crawler}")

    # 确保数据库连接
    DatabaseManager._pool = None  # reset lazy init
    import os as _os
    _os.environ["DATABASE_URL"] = db_url

    try:
        # 初始化数据库表（容错）
        try:
            await init_tables()
        except Exception as e:
            logger.warning(f"[{task_id}] 初始化表失败（可能已存在）: {sanitize_error_message(str(e))}")

        # 执行采集
        start = datetime.now(timezone.utc)
        async with crawler:
            raw_result = await crawler.parse(crawler.page)

        elapsed_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

        # 构造 HarvestRecord
        records_to_save = []
        if isinstance(raw_result, list):
            for item in raw_result:
                records_to_save.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "date": item.get("date"),
                        "matched_keywords": task_keywords,
                        "raw_data": item,
                    }
                )
        else:
            records_to_save.append(
                {
                    "title": raw_result.get("title", ""),
                    "url": raw_result.get("url", ""),
                    "date": raw_result.get("date"),
                    "matched_keywords": [],
                    "raw_data": raw_result,
                }
            )

        # 持久化到数据库
        saved_records = []
        try:
            inserted, updated = await save_harvest_records(
                records_to_save,
                source_name=source_name,
            )
            saved_records = records_to_save  # 简化：直接返回原始数据
            logger.info(
                f"[{task_id}] 数据库持久化完成: 插入={inserted}, 更新={updated}"
            )
        except Exception as db_err:
            logger.warning(f"[{task_id}] 数据库写入失败: {db_err}")

        # 更新内存结果
        _task_results[task_id] = {
            "status": "succeeded",
            "result": raw_result,
            "records": saved_records,
            "elapsed_ms": round(elapsed_ms, 2),
            "finished_at": _iso_now(),
        }

        logger.info(f"[{task_id}] 采集完成，耗时 {elapsed_ms:.0f}ms")

    except Exception as exc:
        logger.error(f"[{task_id}] 采集异常: {exc}")
        _task_results[task_id] = {
            "status": "failed",
            "error": str(exc),
            "finished_at": _iso_now(),
        }


async def _build_crawler_instance(
    request: CrawlRequest,
) -> tuple[HumanCrawlerBase, str]:
    """根据请求参数构造爬虫实例。"""
    source = request.source

    # 构造默认爬虫（带站点元信息）
    class SiteCrawler(DefaultCrawler):
        source_name = source

    crawler = SiteCrawler(
        headless=True,
        stealth=True,
        timeout=30000,
    )

    # TODO: 后续可扩展为工厂模式，按 source 加载具体爬虫子类
    return crawler, source


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI 生命周期
# ─────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭钩子"""
    global _scheduler

    logger.info("启动采集系统 API 服务...")

    # 初始化调度器
    _scheduler = SmartScheduler(max_concurrent=MAX_CONCURRENT)
    logger.info(f"调度器就绪，最大并发: {MAX_CONCURRENT}")

    # 初始化数据库连接池
    try:
        await init_tables()
        logger.info("数据库表初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化警告: {sanitize_error_message(str(e))}")

    logger.info("API 服务已就绪 ✓")

    yield

    # 关闭
    logger.info("关闭数据库连接池...")
    await DatabaseManager.close_pool()
    logger.info("API 服务已关闭 ✓")


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI 应用
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="采集系统 API",
    description="基于 FastAPI + SmartScheduler + HumanCrawlerBase 的采集服务",
    version="1.0.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────────
# 健康检查
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["健康检查"])
async def health_check():
    return {
        "status": "healthy",
        "service": "tender-scraper-api",
        "version": "1.0.0",
        "timestamp": _iso_now(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /crawl — 触发采集任务
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/crawl", response_model=CrawlResponse, tags=["采集"])
async def trigger_crawl(request: CrawlRequest, background_tasks: BackgroundTasks):
    """
    触发一个新的采集任务。

    - 任务立即注册到 SmartScheduler
    - 实际采集异步执行（BackgroundTasks）
    - 返回 task_id 用于查询状态和结果
    """
    global _scheduler, _task_results

    task_id = str(uuid.uuid4())[:12]

    # 构造 CrawlTask
    task = CrawlTask(
        task_id=task_id,
        source=request.source,
        url=request.url,
        info_type=request.info_type,
        region=request.region,
        keywords=request.keywords,
        priority_static=request.priority_static,
        max_retries=request.max_retries,
    )

    # 注册到调度器
    priority_score = await _scheduler.register(task)

    # 初始化结果占位
    _task_results[task_id] = {
        "status": "pending",
        "result": None,
        "records": [],
        "created_at": _iso_now(),
        "finished_at": None,
    }

    # 构造爬虫并启动后台采集
    crawler, source_name = await _build_crawler_instance(request)

    background_tasks.add_task(
        _run_crawl_task,
        task_id,
        crawler,
        DATABASE_URL,
        request.keywords,
        source_name,
    )

    logger.info(
        f"[{task_id}] 任务已提交: source={request.source}, "
        f"url={request.url}, priority={priority_score:.4f}"
    )

    return CrawlResponse(
        task_id=task_id,
        message="任务已提交，采集异步执行中",
        priority_score=round(priority_score, 4),
        status="pending",
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /status/{task_id} — 获取任务状态
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/status/{task_id}", response_model=TaskStatusResponse, tags=["采集"])
async def get_task_status(task_id: str):
    """查询指定任务ID的运行状态"""
    global _scheduler, _task_results

    # 优先查内存缓存
    cached = _task_results.get(task_id)

    # 再查调度器内部状态
    scheduler_task = _scheduler._tasks.get(task_id) if _scheduler else None

    if cached is None and scheduler_task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 {task_id} 不存在",
        )

    if scheduler_task:
        task = scheduler_task
        return TaskStatusResponse(
            task_id=task_id,
            status=task.status.value,
            source=task.source,
            url=task.url,
            priority_dynamic=round(task.priority_dynamic, 4),
            retry_count=task.retry_count,
            error=task.error,
            created_at=_dt_to_str(task.created_at),
            started_at=_dt_to_str(task.started_at),
            finished_at=_dt_to_str(task.finished_at),
            result_cached=task.task_id in _task_results,
        )

    # 纯缓存命中
    return TaskStatusResponse(
        task_id=task_id,
        status=cached.get("status", "unknown"),
        source="",
        url="",
        priority_dynamic=0.0,
        retry_count=0,
        error=cached.get("error"),
        created_at=cached.get("created_at"),
        finished_at=cached.get("finished_at"),
        result_cached=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /results/{task_id} — 获取采集结果
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/results/{task_id}", response_model=CrawlResultResponse, tags=["采集"])
async def get_crawl_results(task_id: str):
    """获取指定任务的采集结果（结构化记录列表）"""
    global _task_results

    cached = _task_results.get(task_id)

    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 {task_id} 不存在或结果已过期",
        )

    records = cached.get("records", [])
    items = [
        CrawlResultItem(
            record_id=None,
            title=r.get("title", ""),
            source_url=r.get("url", ""),
            source_name=r.get("source_name", ""),
            publish_date=str(r.get("date")) if r.get("date") else None,
            matched_keywords=r.get("matched_keywords", []),
            raw_data=r.get("raw_data", {}),
            created_at=cached.get("finished_at"),
        )
        for r in records
    ]

    return CrawlResultResponse(
        task_id=task_id,
        status=cached.get("status", "unknown"),
        records=items,
        total=len(items),
        finished_at=cached.get("finished_at"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats — 获取统计信息
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/stats", response_model=StatsResponse, tags=["统计"])
async def get_stats():
    """
    返回系统全局统计信息：
    - SmartScheduler 调度统计（站点级）
    - Database 健康状态和记录数
    """
    global _scheduler

    # 调度器统计
    scheduler_stats = {
        "queue_size": _scheduler.queue_size if _scheduler else 0,
        "running_count": _scheduler.running_count if _scheduler else 0,
        "max_concurrent": MAX_CONCURRENT,
        "sources": _scheduler.get_source_stats() if _scheduler else {},
    }

    # 数据库统计
    try:
        from scripts import db_models
        db_health = await db_models.health_check()
    except Exception as e:
        db_health = {"status": "unavailable", "error": str(e)}

    return StatsResponse(scheduler=scheduler_stats, database=db_health)


# ─────────────────────────────────────────────────────────────────────────────
# 启动入口（开发/调试）
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
