"""自定义爬虫配置 API"""

import json
import os
import time
import threading
from pathlib import Path
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.database import get_db
from app.utils.session import get_user_from_session
from app.api.dependencies import get_current_user
from fastapi import Depends
from app.core.crawl_executor import CrawlExecutor, PLAYWRIGHT_AVAILABLE
from app.security.audit import write_audit_log, EVENT_CONFIG_CHANGE, EVENT_DATA_DELETE

router = APIRouter(prefix="/api/crawler-configs", tags=["自定义爬虫"])


def _get_current_user(request) -> dict:
    """self_mode-aware 取当前用户：self_mode 自动 admin，团队模式从 session 拿"""
    from app.config.settings import get_settings
    if get_settings().is_self_mode:
        return {"user_id": "admin", "username": "admin", "role": "admin"}
    return _legacy_get_user_id(request)


def _legacy_get_user_id(request) -> str:
    token = request.cookies.get("session_token") or request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_user_from_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="无效的session")
    return user["user_id"]


@router.get("/{config_id}")
def get_config(config_id: int, request: Request):
    """获取单个爬虫配置"""
    _get_current_user(request)  # require auth
    db = get_db()
    conn = db._get_conn()
    cursor = conn.execute("SELECT * FROM crawler_configs WHERE id=?", (config_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="配置不存在")
    colnames = [d[0] for d in cursor.description]
    cfg = dict(zip(colnames, row))
    cfg["item_rules"] = json.loads(cfg.get("item_rules", "{}"))
    cfg["headers"] = json.loads(cfg.get("headers", "{}"))
    return JSONResponse(cfg)


@router.get("")
def list_configs(request: Request):
    """列出所有爬虫配置"""
    _get_current_user(request)  # require auth
    db = get_db()
    conn = db._get_conn()
    cursor = conn.execute(
        "SELECT id, name, base_url, status, created_at, updated_at FROM crawler_configs ORDER BY id DESC"
    )
    rows = cursor.fetchall()
    return JSONResponse({
        "configs": [
            {
                "id": r[0], "name": r[1], "base_url": r[2],
                "status": r[3], "created_at": str(r[4]), "updated_at": str(r[5])
            } for r in rows
        ]
    })


@router.post("")
def create_config(request: Request, config: dict = Body(...)):
    """创建爬虫配置"""
    user = _get_current_user(request); user_id = user["user_id"] if isinstance(user, dict) else user
    db = get_db()
    conn = db._get_conn()
    name = config.get("name", "").strip()
    base_url = config.get("base_url", "").strip()
    if not name or not base_url:
        raise HTTPException(status_code=400, detail="name和base_url必填")

    item_rules = json.dumps(config.get("item_rules", {}), ensure_ascii=False)
    cur = conn.execute(
        """INSERT INTO crawler_configs
           (name, base_url, list_selector, item_rules, pagination_type,
            pagination_selector, pagination_param, filter_keyword, cookies, headers,
            status, business_type, info_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
           RETURNING id""",
        (
            name, base_url,
            config.get("list_selector", ""),
            item_rules,
            config.get("pagination_type", "none"),
            config.get("pagination_selector", ""),
            config.get("pagination_param", ""),
            config.get("filter_keyword", ""),
            config.get("cookies", ""),
            json.dumps(config.get("headers", {}), ensure_ascii=False),
            config.get("business_type", ""),
            config.get("info_type", "")
        )
    )
    new_id = cur.fetchone()[0]
    conn.commit()

    write_audit_log(
        EVENT_CONFIG_CHANGE,
        user_id=user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        resource=f"crawler_config:{new_id}",
        result="success",
        details={"action": "create", "name": name, "base_url": base_url},
    )
    return JSONResponse({"success": True, "id": new_id})


@router.put("/{config_id}")
def update_config(config_id: int, request: Request, config: dict = Body(...)):
    """更新爬虫配置"""
    user = _get_current_user(request); user_id = user["user_id"] if isinstance(user, dict) else user
    db = get_db()
    conn = db._get_conn()
    item_rules = json.dumps(config.get("item_rules", {}), ensure_ascii=False)
    conn.execute(
        """UPDATE crawler_configs SET
           name=?, base_url=?, list_selector=?, item_rules=?, pagination_type=?,
           pagination_selector=?, pagination_param=?, filter_keyword=?, cookies=?, headers=?,
           business_type=?, info_type=?,
           updated_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (
            config.get("name"), config.get("base_url"),
            config.get("list_selector", ""), item_rules,
            config.get("pagination_type", "none"),
            config.get("pagination_selector", ""),
            config.get("pagination_param", ""),
            config.get("filter_keyword", ""),
            config.get("cookies", ""),
            config.get("business_type", ""),
            config.get("info_type", ""),
            config_id
        )
    )
    conn.commit()

    write_audit_log(
        EVENT_CONFIG_CHANGE,
        user_id=user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        resource=f"crawler_config:{config_id}",
        result="success",
        details={"action": "update", "name": config.get("name")},
    )
    return JSONResponse({"success": True})


@router.delete("/{config_id}")
def delete_config(config_id: int, request: Request):
    """删除爬虫配置"""
    user = _get_current_user(request); user_id = user["user_id"] if isinstance(user, dict) else user
    db = get_db()
    conn = db._get_conn()
    # 获取配置名用于审计
    cur = conn.execute("SELECT name FROM crawler_configs WHERE id=?", (config_id,))
    row = cur.fetchone()
    config_name = row[0] if row else str(config_id)
    conn.execute("DELETE FROM crawl_executions WHERE config_id=?", (config_id,))
    conn.execute("DELETE FROM crawler_configs WHERE id=?", (config_id,))
    conn.commit()

    write_audit_log(
        EVENT_CONFIG_CHANGE,
        user_id=user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        resource=f"crawler_config:{config_id}",
        result="success",
        details={"action": "delete", "name": config_name},
    )
    return JSONResponse({"success": True})


@router.post("/{config_id}/run")
def run_config(config_id: int, request: Request):
    """手动执行爬虫（同步，15秒超时）"""
    db = get_db()
    conn = db._get_conn()
    cursor = conn.execute("SELECT * FROM crawler_configs WHERE id=?", (config_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="配置不存在")

    colnames = [d[0] for d in cursor.description]
    cfg = dict(zip(colnames, row))

    # 记录执行
    cur = conn.execute(
        "INSERT INTO crawl_executions (config_id, status) VALUES (?, 'running') RETURNING id",
        (config_id,)
    )
    exec_id = cur.fetchone()[0]
    conn.commit()

    try:
        if not PLAYWRIGHT_AVAILABLE:
            raise Exception("Playwright未安装")

        executor = CrawlExecutor(cfg)
        result = executor.crawl(timeout=15)

        # 写入 output/latest.json
        out_file = Path(__file__).parent.parent.parent.parent / "output" / "latest.json"
        existing = []
        if out_file.exists():
            try:
                existing = json.loads(out_file.read_text()).get("projects", [])
            except Exception:
                existing = []

        existing_urls = {p.get("url", "") for p in existing}
        new_projects = [p for p in result.get("results", []) if p.get("url") and p["url"] not in existing_urls]

        all_projects = existing + new_projects
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps({
            "projects": all_projects,
            "total": len(all_projects),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }, ensure_ascii=False, indent=2))

        # 更新执行记录
        conn2 = db._get_conn()
        conn2.execute(
            "UPDATE crawl_executions SET status='completed', items_found=?, items_new=?, finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (result.get("items_found", 0), len(new_projects), exec_id)
        )
        conn2.commit()

        return JSONResponse({
            "success": True,
            "execution_id": exec_id,
            "items_found": result.get("items_found", 0),
            "items_new": len(new_projects)
        })

    except Exception as e:
        conn3 = db._get_conn()
        conn3.execute(
            "UPDATE crawl_executions SET status='failed', error_message=?, finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (str(e), exec_id)
        )
        conn3.commit()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/{config_id}/executions")
def list_executions(config_id: int, request: Request, limit: int = 20):
    """获取执行历史"""
    db = get_db()
    conn = db._get_conn()
    cursor = conn.execute(
        "SELECT id, status, items_found, items_new, error_message, started_at, finished_at FROM crawl_executions WHERE config_id=? ORDER BY id DESC LIMIT ?",
        (config_id, limit)
    )
    rows = cursor.fetchall()
    return JSONResponse({
        "executions": [
            {"id": r[0], "status": r[1], "items_found": r[2], "items_new": r[3],
             "error_message": r[4], "started_at": str(r[5]), "finished_at": str(r[6]) if r[6] else None}
            for r in rows
        ]
    })


@router.post("/generate-rules")
def generate_rules(request: Request, payload: dict = Body(...)):
    """LLM生成爬虫规则"""
    description = payload.get("description", "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description不能为空")

    llm_service = None
    try:
        from app.services.llm_service import get_llm_service_sync
        llm_service = get_llm_service_sync()
    except Exception:
        pass

    if not llm_service:
        return JSONResponse({"error": "LLM服务未配置"}, status_code=503)

    prompt = f"""你是一个爬虫规则生成器。用户想要从某个网站抓取招标/采购信息。

用户描述：
{description}

请生成一个爬虫配置的JSON，包含以下字段：
{{
  "name": "网站名称",
  "base_url": "入口页面URL",
  "list_selector": "列表项的CSS选择器",
  "item_rules": {{
    "title": {{"selector": "标题选择器", "attr": "text"}},
    "url": {{"selector": "链接选择器", "attr": "href"}},
    "publish_date": {{"selector": "日期选择器", "attr": "text"}},
    "budget": {{"selector": "预算选择器", "attr": "text"}}
  }},
  "pagination_type": "none|page_param|next_button",
  "pagination_selector": "下一页按钮选择器(如果适用)",
  "pagination_param": "分页URL参数模板，如 page={{n}}",
  "filter_keyword": "过滤关键词(可选)"
}}

只返回JSON，不要其他内容。"""

    try:
        resp = llm_service.chat([{"role": "user", "content": prompt}])
        text = resp.get("content", resp.get("text", ""))
        import re
        m = re.search(r'\{[^{}]*"name"[^{}]*"base_url"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if m:
            rules = json.loads(m.group())
        else:
            m2 = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if m2:
                rules = json.loads(m2.group(1))
            else:
                m3 = re.search(r'\{.*\}', text, re.DOTALL)
                if m3:
                    rules = json.loads(m3.group())
                else:
                    return JSONResponse({"error": "LLM输出无法解析为JSON", "raw": text[:500]}, status_code=422)
        return JSONResponse({"rules": rules})
    except Exception as e:
        return JSONResponse({"error": f"LLM调用失败: {e}"}, status_code=500)
