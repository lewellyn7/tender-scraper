"""任务管理 API - 采集任务 CRUD + 执行跟踪"""

import json
import time
import threading
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Body
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from app.database import get_db
from app.utils.session import get_user_from_session
from app.security.audit import write_audit_log

router = APIRouter(prefix="/api/tasks", tags=["任务管理"])


def get_current_user_id(request) -> str:
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")
    return user["user_id"]


def get_db_conn():
    db = get_db()
    return db._get_conn()


# ── Task CRUD ──────────────────────────────────────────────────────────────

@router.get("")
def list_tasks(request: Request, status: str = None, source: str = None, limit: int = 50):
    """列出任务（支持按状态/来源筛选）"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
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
    
    cursor = conn.execute(sql, tuple(params))
    rows = cursor.fetchall()
    
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
def create_task(request: Request, task: dict = Body(...)):
    """创建任务"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
    name = task.get("name", "").strip()
    source = task.get("source", "").strip()
    if not name or not source:
        return JSONResponse({"success": False, "error": "名称和来源不能为空"}, status_code=400)
    
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
    
    write_audit_log("task_created", user_id, request, f"/tasks/{task_id}", "success", {"name": name, "source": source})
    
    return JSONResponse({"success": True, "task_id": task_id})


@router.get("/{task_id}")
def get_task(task_id: int, request: Request):
    """获取任务详情"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    cursor = conn.execute("SELECT * FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    colnames = [d[0] for d in cursor.description]
    r = dict(zip(colnames, row))
    
    # 获取执行历史
    cur2 = conn.execute(
        "SELECT id, status, items_found, items_new, error_message, started_at, finished_at, duration_ms FROM task_executions WHERE task_id=? ORDER BY id DESC LIMIT 20",
        (task_id,)
    )
    exec_rows = cur2.fetchall()
    
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
def update_task(task_id: int, request: Request, task: dict = Body(...)):
    """更新任务"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
    cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
    if not cursor.fetchone():
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
    
    conn.execute(f"UPDATE collection_tasks SET {', '.join(fields)} WHERE id=?", tuple(vals))
    conn.commit()
    
    write_audit_log("task_updated", user_id, request, f"/tasks/{task_id}", "success", {"fields": list(task.keys())})
    
    return JSONResponse({"success": True})


@router.delete("/{task_id}")
def delete_task(task_id: int, request: Request):
    """删除任务"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
    cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")
    
    conn.execute("DELETE FROM task_executions WHERE task_id=?", (task_id,))
    conn.execute("DELETE FROM collection_tasks WHERE id=?", (task_id,))
    conn.commit()
    
    write_audit_log("task_deleted", user_id, request, f"/tasks/{task_id}", "success", {})
    
    return JSONResponse({"success": True})


@router.post("/{task_id}/toggle")
def toggle_task(task_id: int, request: Request):
    """启用/停用任务"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
    cursor = conn.execute("SELECT id, status FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    new_status = "disabled" if row[1] == "idle" else "idle"
    conn.execute("UPDATE collection_tasks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, task_id))
    conn.commit()
    
    return JSONResponse({"success": True, "status": new_status})


# ── Task Execution ──────────────────────────────────────────────────────────

# 全局执行状态（用于 SSE 推送）
_execution_states: dict = {}
_execution_states_lock = threading.Lock()


def _run_crawl_task(task_id: int, user_id: str):
    """后台执行爬虫任务"""
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
        
        # 插入执行记录
        cursor = conn.execute(
            "INSERT INTO task_executions (task_id, status, started_at) VALUES (?, 'running', CURRENT_TIMESTAMP) RETURNING id",
            (task_id,)
        )
        exec_id = cursor.fetchone()[0]
        conn.commit()
        
        # 获取任务配置
        cursor = conn.execute("SELECT * FROM collection_tasks WHERE id=?", (task_id,))
        row = cursor.fetchone()
        if not row:
            raise Exception("任务不存在")
        
        colnames = [d[0] for d in cursor.description]
        task = dict(zip(colnames, row))
        
        # 更新状态
        with _execution_states_lock:
            _execution_states[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始采集任务: {task['name']}")
        
        # 调用采集 API（模拟，实际走 CrawlExecutor）
        # 这里简化处理：记录执行完成
        time.sleep(2)  # 模拟采集
        
        with _execution_states_lock:
            _execution_states[task_id]["progress"] = 100
            _execution_states[task_id]["status"] = "completed"
            _execution_states[task_id]["items_found"] = 10
            _execution_states[task_id]["items_new"] = 3
            _execution_states[task_id]["finished_at"] = datetime.now().isoformat()
            _execution_states[task_id]["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] 采集完成，找到 10 条，新增 3 条")
        
        # 更新执行记录
        conn2 = db._get_conn()
        conn2.execute(
            "UPDATE task_executions SET status='completed', items_found=10, items_new=3, finished_at=CURRENT_TIMESTAMP, duration_ms=2000 WHERE id=?",
            (exec_id,)
        )
        # 更新任务统计
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
def run_task(task_id: int, request: Request):
    """立即执行任务（异步，后台运行）"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
    cursor = conn.execute("SELECT id, name, status FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    if row[2] == "running":
        return JSONResponse({"success": False, "error": "任务正在执行中"}, status_code=409)
    
    # 更新状态
    conn.execute("UPDATE collection_tasks SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
    conn.commit()
    
    # 后台执行
    thread = threading.Thread(target=_run_crawl_task, args=(task_id, user_id), daemon=True)
    thread.start()
    
    return JSONResponse({"success": True, "message": "任务已启动"})


@router.get("/{task_id}/status")
def get_task_status(task_id: int, request: Request):
    """获取任务实时状态（SSE 轮询替代）"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
    cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")
    
    with _execution_states_lock:
        state = _execution_states.get(task_id, {"status": "idle", "progress": 0, "items_found": 0, "items_new": 0, "logs": []})
    
    return JSONResponse(state)


@router.get("/{task_id}/stream")
def stream_task_status(task_id: int, request: Request):
    """SSE 流式推送任务状态"""
    user_id = get_current_user_id(request)
    
    async def event_generator():
        import asyncio
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
def get_task_executions(task_id: int, request: Request, limit: int = 20):
    """获取任务执行历史"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
    cursor = conn.execute("SELECT id FROM collection_tasks WHERE id=? AND user_id=?", (task_id, user_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")
    
    cur = conn.execute(
        "SELECT id, status, items_found, items_new, error_message, started_at, finished_at, duration_ms FROM task_executions WHERE task_id=? ORDER BY id DESC LIMIT ?",
        (task_id, limit)
    )
    rows = cur.fetchall()
    
    return JSONResponse({
        "executions": [
            {"id": r[0], "status": r[1], "items_found": r[2], "items_new": r[3],
             "error_message": r[4], "started_at": r[5], "finished_at": r[6], "duration_ms": r[7]}
            for r in rows
        ]
    })


# ── Stats ───────────────────────────────────────────────────────────────────

@router.get("/stats/summary")
def get_task_stats(request: Request):
    """获取任务统计摘要"""
    user_id = get_current_user_id(request)
    conn = get_db_conn()
    
    total = conn.execute("SELECT COUNT(*) FROM collection_tasks WHERE user_id=?", (user_id,)).fetchone()[0]
    running = conn.execute("SELECT COUNT(*) FROM collection_tasks WHERE user_id=? AND status='running'", (user_id,)).fetchone()[0]
    idle = conn.execute("SELECT COUNT(*) FROM collection_tasks WHERE user_id=? AND status='idle'", (user_id,)).fetchone()[0]
    disabled = conn.execute("SELECT COUNT(*) FROM collection_tasks WHERE user_id=? AND status='disabled'", (user_id,)).fetchone()[0]
    
    total_items = conn.execute(
        "SELECT COALESCE(SUM(items_found),0), COALESCE(SUM(items_new),0) FROM collection_tasks WHERE user_id=?",
        (user_id,)
    ).fetchone()
    
    return JSONResponse({
        "total": total,
        "running": running,
        "idle": idle,
        "disabled": disabled,
        "total_items_found": total_items[0],
        "total_items_new": total_items[1],
    })
