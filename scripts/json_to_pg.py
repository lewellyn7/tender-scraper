#!/usr/bin/env python3
"""
将 latest.json 中的记录清洗后入库 PostgreSQL (projects_cqggzy / projects_ccgp)

用法:
    python scripts/json_to_pg.py        # 干跑（只打印）
    python scripts/json_to_pg.py --run  # 正式写入
"""
import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import get_db


def infer_business_type(url: str, title: str = "") -> str:
    if "014005" in url or "order" in url:
        return "政府采购"
    if "014001" in url or "bidding" in url:
        return "工程招投标"
    text = title[:500] if title else ""
    if "采购" in text:
        return "政府采购"
    if "招标" in text:
        return "工程招投标"
    return "政府采购"


def infer_info_type(url: str) -> str:
    if "/014005/014005004/" in url:
        return "采购结果公告"
    if "/014005/014005001/" in url:
        return "采购公告"
    if "/014005/014005002/" in url:
        return "答疑变更"
    if "/014005/014005003/" in url:
        return "废标公告"
    if "/014005/014005005/" in url:
        return "合同公告"
    if "/014005/014005008/" in url:
        return "单一来源公示"
    if "/014001/014001019/" in url:
        return "招标计划"
    if "/014001/014001001/" in url:
        return "招标公告"
    if "/014001/014001014/" in url:
        return "邀标信息"
    if "/014001/014001002/" in url:
        return "答疑补遗"
    if "/014001/014001003/" in url:
        return "中标候选人公示"
    if "/014001/014001004/" in url:
        return "中标结果公示"
    if "/014001/014001020/" in url:
        return "合同签订基本信息公示"
    if "/014001/014001023/" in url:
        return "合同变更基本信息公示"
    if "/014001/014001016/" in url:
        return "相关公告"
    if "/014001/014001021/" in url:
        return "终止公告"
    return "其他"


def infer_category(url: str, title: str = "") -> str:
    """映射到 category 字段（采购公告 -> 政府采购）"""
    bt = infer_business_type(url, title)
    return bt


def choose_table(url: str) -> str:
    """根据 URL 判断写入哪个表"""
    if "ccgp" in url or "ccgp-chongqing" in url:
        return "projects_ccgp"
    return "projects_cqggzy"


def json_row_to_db_row(p: dict) -> dict:
    """将 JSON 项目 dict 转换为 DB 行 tuple（按 upsert_projects 列顺序）"""
    url = p.get("url", "")
    title = p.get("title", "") or ""
    today = datetime.now().strftime("%Y-%m-%d")

    business_type = p.get("business_type") or infer_business_type(url, title)
    info_type = p.get("info_type") or infer_info_type(url)
    category = infer_category(url, title)

    def _ts(v):
        """空字符串转为 None（timestamp 列不接受空字符串）"""
        return v if v and str(v).strip() else None

    return {
        "url": url,
        "title": title,
        "category": category,
        "info_type": info_type,
        "business_type": business_type,
        "publish_date": _ts(p.get("publish_date", "") or ""),
        "publish_date_raw": p.get("publish_date_raw", "") or "",
        "content_preview": (p.get("content_preview") or "").replace("\n", " ")[:2000],
        "full_content": p.get("full_content", "") or "",
        "budget": p.get("budget", "") or "",
        "bid_amount": p.get("bid_amount", "") or "",
        "deadline": _ts(p.get("deadline", "")),
        "region": p.get("region", "") or "",
        "industry": p.get("industry", "") or "",
        "tender_type": p.get("tender_type", "") or "",
        "project_overview": (p.get("project_overview") or "")[:2000],
        "bidder_requirements": p.get("bidder_requirements", "") or "",
        "submission_deadline": _ts(p.get("submission_deadline", "")),
        "contact_name": p.get("contact_name", "") or "",
        "contact_phone": p.get("contact_phone", "") or "",
        "contact_email": p.get("contact_email", "") or "",
        "attachments_count": p.get("attachments_count", 0) or 0,
        "attachments": json.dumps(p.get("attachments", [])) if isinstance(p.get("attachments"), list) else (p.get("attachments") or "[]"),
        "keywords_matched": p.get("keywords_matched", "") or "",
        "source_url": p.get("source_url", "") or url,
        "scraped_at": _ts(p.get("scraped_at", "")) or today,
        "scraped_by": p.get("scraped_by", "tender-scraper v3.2"),
        "contract_amount": p.get("contract_amount", "") or "",
        "planned_publish_date": _ts(p.get("planned_publish_date", "")),
        "tender_content": p.get("tender_content", "") or "",
    }


def main():
    parser = argparse.ArgumentParser(description="将 latest.json 清洗入库 PostgreSQL")
    parser.add_argument("--run", action="store_true", help="正式写入（不加则干跑）")
    args = parser.parse_args()

    SYS_PATH = Path('/app') if Path('/.dockerenv').exists() else Path(__file__).parent.parent
    json_file = SYS_PATH / "output" / "latest.json"

    if not json_file.exists():
        print(f"❌ 文件不存在: {json_file}")
        sys.exit(1)

    with open(json_file, encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    print(f"📄 latest.json 共 {len(projects)} 条记录")

    # 按表分组
    groups = {"projects_cqggzy": [], "projects_ccgp": []}
    for p in projects:
        url = p.get("url", "")
        if not url:
            continue
        tbl = choose_table(url)
        groups[tbl].append(p)

    for tbl, projs in groups.items():
        print(f"  → {tbl}: {len(projs)} 条")

    if not args.run:
        print("\n🔍 干跑模式，打印前 3 条目标记录：")
        for tbl, projs in groups.items():
            for p in projs[:3]:
                url = p.get("url", "")
                print(f"  [{tbl}] {url[:80]}")
                print(f"    bt={infer_business_type(url, p.get('',''))} it={infer_info_type(url)}")
        print("\n💡 加 --run 正式写入")
        return

    # 正式写入
    print("\n🚀 开始写入 PostgreSQL ...")
    db = get_db()
    conn_wrapper = db._get_conn()
    pg_conn = conn_wrapper.conn

    INSERT_COLS = [
        "url", "title", "category", "info_type", "business_type",
        "publish_date", "publish_date_raw", "content_preview", "full_content",
        "budget", "bid_amount", "deadline", "region", "industry",
        "tender_type", "project_overview", "bidder_requirements",
        "submission_deadline", "contact_name", "contact_phone", "contact_email",
        "attachments_count", "attachments", "keywords_matched",
        "source_url", "scraped_at", "scraped_by",
        "contract_amount", "planned_publish_date", "tender_content",
    ]

    from psycopg2.extras import execute_batch

    for tbl, projs in groups.items():
        if not projs:
            continue

        rows = []
        for p in projs:
            d = json_row_to_db_row(p)
            row = tuple(d.get(c, "") for c in INSERT_COLS)
            rows.append(row)

        placeholders = ",".join(["%s"] * len(INSERT_COLS))
        set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in INSERT_COLS[1:])
        sql = f"""
            INSERT INTO {tbl} ({','.join(INSERT_COLS)})
            VALUES ({placeholders})
            ON CONFLICT (url) DO UPDATE SET {set_clause}
        """

        cursor = pg_conn.cursor()
        execute_batch(cursor, sql, rows, page_size=500)
        pg_conn.commit()
        print(f"  ✅ 写入 {tbl}: {len(rows)} 条")

    # 验证
    cursor = pg_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM projects_cqggzy")
    cqggzy_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM projects_ccgp")
    ccgp_count = cursor.fetchone()[0]
    print(f"\n📊 PG 当前总量: cqggzy={cqggzy_count}, ccgp={ccgp_count}")

    # 清缓存（让 API 读到新数据）
    from app.api.routes.projects import _clear_cache
    _clear_cache()
    print("🧹 API 缓存已清除")


if __name__ == "__main__":
    main()
