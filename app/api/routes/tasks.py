"""任务管理 API - 采集任务 CRUD + 执行跟踪"""

import json
import time
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Body, Request
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from app.database import get_db
from app.api.dependencies import get_current_user
from app.utils.session import get_user_from_session
from app.security.audit import write_audit_log

router = APIRouter(prefix="/api/tasks", tags=["任务管理"])

_executor = ThreadPoolExecutor(max_workers=4)

# ── Task CRUD ──────────────────────────────────────────────────────────────

@router.get("")
async def list_tasks(
    request: Request,
    status: str = None,
    source: str = None,
    limit: int = 50,
    user_id: str = Depends(get_current_user),
):
    """列出任务（支持按状态/来源筛选）"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    sql = """
        SELECT id, name, source, status, schedule_type, schedule_cron,
               keywords, exclude_keywords, info_types, budget_min,
               priority, max_concurrency, request_interval, timeout_seconds,
               items_found, items_new, last_run_at, created_at, updated_at
        FROM collection_tasks
        WHERE user_id = ?
    """
    params = [user_id]

    if status:
        sql += " AND status = ?"
        params.append(status)
    if source:
        sql += " AND source = ?"
        params.append(source)

    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    def _query():
        cur = conn.execute(sql, tuple(params))
        return cur.fetchall()

    rows = await loop.run_in_executor(_executor, _query)

    tasks = []
    for r in rows:
        tasks.append({
            "id": r[0], "name": r[1], "source": r[2], "status": r[3],
            "schedule_type": r[4], "schedule_cron": r[5],
            "keywords": json.loads(r[6]) if r[6] else [],
            "exclude_keywords": json.loads(r[7]) if r[7] else [],
            "info_types": json.loads(r[8]) if r[8] else [],
            "budget_min": r[9],
            "priority": r[10] or 5,
            "max_concurrency": r[11] or 5,
            "request_interval": r[12] or 2.0,
            "timeout_seconds": r[13] or 30,
            "items_found": r[14] or 0,
            "items_new": r[15] or 0,
            "last_run_at": r[16],
            "created_at": r[17], "updated_at": r[18],
        })

    return JSONResponse({"tasks": tasks, "total": len(tasks)})


@router.post("")
async def create_task(
    request: Request,
    task: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """创建任务"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    name = task.get("name", "").strip()
    source = task.get("source", "").strip()
    if not name or not source:
        return JSONResponse({"success": False, "error": "名称和来源不能为空"}, status_code=400)

    def _insert():
        cursor = conn.execute("""
            INSERT INTO collection_tasks
            (user_id, name, source, status, schedule_type, schedule_cron,
             keywords, exclude_keywords, info_types, budget_min,
             priority, max_concurrency, request_interval, timeout_seconds,
             created_at, updated_at)
            VALUES (?, ?, ?, 'idle', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
        """, (
            user_id, name, source,
            task.get("schedule_type", "manual"),
            task.get("schedule_cron", ""),
            json.dumps(task.get("keywords", []), ensure_ascii=False),
            json.dumps(task.get("exclude_keywords", []), ensure_ascii=False),
            json.dumps(task.get("info_types", []), ensure_ascii=False),
            task.get("budget_min") or None,
            task.get("priority", 5),
            task.get("max_concurrency", 5),
            task.get("request_interval", 2.0),
            task.get("timeout_seconds", 30),
        ))
        task_id = cursor.fetchone()[0]
        conn.commit()
        return task_id

    task_id = await loop.run_in_executor(_executor, _insert)
    write_audit_log("task_created", user_id, request, f"/tasks/{task_id}", "success", {"name": name, "source": source})

    return JSONResponse({"success": True, "task_id": task_id})


@router.get("/{task_id}")
async def get_task(task_id: int, request: Request, user_id: str = Depends(get_current_user)):
    """获取任务详情"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    def _fetch():
        cursor = conn.execute("SELECT * FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cursor.fetchone(), cursor.description

    row, desc = await loop.run_in_executor(_executor, _fetch)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    colnames = [d[0] for d in desc]
    r = dict(zip(colnames, row))

    def _fetch_history():
        cur2 = conn.execute(
            "SELECT id, status, items_found, items_new, error_message, started_at, finished_at, duration_ms FROM task_executions WHERE task_id=? ORDER BY id DESC LIMIT 20",
            (task_id,)
        )
        return cur2.fetchall()

    exec_rows = await loop.run_in_executor(_executor, _fetch_history)

    return JSONResponse({
        "task": {
            "id": r["id"], "name": r["name"], "source": r["source"], "status": r["status"],
            "schedule_type": r["schedule_type"], "schedule_cron": r["schedule_cron"],
            "keywords": json.loads(r["keywords"]) if r["keywords"] else [],
            "exclude_keywords": json.loads(r["exclude_keywords"]) if r["exclude_keywords"] else [],
            "info_types": json.loads(r["info_types"]) if r["info_types"] else [],
            "budget_min": r["budget_min"],
            "priority": r["priority"], "max_concurrency": r["max_concurrency"],
            "request_interval": r["request_interval"], "timeout_seconds": r["timeout_seconds"],
            "items_found": r["items_found"], "items_new": r["items_new"],
            "last_run_at": r["last_run_at"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        },
        "executions": [
            {"id": e[0], "status": e[1], "items_found": e[2], "items_new": e[3],
             "error_message": e[4], "started_at": e[5], "finished_at": e[6], "duration_ms": e[7]}
            for e in exec_rows
        ]
    })


@router.put("/{task_id}")
async def update_task(task_id: int, request: Request, task: dict = Body(...), user_id: str = Depends(get_current_user)):
    """更新任务"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    def _check():
        cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cursor.fetchone()

    if not await loop.run_in_executor(_executor, _check):
        raise HTTPException(status_code=404, detail="任务不存在")

    fields = []
    vals = []
    updatable = ["name", "source", "schedule_type", "schedule_cron", "keywords",
                 "exclude_keywords", "info_types", "budget_min", "priority",
                 "max_concurrency", "request_interval", "timeout_seconds", "status"]

    for k, v in task.items():
        if k in updatable:
            if k in ("keywords", "exclude_keywords", "info_types"):
                v = json.dumps(v, ensure_ascii=False) if v else "[]"
            fields.append(f"{k} = ?")
            vals.append(v)

    fields.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(task_id)

    def _update():
        conn.execute(f"UPDATE collection_tasks SET {', '.join(fields)} WHERE id=?", tuple(vals))
        conn.commit()

    await loop.run_in_executor(_executor, _update)
    write_audit_log("task_updated", user_id, request, f"/tasks/{task_id}", "success", {"fields": list(task.keys())})

    return JSONResponse({"success": True})


@router.delete("/{task_id}")
async def delete_task(task_id: int, request: Request, user_id: str = Depends(get_current_user)):
    """删除任务"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    def _check():
        cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cursor.fetchone()

    if not await loop.run_in_executor(_executor, _check):
        raise HTTPException(status_code=404, detail="任务不存在")

    def _delete():
        conn.execute("DELETE FROM task_executions WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM collection_tasks WHERE id=?", (task_id,))
        conn.commit()

    await loop.run_in_executor(_executor, _delete)
    write_audit_log("task_deleted", user_id, request, f"/tasks/{task_id}", "success", {})

    return JSONResponse({"success": True})


@router.post("/{task_id}/toggle")
async def toggle_task(task_id: int, request: Request, user_id: str = Depends(get_current_user)):
    """启用/停用任务"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    def _fetch():
        cursor = conn.execute("SELECT id, status FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cursor.fetchone()

    row = await loop.run_in_executor(_executor, _fetch)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    new_status = "disabled" if row[1] == "idle" else "idle"

    def _toggle():
        conn.execute("UPDATE collection_tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, task_id))
        conn.commit()

    await loop.run_in_executor(_executor, _toggle)

    return JSONResponse({"success": True, "status": new_status})


# ── Task Execution ──────────────────────────────────────────────────────────

_execution_states: dict = {}
_execution_states_lock = threading.Lock()


def _run_crawl_task(task_id: int, user_id: str):
    """后台执行爬虫任务（在线程池运行，不阻塞事件循环）"""
    import httpx

    with _execution_states_lock:
        _execution_states[task_id] = {
            "status": "running",
            "progress": 0,
            "items_found": 0,
            "items_new": 0,
            "logs": [],
            "started_at": datetime.now().isoformat(),
            "error": None
        }

    try:
        db = get_db()
        conn = db._get_conn()

        cursor = conn.execute(
            "INSERT INTO task_executions (task_id, status, started_at) VALUES (?, 'running', CURRENT_TIMESTAMP) RETURNING id",
            (task_id,)
        )
        exec_id = cursor.fetchone()[0]
        conn.commit()

        cursor = conn.execute("SELECT * FROM collection_tasks WHERE id=?", (task_id,))
        row = cursor.fetchone()
        if not row:
            raise Exception("任务不存在")

        colnames = [d[0] for d in cursor.description]
        task = dict(zip(colnames, row))

        with _execution_states_lock:
            _execution_states[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始采集任务: {task['name']}")

        time.sleep(2)  # 模拟采集

        with _execution_states_lock:
            _execution_states[task_id]["progress"] = 100
            _execution_states[task_id]["status"] = "completed"
            _execution_states[task_id]["items_found"] = 10
            _execution_states[task_id]["items_new"] = 3
            _execution_states[task_id]["finished_at"] = datetime.now().isoformat()
            _execution_states[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 采集完成，找到 10 条，新增 3 条")

        conn2 = db._get_conn()
        conn2.execute(
            "UPDATE task_executions SET status='completed', items_found=10, items_new=3, finished_at=CURRENT_TIMESTAMP, duration_ms=2000 WHERE id=?",
            (exec_id,)
        )
        conn2.execute(
            "UPDATE collection_tasks SET items_found=items_found+10, items_new=items_new+3, last_run_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id,)
        )
        conn2.commit()

    except Exception as e:
        with _execution_states_lock:
            _execution_states[task_id]["status"] = "failed"
            _execution_states[task_id]["error"] = str(e)
            _execution_states[task_id]["finished_at"] = datetime.now().isoformat()
            _execution_states[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 执行失败: {e}")


@router.post("/{task_id}/run")
async def run_task(task_id: int, request: Request, user_id: str = Depends(get_current_user)):
    """立即执行任务（异步，后台运行）"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    def _check():
        cursor = conn.execute("SELECT id, name, status FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cursor.fetchone()

    row = await loop.run_in_executor(_executor, _check)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")

    if row[2] == "running":
        return JSONResponse({"success": False, "error": "任务正在执行中"}, status_code=409)

    def _update():
        conn.execute("UPDATE collection_tasks SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
        conn.commit()

    await loop.run_in_executor(_executor, _update)

    # 后台线程执行（不阻塞）
    asyncio.get_event_loop().run_in_executor(_executor, _run_crawl_task, task_id, user_id)

    return JSONResponse({"success": True, "message": "任务已启动"})


@router.get("/{task_id}/status")
async def get_task_status(task_id: int, request: Request, user_id: str = Depends(get_current_user)):
    """获取任务实时状态"""
    loop = asyncio.get_event_loop()

    def _check():
        conn = get_db()._get_conn()
        cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cursor.fetchone()

    if not await loop.run_in_executor(_executor, _check):
        raise HTTPException(status_code=404, detail="任务不存在")

    with _execution_states_lock:
        state = _execution_states.get(task_id, {"status": "idle", "progress": 0, "items_found": 0, "items_new": 0, "logs": []})

    return JSONResponse(state)


@router.get("/{task_id}/stream")
async def stream_task_status(task_id: int, request: Request, user_id: str = Depends(get_current_user)):
    """SSE 流式推送任务状态"""
    loop = asyncio.get_event_loop()

    def _check():
        conn = get_db()._get_conn()
        cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cursor.fetchone()

    if not await loop.run_in_executor(_executor, _check):
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        last_status = ""
        while True:
            with _execution_states_lock:
                state = _execution_states.get(task_id, {"status": "idle"})

            if state.get("status") in ("completed", "failed"):
                yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
                break

            status_str = json.dumps(state, ensure_ascii=False)
            if status_str != last_status:
                yield f"data: {status_str}\n\n"
                last_status = status_str

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/{task_id}/executions")
async def get_task_executions(task_id: int, request: Request, limit: int = 20, user_id: str = Depends(get_current_user)):
    """获取任务执行历史"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    def _check():
        cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cursor.fetchone()

    if not await loop.run_in_executor(_executor, _check):
        raise HTTPException(status_code=404, detail="任务不存在")

    def _fetch():
        cur = conn.execute(
            "SELECT id, status, items_found, items_new, error_message, started_at, finished_at, duration_ms FROM task_executions WHERE task_id=? ORDER BY id DESC LIMIT ?",
            (task_id, limit)
        )
        return cur.fetchall()

    rows = await loop.run_in_executor(_executor, _fetch)

    return JSONResponse({
        "executions": [
            {"id": r[0], "status": r[1], "items_found": r[2], "items_new": r[3],
             "error_message": r[4], "started_at": r[5], "finished_at": r[6], "duration_ms": r[7]}
            for r in rows
        ]
    })


# ── Stats ───────────────────────────────────────────────────────────────────

@router.get("/stats/summary")
async def get_task_stats(request: Request, user_id: str = Depends(get_current_user)):
    """获取任务统计摘要"""
    loop = asyncio.get_event_loop()
    conn = await loop.run_in_executor(_executor, get_db()._get_conn)

    def _stats():
        total = conn.execute("SELECT COUNT(*) FROM collection_tasks WHERE user_id=?", (user_id,)).fetchone()[0]
        running = conn.execute("SELECT COUNT(*) FROM collection_tasks WHERE user_id=? AND status='running'", (user_id,)).fetchone()[0]
        idle = conn.execute("SELECT COUNT(*) FROM collection_tasks WHERE user_id=? AND status='idle'", (user_id,)).fetchone()[0]
        disabled = conn.execute("SELECT COUNT(*) FROM collection_tasks WHERE user_id=? AND status='disabled'", (user_id,)).fetchone()[0]
        total_items = conn.execute(
            "SELECT COALESCE(SUM(items_found),0), COALESCE(SUM(items_new),0) FROM collection_tasks WHERE user_id=?",
            (user_id,)
        ).fetchone()
        return total, running, idle, disabled, total_items

    total, running, idle, disabled, total_items = await loop.run_in_executor(_executor, _stats)

    return JSONResponse({
        "total": total,
        "running": running,
        "idle": idle,
        "disabled": disabled,
        "total_items_found": total_items[0],
        "total_items_new": total_items[1],
    })
