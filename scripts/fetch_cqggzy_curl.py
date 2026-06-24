#!/usr/bin/env python3
"""
CQGGZY 数据采集 - curl + python 方案 (绕过 Playwright)
基于 app/crawlers/cqggzy.py:88-150 的 API payload 结构

用法:
  python3 scripts/fetch_cqggzy_curl.py --category 014001001 --date 2026-06-23
  python3 scripts/fetch_cqggzy_curl.py --backfill --date-start 2026-06-22 --date-end 2026-06-23
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加项目根路径
sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_URL = "https://www.cqggzy.com"
API_URL = f"{BASE_URL}/api/special-zone/search-engine-page"

# 用户指定的 8 大类 (2026-06-23 指令)
CATEGORY_WHITELIST = {
    "014001019": "engineering_plan",
    "014001001": "engineering_tender",
    "014001002": "engineering_clarification",
    "014001003": "engineering_candidate",
    "014001004": "engineering_result",
    "014005001": "gov_purchase_announcement",
    "014005002": "gov_purchase_change",
    "014005004": "gov_purchase_result",
}

# 排除的 categoryNum (2026-06-23 17:51 指令)
CATEGORY_BLACKLIST = {"014005008", "014001015"}


def _curl_post(url: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """执行 curl POST 请求"""
    payload_json = json.dumps(data, ensure_ascii=False)
    cmd = [
        "curl", "-s", "-L", "--max-time", "30",
        "-H", "Accept: application/json, text/plain, */*",
        "-H", "Content-Type: application/json",
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-H", "Referer: https://www.cqggzy.com/",
        "-H", "Origin: https://www.cqggzy.com",
        "-X", "POST",
        "-d", payload_json,
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def _curl_get(url: str) -> Optional[str]:
    """执行 curl GET 请求"""
    cmd = [
        "curl", "-s", "-L", "--max-time", "30",
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-H", "Referer: https://www.cqggzy.com/",
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


def _build_api_payload(category_num: str, page_num: int = 1, date_start: str = "", date_end: str = "") -> Dict[str, Any]:
    """构建 API POST payload (基于 cqggzy.py:90-150 实际格式)"""
    pn = page_num - 1  # API 页码从 0 开始
    rn = 50

    # 日期处理：API 的 edt 是排他的
    sdt = date_start if date_start else ""
    if date_end:
        try:
            edt = (datetime.strptime(date_end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            edt = date_end
    else:
        edt = ""

    return {
        "token": "",
        "pn": pn,
        "rn": rn,
        "sdt": sdt,
        "edt": edt,
        "wd": "",
        "inc_wd": "",
        "exc_wd": "",
        "fields": "",
        "sort": '{"istop":"0","ordernum":"0","webdate":"0","newid":"0"}',
        "ssort": "",
        "cl": 10000,
        "terminal": "",
        "highlights": "",
        "statistics": None,
        "accuracy": "",
        "noParticiple": "1",
        "searchRange": None,
        "noWd": True,
        "cnum": "001",
        "condition": [
            {
                "fieldName": "categorynum",
                "equal": None,
                "notEqual": None,
                "equalList": [category_num],
                "notEqualList": None,
                "isLike": True,
                "likeType": 2,
                "noWd": True,
            }
        ],
        "time": [],
    }


def _extract_content_from_html(html: str) -> Optional[str]:
    """从 HTML 提取正文内容"""
    if not html or len(html) < 1000:
        return None

    # 1. 提取所有 h1
    h1_texts = re.findall(r"<h1[^>]*>([^<]+)</h1>", html)
    h1_block = "\n".join(t.strip() for t in h1_texts if t.strip()) if h1_texts else ""

    # 2. 提取内容区
    content = None
    selectors = [
        r'<div[^>]*class=["\'][^"\']*epoint-article-content[^"\']*["\'][^>]*>(.+?)</div>',
        r'<div[^>]*id=["\']mainContent["\'][^>]*>(.+?)</div>',
        r'<div[^>]*class=["\'][^"\']*epoint-article[^"\']*["\'][^>]*>(.+?)</div>',
    ]
    for pat in selectors:
        m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
        if m:
            text = re.sub(r"<[^>]+>", "\n", m.group(1))
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) > 100:
                content = text
                break

    # 3. Fallback: 提取 body 中所有文本 (去脚本和样式)
    if not content:
        body_match = re.search(r"<body[^>]*>(.+?)</body>", html, re.DOTALL | re.IGNORECASE)
        if body_match:
            text = re.sub(r"<script[^>]*>.*?</script>", "", body_match.group(1), flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "\n", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            # 过滤掉明显是导航/噪音
            if len(text) > 200:
                content = text

    if h1_block or content:
        return (h1_block + "\n\n" + content).strip() if content else h1_block

    return None


def _extract_project_no(content: str) -> Optional[str]:
    """从正文提取项目编号"""
    if not content:
        return None
    patterns = [
        r"项目编号[：:\s]*([A-Z0-9\-]{10,})",
        r"项目编号[：:\s]*(\d{10,})",
        r"项目编码[：:\s]*([A-Z0-9\-]{6,})",
        r"招标编号[：:\s]*([A-Z0-9\-]{8,})",
    ]
    for pat in patterns:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def fetch_list(category_num: str, page_num: int = 1, date_start: str = "", date_end: str = "") -> List[Dict[str, Any]]:
    """采集列表页，返回原始 records 列表"""
    payload = _build_api_payload(category_num, page_num, date_start, date_end)
    resp = _curl_post(API_URL, payload)

    if not resp or resp.get("code") != 200:
        print(f"  ❌ {category_num} p{page_num}: API 返回 code={resp.get('code') if resp else 'NO'}")
        return []

    # 响应结构: {code:200, content: "json string", ...}
    content_str = resp.get("content", "{}")
    try:
        content_parsed = json.loads(content_str)
    except json.JSONDecodeError:
        print(f"  ❌ {category_num} p{page_num}: content 解析失败")
        return []

    result = content_parsed.get("result", {})
    records = result.get("records", [])
    total = result.get("totalcount", 0)

    print(f"  📄 {category_num} p{page_num}: {len(records)}条 (total={total})")

    return records


def fetch_all_pages(category_num: str, date_start: str = "", date_end: str = "") -> List[Dict[str, Any]]:
    """采集某类别所有页"""
    all_records = []
    page = 1
    while page <= 10:  # 最多 10 页保护
        records = fetch_list(category_num, page, date_start, date_end)
        if not records:
            break
        all_records.extend(records)
        if len(records) < 50:  # 最后一页
            break
        page += 1
    return all_records


def parse_record_to_dict(record: Dict[str, Any], category_num: str) -> Dict[str, Any]:
    """把 API record 转换成标准化的项目字典"""
    title = record.get("title", "").replace("<em>", "").replace("</em>", "")
    infoid = record.get("infoid", "")
    catnum = record.get("categorynum", category_num)
    pub_date = record.get("infodate", "")[:10] if record.get("infodate") else ""

    # 构造 detail URL
    if infoid:
        trade_id = "014005" if catnum.startswith("014005") else "014001"
        url = f"{BASE_URL}/trade/{trade_id}/{infoid}?categoryNum={catnum}"
    else:
        url = ""

    return {
        "title": title,
        "url": url,
        "category": catnum,
        "publish_date": pub_date,
        "info_type": _infer_info_type(catnum),
        "infoid": infoid,
    }


def _infer_info_type(catnum: str) -> str:
    """根据 categoryNum 推断 info_type"""
    mapping = {
        "014001019": "招标计划",
        "014001001": "招标公告",
        "014001002": "答疑补遗",
        "014001003": "中标候选人",
        "014001004": "中标结果",
        "014005001": "采购公告",
        "014005002": "变更公告",
        "014005004": "采购结果",
    }
    # 截前 9 位
    prefix9 = catnum[:9] if len(catnum) >= 9 else catnum
    return mapping.get(prefix9, "")


def main():
    parser = argparse.ArgumentParser(description="CQGGZY curl 采集器")
    parser.add_argument("--category", help="单个 categoryNum (e.g. 014001001)")
    parser.add_argument("--date", help="单日 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--date-start", help="起始日期")
    parser.add_argument("--date-end", help="结束日期")
    parser.add_argument("--backfill", action="store_true", help="回填模式：8 大类")
    parser.add_argument("--with-details", action="store_true", help="同时采集详情页")
    parser.add_argument("--output", help="输出文件 (JSON)")

    args = parser.parse_args()

    date_start = args.date_start or args.date or ""
    date_end = args.date_end or args.date or ""

    if args.backfill:
        print(f"🚀 回填模式：8 大类")
        print(f"📅 日期范围：{date_start or '(不限制)'} ~ {date_end or '(不限制)'}")
        all_items = []
        for cat in CATEGORY_WHITELIST.keys():
            records = fetch_all_pages(cat, date_start, date_end)
            print(f"   {cat} → {len(records)}条 (raw)")
            for r in records:
                item = parse_record_to_dict(r, cat)
                all_items.append(item)
        print(f"\n📊 总计：{len(all_items)}条 (raw)")

    elif args.category:
        print(f"🔍 采集类别：{args.category}")
        records = fetch_all_pages(args.category, date_start, date_end)
        all_items = [parse_record_to_dict(r, args.category) for r in records]
        print(f"📊 共 {len(all_items)}条")

    else:
        parser.print_help()
        return

    # 详情采集
    if args.with_details and all_items:
        print(f"\n🔍 采集详情 ({len(all_items)}条)...")
        for item in all_items:
            url = item.get("url", "")
            if not url:
                continue
            html = _curl_get(url)
            if not html:
                print(f"  ❌ {item['title'][:30]}: 详情页失败")
                continue
            content = _extract_content_from_html(html)
            if content and len(content) > 50:
                item["full_content"] = content
                item["content_preview"] = content[:300]
                project_no = _extract_project_no(content)
                if project_no:
                    item["project_no"] = project_no
                print(f"  ✅ {item['title'][:30]} ({len(content)}字)")
            else:
                print(f"  ⚠️  {item['title'][:30]}: 详情页空")

    # 输出
    if args.output:
        Path(args.output).write_text(json.dumps(all_items, ensure_ascii=False, indent=2))
        print(f"\n💾 已保存到 {args.output}")
    else:
        print(f"\n📋 前 3 条预览：")
        for item in all_items[:3]:
            print(f"  • {item.get('title', '')[:50]}")
            print(f"    URL: {item.get('url', '')[:80]}")
            print(f"    Date: {item.get('publish_date', '')}")


if __name__ == "__main__":
    main()