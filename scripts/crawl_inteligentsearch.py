"""重庆资源交易网 intelligentsearch API 采集器

通过 jyxx/transaction_detail.html 的统一搜索 API 采集所有分类数据
API: POST https://www.cqggzy.com/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew

修复 (v3): newid 去重 + 改用逐条 executemany 避免 page_size 分片问题
"""
import asyncio, json, re, os, sys
from datetime import datetime, date
from typing import List, Dict, Any, Set

import httpx
from loguru import logger

sys.path.insert(0, '/app')
from app.database import get_db


# ── 配置 ─────────────────────────────────────────────────────────────────────
BASE_URL      = "https://www.cqggzy.com"
SEARCH_API    = f"{BASE_URL}/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
START_DATE    = date(2026, 1, 1)
END_DATE      = date(2026, 5, 31)

# 分类配置：name → categorynum
CATEGORIES = {
    # 工程招投标
    "招标计划":        "014001019",
    "招标公告":        "014001001",
    "邀标信息":        "014001014",
    "答疑补遗":        "014001002",
    "中标候选人公示":  "014001003",
    "中标结果公示":    "014001004",
    "合同签订基本信息公示": "014001020",
    "合同变更基本信息公示": "014001023",
    "相关公告":        "014001016",
    "终止公告":        "014001021",
    "保证金退还":      "014001018",
    # 政府采购
    "采购公告":        "014005001",
    "采购结果公告":    "014005004",
    "答疑变更":        "014005002",
    "单一来源公示":    "014005008",
}

# 不采集的分类
NO_COLLECT = {"邀标信息", "合同签订基本信息公示", "合同变更基本信息公示", "单一来源公示", "保证金退还"}

# 排除的 categorynum
EXCLUDE_CODES = {"014001018", "004002005", "014001015", "014005014", "014008011"}


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def build_post_body(categorynum: str, page_num: int = 0, rn: int = 50,
                    sdt: str = "", edt: str = "") -> dict:
    return {
        "token": "",
        "pn": page_num,
        "rn": rn,
        "sdt": sdt,
        "edt": edt,
        "wd": "",
        "inc_wd": "",
        "exc_wd": "",
        "fields": "title;content",
        "cnum": "001",
        "sort": json.dumps({"istop": "0", "ordernum": "0", "webdate": "0", "newid": "0"}),
        "ssort": "",
        "cl": 10000,
        "terminal": "",
        "condition": [{
            "fieldName": "categorynum",
            "equal": categorynum,
            "notEqual": None,
            "equalList": None,
            "notEqualList": list(EXCLUDE_CODES),
            "isLike": True,
            "likeType": 2
        }],
        "time": [{
            "fieldName": "webdate",
            "startTime": f"{sdt} 00:00:00" if sdt else "",
            "endTime": f"{edt} 23:59:59" if edt else ""
        }],
        "highlights": "",
        "statistics": None,
        "unionCondition": [],
        "accuracy": "",
        "noParticiple": "1",
        "searchRange": None,
        "noWd": True,
        "isBusiness": "1"
    }


def parse_record(r: dict) -> dict:
    pub_date_str = r.get("pubinwebdate", "") or r.get("startdate", "") or ""
    pub_date = None
    if pub_date_str:
        try:
            pub_date = datetime.strptime(pub_date_str[:10], "%Y-%m-%d")
        except ValueError:
            pass

    content = r.get("content", "") or ""
    title = r.get("titlenew", "") or r.get("title", "") or ""

    infod   = r.get("infod", "") or ""
    linkurl = r.get("linkurl", "") or ""
    if infod:
        url = f"{BASE_URL}/xxhz/{infod}/transaction_detail.html"
    elif linkurl:
        url = f"{BASE_URL}{linkurl}" if linkurl.startswith("/") else linkurl
    else:
        url = ""

    return {
        "url": url,
        "title": title[:500],
        "info_type": "",
        "publish_date": pub_date,
        "publish_date_raw": pub_date.strftime("%Y-%m-%d") if pub_date else "",
        "content_preview": content[:500],
        "full_content": content[:5000],
        "category": r.get("categorytype", ""),
        "region": r.get("infoc", ""),
        "source": r.get("infoa", ""),
        "project_no": infod,
        "newid": str(r.get("newid", "")),
    }


async def fetch_category(client: httpx.AsyncClient, category_name: str, categorynum: str,
                          sdt: str, edt: str, max_pages: int = 300) -> tuple[int, List[dict]]:
    """采集单个分类，返回 (total_count, unique_records)
    
    按 newid 去重：同一分类中相同 newid 的记录只保留第一条（第一条优先）
    """
    seen_newids: Set[str] = set()
    all_unique: List[dict] = []
    page_size = 50
    total_count = 0

    for page in range(max_pages):
        body = build_post_body(categorynum, page, page_size, sdt, edt)
        try:
            resp = await client.post(SEARCH_API, json=body, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"  ⚠ {category_name} page {page} error: {e}")
            break

        content_str = data.get("content", "")
        if isinstance(content_str, str):
            try:
                content = json.loads(content_str)
            except json.JSONDecodeError:
                logger.warning(f"  ⚠ {category_name} page {page} parse error")
                break
        else:
            content = content_str

        result = content.get("result", {}) if isinstance(content, dict) else {}
        total_count = int(result.get("totalcount", 0) or 0)
        records = result.get("records", [])

        if not records:
            break

        new_unique = 0
        for r in records:
            newid = str(r.get("newid", ""))
            if newid and newid not in seen_newids:
                seen_newids.add(newid)
                parsed = parse_record(r)
                parsed["info_type"] = category_name
                all_unique.append(parsed)
                new_unique += 1

        logger.info(f"  {category_name} page {page+1}: {new_unique} new (total {len(all_unique)}, website {total_count})")

        if len(records) < page_size:
            break

    return total_count, all_unique


async def run():
    logger.info("=== 重庆资源交易网 intelligentsearch 采集器 v3 ===")
    logger.info(f"日期范围: {START_DATE} ~ {END_DATE}")

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Referer": f"{BASE_URL}/jyxx/transaction_detail.html",
        },
        timeout=httpx.Timeout(60.0, connect=10.0),
    ) as client:

        total_all = 0
        for cat_name, catnum in CATEGORIES.items():
            if cat_name in NO_COLLECT:
                continue

            sdt = START_DATE.strftime("%Y-%m-%d")
            edt = END_DATE.strftime("%Y-%m-%d")

            logger.info(f"\n[{cat_name}] 采集中 (categorynum={catnum})...")
            total_count, records = await fetch_category(
                client, cat_name, catnum, sdt, edt
            )

            if not records:
                logger.warning(f"  ⚠ {cat_name} 无数据")
                continue

            # 写入 DB
            db = get_db()
            cols = [
                "url", "title", "category", "info_type", "business_type",
                "publish_date", "publish_date_raw", "content_preview", "full_content",
                "budget", "bid_amount", "deadline", "region", "industry",
                "tender_type", "project_overview", "bidder_requirements",
                "submission_deadline", "contact_name", "contact_phone", "contact_email",
                "attachments_count", "attachments", "keywords_matched",
                "source_url", "scraped_at", "scraped_by",
                "contract_amount", "planned_publish_date", "tender_content",
            ]
            placeholders = ",".join(["%s"] * len(cols))
            set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols[1:])
            insert_sql = f"""
                INSERT INTO projects_cqggzy ({','.join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (url) DO UPDATE SET {set_clause}
            """

            null_cols = {'deadline', 'publish_date', 'attachments_count', 'opening_date', 'scraped_at'}
            def _to_val(r, c):
                v = r.get(c)
                if v is None:
                    return None
                return v if c in null_cols else (v or "")

            rows = [[_to_val(rec, c) for c in cols] for rec in records]

            # 改用 psycopg2.extras.execute_batch 确保大批量正确写入
            from psycopg2.extras import execute_batch
            conn = db._get_conn().conn
            cursor = conn.cursor()
            execute_batch(cursor, insert_sql, rows, page_size=1000)
            conn.commit()
            cursor.close()

            logger.info(f"  ✅ {cat_name}: 写入 {len(rows)} 条 (网站总计 {total_count})")
            total_all += len(rows)

            await asyncio.sleep(0.5)

    logger.info(f"\n总计写入: {total_all} 条")

    # 清除 API 缓存
    try:
        web_url = os.getenv("WEB_URL", "http://tender-scraper-web:8000")
        cache_key = os.getenv("INTERNAL_CACHE_CLEAR_KEY", "")
        async with httpx.AsyncClient() as c:
            await c.post(f"{web_url}/api/cache/clear", json={"internal_key": cache_key}, timeout=5)
    except Exception:
        pass

    logger.info("✅ 完成")


if __name__ == "__main__":
    asyncio.run(run())