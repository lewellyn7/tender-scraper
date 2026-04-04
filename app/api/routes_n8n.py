"""n8n 工作流集成接口"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Query
from loguru import logger

sys_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, sys_path)

router = APIRouter(prefix="/api/n8n", tags=["n8n集成"])

# n8n webhook 配置
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
N8N_TRIGGER_COLLECTION = os.getenv("N8N_TRIGGER_COLLECTION", "")  # 触发采集的 webhook URL
N8N_TRIGGER_NOTIFY = os.getenv("N8N_TRIGGER_NOTIFY", "")  # 触发通知的 webhook URL


# ========== 触发采集 ==========
@router.post("/trigger-collection")
async def trigger_collection(
    source: str = Body(None, description="采集来源: all/ccgp/cqggzy"),
    keywords: List[str] = Body(None, description="额外关键词筛选"),
    days: int = Body(3, description="采集天数范围"),
    wait: bool = Body(False, description="是否等待完成"),
    x_n8n_webhook_key: str = Header(
        None, alias="x-n8n-webhook-key", description="n8n webhook 认证密钥"
    ),
):
    """触发采集任务 (n8n webhook trigger)

    在 n8n 中配置 HTTP Request 节点:
    - Method: POST
    - URL: http://localhost:9099/api/n8n/trigger-collection
    - Body: {"source":"all","days":3}
    """
    # 认证检查
    # 禁止使用默认密钥
    expected_key = os.getenv("N8N_WEBHOOK_KEY")
    if not expected_key:
        raise ValueError("N8N_WEBHOOK_KEY 环境变量必须设置")
    if expected_key and x_n8n_webhook_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid webhook key")

    # 构建采集任务参数
    task_params = {
        "source": source or "all",
        "keywords": keywords or [],
        "days": days,
        "triggered_by": "n8n",
        "triggered_at": datetime.now().isoformat(),
    }

    logger.info(f"🔔 n8n 触发采集: {task_params}")

    if wait:
        # 同步等待模式
        result = await _run_collection_sync(task_params)
        return {"status": "completed", "result": result}
    else:
        # 异步模式 - 立即返回
        asyncio.create_task(_run_collection_async(task_params))
        return {
            "status": "accepted",
            "message": "采集任务已提交",
            "task_id": f"n8n_{int(time.time())}",
        }


async def _run_collection_sync(params: Dict) -> Dict:
    """同步执行采集"""
    # TODO: 调用实际采集逻辑
    return {"total": 0, "matched": 0, "duration_seconds": 0, "output_file": ""}


async def _run_collection_async(params: Dict):
    """异步执行采集"""
    # TODO: 调用实际采集逻辑，完成后推送结果到 n8n
    pass


# ========== 查询状态 ==========
@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """查询采集任务状态"""
    # TODO: 从 Redis/DB 获取任务状态
    return {
        "task_id": task_id,
        "status": "running",  # pending/running/completed/failed
        "progress": 50,
        "message": "采集进行中...",
    }


# ========== 获取最新数据 ==========
@router.get("/latest")
async def get_latest_data(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    matched_only: bool = Query(False),
    date_start: str = Query(None, description="YYYY-MM-DD"),
    date_end: str = Query(None, description="YYYY-MM-DD"),
):
    """获取最新采集数据 (供 n8n 消费)"""
    data_file = Path(sys_path) / "output" / "latest.json"
    if not data_file.exists():
        return {"data": [], "total": 0}

    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    if matched_only:
        projects = [p for p in projects if p.get("keywords_matched")]

    # 日期过滤
    if date_start or date_end:
        filtered = []
        for p in projects:
            pd = p.get("publish_date", "")
            if isinstance(pd, list):
                pd = pd[0] if pd else ""
            if isinstance(pd, str):
                pd = pd.replace("[", "").replace("]", "").replace("'", "")
            if pd:
                pd = pd[:10]
                if date_start and pd < date_start:
                    continue
                if date_end and pd > date_end:
                    continue
            filtered.append(p)
        projects = filtered

    return {
        "data": projects[offset : offset + limit],
        "total": len(projects),
        "offset": offset,
        "limit": limit,
        "last_run": data.get("last_run", ""),
    }


# ========== 推送数据到 n8n ==========
@router.post("/push-to-n8n")
async def push_to_n8n(
    project_urls: List[str] = Body(..., description="要推送的项目 URL 列表"),
    n8n_url: str = Body(..., description="n8n webhook URL"),
):
    """推送指定项目到 n8n workflow"""
    data_file = Path(sys_path) / "output" / "latest.json"
    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    projects = {p.get("url"): p for p in data.get("projects", [])}

    results = []
    for url in project_urls:
        if url in projects:
            results.append(projects[url])

    # 发送到 n8n
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                n8n_url,
                json={
                    "projects": results,
                    "count": len(results),
                    "timestamp": datetime.now().isoformat(),
                },
            )
            resp.raise_for_status()
        return {"success": True, "pushed": len(results)}
    except Exception as e:
        logger.error(f"推送 n8n 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 回调接口 (n8n 回调本系统) ==========
@router.post("/callback/{action}")
async def n8n_callback(
    action: str,
    data: Dict = Body(...),
    x_n8n_webhook_key: str = Header(None, alias="x-n8n-webhook-key"),
):
    """n8n 回调接口 - 处理 n8n workflow 的返回结果"""
    # 禁止使用默认密钥
    expected_key = os.getenv("N8N_WEBHOOK_KEY")
    if not expected_key:
        raise ValueError("N8N_WEBHOOK_KEY 环境变量必须设置")
    if expected_key and x_n8n_webhook_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid webhook key")

    logger.info(f"📥 n8n 回调 [{action}]: {data}")

    if action == "notify":
        # n8n 处理完通知逻辑后回调
        return {"received": True, "action": "notify"}
    elif action == "export":
        # n8n 处理完导出逻辑后回调
        return {"received": True, "action": "export"}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")


# ========== 健康检查 ==========
@router.get("/health")
async def n8n_health():
    """n8n 集成健康检查"""
    return {
        "status": "ok",
        "n8n_enabled": bool(N8N_WEBHOOK_URL),
        "timestamp": datetime.now().isoformat(),
    }
