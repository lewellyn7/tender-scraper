"""重庆市公共资源交易网采集器 V3 - 继承 BaseCrawler
- 复用通用字段提取、日期解析、附件解析
- URL 缓存避免重复采集
- 并行采集列表页 + 详情页
"""

import asyncio
import os
from datetime import datetime
import json
import random
import re
from typing import List

import httpx
from loguru import logger

from app.crawlers.base import BaseCrawler
from app.database import get_db
from app.models.tender import TenderInfo
from app.services.keywords_service import KeywordsService
from app.utils.summarize import summarize as make_summary
from app.utils.project_linker import normalize_project_name, extract_project_no


class CQGGZYCrawlerV2(BaseCrawler):
    """重庆市公共资源交易网采集器 — 继承 BaseCrawler"""

    BASE_URL = "https://www.cqggzy.com"

    # 新版 URL (2026-06 改版后) — pageNum= + date=3m
    # 工程招投标
    ENGINEERING_URL = "https://www.cqggzy.com/trade/014001?categoryNum=014001001"
    # 政府采购
    GOV_PURCHASE_URL = "https://www.cqggzy.com/trade/014005?categoryNum=014005001"

    # 分类采集 URL 映射（支持多 categoryNum）
    LIST_URLS = {
        "engineering_notice":    ("https://www.cqggzy.com/trade/014001", "014001001"),
        "engineering_plan":      ("https://www.cqggzy.com/trade/014001", "014001019"),
        "engineering_qa":        ("https://www.cqggzy.com/trade/014001", "014001002"),
        "engineering_candidate":  ("https://www.cqggzy.com/trade/014001", "014001003"),
        "engineering_result":    ("https://www.cqggzy.com/trade/014001", "014001004"),
        "engineering_terminate": ("https://www.cqggzy.com/trade/014001", "014001021"),
        "gov_purchase_notice":   ("https://www.cqggzy.com/trade/014005", "014005001"),
        "gov_purchase_change":   ("https://www.cqggzy.com/trade/014005", "014005002"),
        "gov_purchase_result":   ("https://www.cqggzy.com/trade/014005", "014005004"),
    }

    INFO_TYPE_MAP = {
        "engineering_notice":    "招标公告",
        "engineering_plan":      "招标计划",
        "engineering_qa":        "答疑补遗",
        "engineering_candidate": "中标候选人公示",
        "engineering_result":    "中标结果公示",
        "engineering_terminate": "终止公告",
        "gov_purchase_notice":   "采购公告",
        "gov_purchase_change":   "变更公告",
        "gov_purchase_result":   "采购结果公告",
    }

    async def fetch_list(
        self, category: str = "gov_purchase", page_num: int = 1,
        start_date: datetime = None, end_date: datetime = None
    ) -> List[TenderInfo]:
        """"采集单个列表页，可按日期范围过滤

        Args:
            category: gov_purchase | engineering
            page_num: 页码
            start_date: 起始日期（只采集此日期之后的项目）
            end_date: 结束日期（只采集此日期之前的项目）
        """
        return await self._fetch_list_page(category, page_num, start_date, end_date)

    async def _fetch_list_via_api(
        self, page, category: str, page_num: int,
        start_date=None, end_date=None
    ) -> List["TenderInfo"]:
        """通过 API 获取列表数据（支持分页）

        POST /api/v2/search-engine-page 返回结构化 JSON，支持 pn/rn 分页。
        在 Playwright 页面上下文内执行以保持 cookie 状态。
        """
        try:
            # 构造 API 请求
            # category → categoryNum 映射
            cat_map = {
                "gov_purchase": "014005001",
                "engineering": "014001001",
            }
            cat_map.update({k: v[1] for k, v in self.LIST_URLS.items()})
            category_num = cat_map.get(category, "014005001" if "gov" in category else "014001001")
            pn = page_num - 1  # API 页码从 0 开始
            rn = 50  # 每页条数（增大减少页间重叠）

            # 日期范围
            sdt = start_date.strftime('%Y-%m-%d') if start_date else ""
            edt = end_date.strftime('%Y-%m-%d') if end_date else ""

            api_payload = {
                "token": "",
                "pn": pn,
                "rn": rn,
                "sdt": sdt,
                "edt": edt,
                "wd": "",
                "inc_wd": "",
                "exc_wd": "",
                "fields": "",
                # newid 排序方向: 0=按 newid 倒序（最新优先，符合采集场景预期）,
                #               1=按 newid 升序（最旧优先，2026-06-09 调研确认此前误用此值，
                #                  导致 pn=0 返回 2019-2020 老数据，6-6~6-9 最新项目永远在 pn=0
                #                  远端，列表采集器只能靠翻大量页才能接近，6 天后仍采不到 6-9）
                "sort": '{"istop":"0","ordernum":"0","newid":"0"}',
                "ssort": "",
                "cl": 10000,
                "terminal": "",
                "highlights": "",
                "unionCondition": [],
                "accuracy": "",
                "noParticiple": "1",
                "noWd": True,
                "condition": [
                    {
                        "fieldName": "categorynum",
                        "equal": category_num,
                        "isLike": True,
                        "likeType": 2
                    }
                ]
            }

            import json
            # 使用 json.dumps 确保 payload 精确序列化（避免 Python None → JSON null 的不一致问题）
            payload_json = json.dumps(api_payload, ensure_ascii=False)
            api_response = await page.evaluate(
                """async (payloadJson) => {
                    const resp = await fetch('/api/v2/search-engine-page', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: payloadJson
                    });
                    return await resp.json();
                }""",
                payload_json
            )

            if not api_response or api_response.get('code') != 200:
                return []

            content_str = api_response.get('content', '{}')
            try:
                content_parsed = json.loads(content_str)
            except (json.JSONDecodeError, TypeError):
                logger.debug(f"  API content 解析失败")
                return []

            result_data = content_parsed.get('result', {})
            items = result_data.get('records', []) if isinstance(result_data, dict) else []
            total = result_data.get('totalcount', 0)
            logger.debug(f"  API 返回: total={total}, this_page={len(items)}")
            if not items:
                return []

            tender_type = self.INFO_TYPE_MAP.get(category, "政府采购" if category == "gov_purchase" else "工程建设")
            results = []
            seen_urls = set()  # 2026-06-08 Bug 1 修复：去重 list API 返回的重复 url

            for item in items:
                title = item.get('title', '').strip()
                if len(title) < 5:
                    continue

                # 日期
                infodate = item.get('infodate', '') or item.get('webdate', '') or ''
                pub_date = None
                if infodate and len(infodate) >= 10:
                    try:
                        pub_date = datetime.strptime(infodate[:19], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        pass

                # 详情页 URL（2026-06 新版）：infoid 为真正的项目 UUID，syscollectguid 是分类级 ID（多项目共用）
                # 优先使用 infoid，若无则降级到 syscollectguid
                infoid = item.get('infoid', '') or item.get('syscollectguid', '')
                raw_catnum = item.get('categorynum', '') or ''
                # categorynum 可能是 12 位（如 014001001007），直接用完整值作为 categoryNum
                category_num = raw_catnum
                # 判断是工程还是采购（trade id 在 URL 中）
                if category_num.startswith('014001') or category.startswith('engineering'):
                    trade_id = '014001'
                else:
                    trade_id = '014005'
                if infoid:
                    full_url = f"{self.BASE_URL}/trade/{trade_id}/{infoid}?categoryNum={category_num}"
                else:
                    full_url = f"{self.BASE_URL}/trade/{trade_id}?infoId={item.get('infoid', '')}"

                tender = TenderInfo(
                    title=title,
                    url=full_url,
                    category=tender_type,
                    source_url=full_url,
                    publish_date_raw=infodate,
                    tender_type=tender_type,
                    business_type=self._infer_business_type_by_url(full_url),  # 2026-06-05 P0-1
                    scraped_by=self.version,
                )
                # 2026-06-08 Bug 1 修复：去重同一 url，list API 在多个 page 返回中可能重复
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                if pub_date:
                    tender.publish_date = pub_date

                # info_type 从 URL 的 categoryNum 前 9 位提取（2026-06-02 用户分类标准）
                import re as _re
                _m = _re.search(r'categoryNum=(\d+)', full_url)
                if _m:
                    _prefix9 = _m.group(1)[:9]
                    _CATEGORY_INFO_TYPE = {
                        '014001019': '招标计划',
                        '014001001': '招标公告',
                        '014001002': '答疑补遗',
                        '014001003': '中标候选人公示',
                        '014001004': '中标结果公示',
                        '014001021': '终止公告',
                        '014005001': '采购公告',
                        '014005002': '变更公告',
                        '014005004': '采购结果公告',
                    }
                    tender.info_type = _CATEGORY_INFO_TYPE.get(_prefix9, '')

                # 从 content 提取全文
                # 2026-06-08 改造：API 改版后不再返回 content 字段（参见 AGENTS.md 6-3 教训）
                # 修复点：raw_content 为空时不要用 title 兑底填充 content_preview
                # 原因：会导致 16.7% 项目摘要与 title 重复（“未清洗”表现）
                # 正确逻辑：raw_content 有就提 full_content + 截取 content_preview，raw_content 无就留空（由详情阶段回填）
                raw_content = item.get('content', '') or ''
                if raw_content:
                    import re as re_module
                    clean = re_module.sub(r'<[^>]+>', '', raw_content)
                    clean = re_module.sub(r'\s+', ' ', clean).strip()
                    from app.utils.clean_noise import make_content_preview
                    tender.full_content = clean  # 保留完整内容，不截断
                    tender.content_preview = make_content_preview(clean, tender.title)
                # else: content_preview 保持默认值空字符串
                # 详情阶段 crawler_fn 会回填；upsert_projects 的 protected_cols={full_content, content_preview}
                # 保证列表阶段写空不会冲掉详情阶段已回填的值


                # 2026-06-12 P0 修复: 列表阶段调 KeywordsService + cp 兜底拼装
                # 修 2 永久 BUG:
                #   1. keywords_matched 99.1% 空 (采集器从未调 KeywordsService)
                #   2. content_preview 86.5% 空 (raw_content 永远空, 留空等详情, 详情可能失败)
                try:
                    from app.services.keywords_service import KeywordsService
                    _text = tender.title + " " + (raw_content or "")
                    _match = KeywordsService().match(_text)
                    if _match:
                        _inc = _match.get("include", [])
                        _exc = _match.get("exclude", [])
                        if _inc and not _exc:
                            tender.keywords_matched = [k["keyword"] for k in _inc]
                except Exception as _kw_e:
                    logger.debug(f"  KeywordsService 失败 (忽略): {_kw_e}")

                # cp 兜底: raw_content 空 + 详情没抓 (6-10 BUG 验证) 时, 用 title+其他字段拼
                if not tender.content_preview and tender.title:
                    _cp_parts = [tender.title]
                    if tender.info_type:
                        _cp_parts.append(f"[{tender.info_type}]")
                    if hasattr(tender, 'budget') and tender.budget:
                        _cp_parts.append(f"预算: {tender.budget}")
                    if hasattr(tender, 'deadline') and tender.deadline:
                        _cp_parts.append(f"截止: {tender.deadline}")
                    if hasattr(tender, 'project_no') and tender.project_no:
                        _cp_parts.append(f"项目编号: {tender.project_no}")
                    tender.content_preview = "\n".join(_cp_parts)[:500]

                results.append(tender)

            logger.debug(f"  API 获取 {len(results)} 条（pn={pn}）")
            return results

        except Exception as e:
            logger.debug(f"  API 获取失败，回退到 NUXT: {e}")
            return []


    async def fetch_lists_parallel(
        self, category: str = "gov_purchase", pages: List[int] = None,
        start_date: datetime = None, end_date: datetime = None
    ) -> List[TenderInfo]:
        """并行采集多个列表页（可按日期范围过滤）"""
        if pages is None:
            pages = list(range(1, 6))
        tasks = [self._fetch_list_page(category, p, start_date, end_date) for p in pages]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_items = []
        for r in results:
            if isinstance(r, list):
                all_items.extend(r)
            elif isinstance(r, Exception):
                logger.warning(f"列表页采集异常: {r}")
        logger.info(f"✅ 并行列表页采集完成：{len(all_items)} 条")
        return all_items

    async def _fetch_list_page(
        self, category: str, page_num: int,
        start_date: datetime = None, end_date: datetime = None
    ) -> List[TenderInfo]:
        """内部：采集单个列表页，可按日期范围过滤
        
        新版 CQGGZY (2025-2026 重构) 使用 NUXT SSR + SPA 架构。
        列表数据嵌入在 #__NUXT_DATA__ 中，格式为 Nuxt JSON 索引格式。
        列表项提取自 NUXT_DATA 而非 DOM。
        """
        results = []
        # 2026-06 改版：pageNum= + date=3m
        if category == "gov_purchase":
            base_url = "https://www.cqggzy.com/trade/014005"
            url = f"{base_url}?pageNum={page_num}&date=3m&categoryNum=014005001"
            tender_type = "政府采购"
        elif category == "engineering":
            base_url = "https://www.cqggzy.com/trade/014001"
            url = f"{base_url}?pageNum={page_num}&date=3m&categoryNum=014001001"
            tender_type = "工程建设"
        else:
            base, cat_num = self.LIST_URLS.get(category, ("https://www.cqggzy.com/trade/014005", "014005001"))
            url = f"{base}?pageNum={page_num}&date=3m&categoryNum={cat_num}"
            # 政府采购类 vs 工程建设类
            tender_type = "政府采购" if category.startswith("gov_purchase") else "工程建设"
        page = None

        try:
            page = await self.browser.new_page()
            logger.info(f"📑 采集 {tender_type} 列表 第{page_num}页")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self._smart_wait()

            # 新版架构：优先通过 API 获取（支持分页），回退到 NUXT_DATA
            api_items = await self._fetch_list_via_api(page, category, page_num, start_date, end_date)
            if api_items:
                results.extend(api_items)
                return results

            # 回退：解析 NUXT_DATA
            nuxt_data = await page.evaluate('document.querySelector("#__NUXT_DATA__")?.textContent || ""')
            if not nuxt_data:
                logger.warning("⚠️ 未找到 NUXT_DATA")
                return results
            # NUXT 数据格式：日期字符串后紧跟标题，如 },"2026-05-29 23:56:23","标题",...
            # 使用正则直接匹配日期和标题对
            date_title_pattern = re.compile(r'\},"((?:2026|2025|2024)-\d{2}-\d{2} \d{2}:\d{2}:\d{2})","([^"]{10,100})"')
            
            seen_titles = set()
            for match in date_title_pattern.finditer(nuxt_data):
                date_str = match.group(1)
                title = match.group(2).strip()
                
                if len(title) < 10 or title in seen_titles:
                    continue
                seen_titles.add(title)

                # 解析日期
                try:
                    pub_date = datetime.strptime(date_str[:19], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pub_date = None

                # 日期过滤
                if start_date and pub_date and pub_date < start_date:
                    continue
                if end_date and pub_date and pub_date > end_date:
                    continue

                # infoId 暂未提取，暂用占位 URL（详情页通过点击触发 NUXT 加载）
                full_url = f"{self.BASE_URL}/trade/014005?title={title[:20]}" if category.startswith("gov_purchase") else f"{self.BASE_URL}/trade/014001?title={title[:20]}"

                tender = TenderInfo(
                    title=title,
                    url=full_url,
                    category=tender_type,
                    source_url=url,
                    publish_date_raw=date_str,
                    tender_type=tender_type,
                    scraped_by=self.version,
                )
                if pub_date:
                    tender.publish_date = pub_date

                # NUXT fallback URL 无 categoryNum，只设 trade 级默认
                # 2026-06-02 用户分类：014001=招标公告（最常见），014005=采购公告
                tender.info_type = "招标公告" if tender_type == "工程建设" else "采购公告"

                results.append(tender)

            logger.info(f"✅ 列表页第{page_num}页（NUXT）：{len(results)} 条")
            return results
        except Exception as e:
            logger.error(f"❌ 列表页第{page_num}页失败：{e}")
            return results
        finally:
            if page:
                await page.close()

    async def fetch_detail(self, tender: TenderInfo) -> TenderInfo:
        """采集详情页（URL 是否已访问由 fetch_list 统一管理）"""
        return await self._fetch_detail_page(tender)

    async def fetch_details_parallel(
        self, tenders: List[TenderInfo], concurrency: int = 5
    ) -> List[TenderInfo]:
        """并行采集多个详情页"""
        return await self.fetch_details_batch(tenders, max_concurrent=concurrency)

    async def _fetch_detail_page(self, tender: TenderInfo) -> TenderInfo:
        """详情页采集：SPA 导航到 UUID URL 获取完整正文。

        策略：
        1. 先访问列表页建立 SPA context
        2. history.pushState 触发 Vue Router 导航到详情页
        3. 等待正文渲染，提取内容
        """
        page = None
        try:
            page = await self.browser.new_page()

            # 从 URL 解析 trade_id 和 categoryNum
            # 格式: /trade/{trade_id}/{uuid}?categoryNum={catnum}
            parsed = self._parse_detail_url(tender.url)
            trade_id = parsed.get('trade_id', '014001')
            category_num = parsed.get('category_num', '')
            uuid_val = parsed.get('uuid', '')

            if not uuid_val:
                logger.debug(f"  详情页无 UUID URL: {tender.url}")
                return tender

            # Step 1: 直接导航到详情页（用 6位 categoryNum，网站接受）
            detail_url = f"{self.BASE_URL}/trade/{trade_id}/{uuid_val}?categoryNum={category_num}"
            await page.goto(detail_url, wait_until="networkidle", timeout=45000)
            await asyncio.sleep(2)
            await self._extract_content(page, tender)


            # Step 3: 等待正文加载
            try:
                await page.wait_for_selector(
                    '.epoint-article-content, #mainContent, .content, .article, '
                    '#content, .text-content, .zw_c, .con_r',
                    timeout=10000
                )
            except Exception:
                pass

            # 提取正文
            content = None
            selectors = [
                '.epoint-article-content', '#mainContent', '.epoint-article',
                '.content', '.article', '.detail-content', '#content',
                '.main-content', '.text-content', '.zw_c', '.con_r',
            ]
            for sel in selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        content = await el.inner_text()
                        if content and len(content) > 100:
                            break
                except Exception:
                    pass

            # 备用：提取 body 正文区（去掉导航噪音）
            if not content or len(content) < 100:
                body = await page.inner_text('body')
                body = re.sub(r'^APP下载.*?当前位置：.*?\s*', '', body, flags=re.DOTALL)
                body = re.sub(r'国家部委网站.*$', '', body, flags=re.DOTALL)
                content = body.strip()

            # 2026-06-10 修复: 抓所有 <h1> 标签内容（项目编号常在 title 下一行的 h1 里）
            # CQGGZY 详情页结构: <h1>title</h1><h1>项目编号：XXX</h1>
            # selectors 列表抓的是正文区, 不含 H1 块, 会丢失项目编号
            try:
                h1_texts = await page.eval_on_selector_all(
                    'h1',
                    'els => els.map(e => e.innerText.trim()).filter(t => t.length > 0)'
                )
                if h1_texts:
                    h1_block = '\n'.join(h1_texts)
                    content = (h1_block + '\n' + (content or '')).strip()
                    logger.debug(f"  H1 块: {h1_block[:100]}")
            except Exception as h1_err:
                logger.debug(f"  H1 抓取失败 {tender.url}: {h1_err}")

            if content and len(content) > 50 and '暂无内容' not in content:
                # 2026-06-05: 使用 clean_noise 进一步去噪 + 识别空详情页
                from app.utils.clean_noise import clean_text, is_empty_page, make_content_preview
                cleaned = clean_text(content)
                if is_empty_page(content) or len(cleaned) < 30:
                    # 整页只有 chrome 或空详情页 — 不入库
                    logger.debug(f"  详情页空(仅chrome): {tender.url}")
                else:
                    tender.full_content = cleaned
                    # 2026-06-08 修复: 同步生成 content_preview, 不依赖后续 fallback
                    tender.content_preview = make_content_preview(cleaned, tender.title)
                    # 2026-06-09 修复: CQGGZY 详情页同步提取项目编号（CCGP 已在 ccgp.py:311 调用，CQGGZY 漏了）
                    tender.project_no = extract_project_no(tender.title, cleaned) or ""
                    logger.debug(f"  详情页成功: {tender.title[:30]} ({len(cleaned)}字)")
            else:
                logger.debug(f"  详情页空/无效: {tender.url}")

            return tender
        except Exception as e:
            logger.warning(f"  详情页失败 {tender.url}: {e}")
            return tender
        finally:
            if page:
                await page.close()

    def _parse_detail_url(self, url: str) -> dict:
        """从详情页 URL 解析 trade_id / uuid / categoryNum

        2026-06-08 修复: 014005 政府采购 2025-2026 重构后采用 19 位数字 ID
        (e.g. /trade/014005/1638974459430088704) 而非标准 UUID 格式
        (8-4-4-4-12). 实际访问测试: HTTP 200 + 正常 HTML 返回, 详情页能打开.
        但 /trade/014005?title=... 是搜索页 URL, 不在此修复范围.

        识别优先级:
        1. 标准 UUID (014001 仍用)  → 8-4-4-4-12 hex
        2. 数字 ID (014005 重构后)  → 16+ 位十进制 (可带 _分页后缀 如 164xxx_1)
        3. 都匹配不上 → uuid='', 主路径跳过
        """
        result = {'trade_id': '014001', 'uuid': '', 'category_num': ''}
        try:
            # 1) 标准 UUID (014001 仍用)
            uuid_match = re.search(
                r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', url
            )
            if uuid_match:
                result['uuid'] = uuid_match.group(1)
            else:
                # 2) 数字 ID (014005 重构后, 16+ 位十进制, 可带 _分页)
                # 实际: /trade/014005/164xxx_1?categoryNum=... 也合法
                num_match = re.search(r'/trade/\d+/(\d{16,}(?:_\d+)?)(?:[?/]|$)', url)
                if num_match:
                    result['uuid'] = num_match.group(1)
            # trade_id 解析 (014001 / 014005)
            tid_match = re.search(r'/trade/(01400[15])(?:/|\?|$)', url)
            if tid_match:
                result['trade_id'] = tid_match.group(1)
            # categoryNum
            cat_match = re.search(r'[?&]categoryNum=([0-9]+)', url)
            if cat_match:
                result['category_num'] = cat_match.group(1)
        except Exception:
            pass
        return result


    async def _extract_content(self, page, tender: TenderInfo) -> None:
        """提取正文内容（滚动加载完整正文）"""
        # 先尝试滚动内容区触发懒加载
        try:
            for _ in range(8):
                await page.evaluate(
                    """() => {
                        const el = document.querySelector('.content,.article,.detail-content,#content,.main-content,.zw_c,.con_r');
                        if (el) { el.scrollTop = el.scrollHeight; }
                        else { window.scrollTo(0, document.body.scrollHeight); }
                    }"""
                )
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # 等待正文区加载
        try:
            await page.wait_for_selector('.zw_c, .con_r, .content, #content', timeout=5000)
        except Exception:
            pass

        selectors = [
            ".epoint-article-content", "#mainContent", ".epoint-article",
            ".content", ".article", ".detail-content", "#content",
            ".main-content", ".text-content", ".news-content",
            ".TREmpty", ".zw_c", ".con_r",
        ]
        for selector in selectors:
            try:
                elem = await page.query_selector(selector)
                if elem:
                    # 滚动该元素到底部
                    try:
                        await page.evaluate(
                            "(el) => { el.scrollTop = el.scrollHeight; }",
                            elem
                        )
                        await asyncio.sleep(0.3)
                    except Exception:
                        pass
                    full = await elem.inner_text()
                    if len(full) > 20:
                        from app.utils.clean_noise import make_content_preview
                        tender.full_content = full
                        tender.content_preview = make_content_preview(full, tender.title)
                        logger.info(f"  ✅ 正文提取成功 ({len(full)} 字)")
                        return
            except Exception:
                continue

        # fallback: body 提取（过滤导航噪音）
        try:
            text = await page.inner_text("body")
            lines, in_content = [], False
            skip_kw = ["首 页", "重要通知", "交易信息", "当前访问", "收藏",
                       "您当前的位置", "版权所有", "技术支持", "<delete_file>"]
            for line in text.split("\n"):
                line = line.strip()
                if any(s in line for s in skip_kw):
                    continue
                if "项目" in line or "采购" in line or "招标" in line:
                    in_content = True
                if in_content and len(line) > 20:
                    lines.append(line)
            full = "\n".join(lines)
            if len(full) > 20:
                from app.utils.clean_noise import make_content_preview
                tender.full_content = full
                tender.content_preview = make_content_preview(full, tender.title)
        except Exception:
            pass

    # ─── 站点特征提取 ────────────────────────────────────────────

    async def _extract_region(self, page) -> str:
        """提取所属区域"""
        try:
            text = await page.inner_text("body")
            districts = [
                "渝中区", "大渡口区", "江北区", "沙坪坝区", "九龙坡区", "南岸区",
                "北碚区", "渝北区", "巴南区", "万州区", "涪陵区", "永川区",
                "合川区", "江津区", "綦江区", "长寿区", "大足区", "璧山区",
                "铜梁区", "潼南区", "荣昌区", "黔江区", "两江新区",
            ]
            for district in districts:
                if district in text:
                    logger.debug(f"  ✅ 区域: {district}")
                    return district
        except Exception:
            pass
        return "重庆市"

    async def _extract_business_type(self, page) -> str:
        """提取业务类型"""
        try:
            url = page.url
            text = (await page.inner_text("body"))[:500]
            if "014005" in url or "order" in url:
                return "政府采购"
            elif "014001" in url or "bidding" in url:
                return "工程招投标"
            if "采购" in text:
                return "政府采购"
            if "招标" in text:
                return "工程招投标"
        except Exception:
            pass
        return "政府采购"

    @staticmethod
    def _infer_business_type_by_url(url: str) -> str:
        """纯 URL 推理业务类型（列表阶段用，无 page 实例）
        2026-06-05 复盘 P0-1 修复：原 _extract_business_type 需 page，列表 API 模式无 page，
        导致 11307/11307 records 业务类型 NULL。"""
        if "014005" in url or "order" in url:
            return "政府采购"
        if "014001" in url or "bidding" in url:
            return "工程招投标"
        return ""

    def _extract_info_type_by_url(self, url: str) -> str:
        """根据 URL 路径提取信息类型（优先级最高）
        2026-06-02 与用户核对：014005002=变更公告（不是答疑变更）
        """
        # 政府采购
        if "/014005/014005001/" in url:
            return "采购公告"
        if "/014005/014005004/" in url:
            return "采购结果公告"
        if "/014005/014005002/" in url:
            return "变更公告"
        if "/014005/014005008/" in url:
            return "单一来源公示"
        # 工程招投标
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
        return ""

    def _is_collectible_info_type(self, info_type: str) -> bool:
        """判断该信息类型是否应该采集（不采集的返回 False）"""
        NO_COLLECT = {"单一来源公示", "邀标信息", "合同签订基本信息公示", "合同变更基本信息公示"}
        return info_type not in NO_COLLECT

    def _extract_date_from_url(self, url: str):
        """从 URL 路径提取日期（格式: /YYYYMMDD/），返回 datetime 或 None"""
        import re
        m = re.search(r'/(\d{4})(\d{2})(\d{2})/', url)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        return None

    async def _extract_info_type(self, page) -> str:
        """提取信息类型：优先 URL 推断，再页面内容兜底"""
        try:
            url = page.url
            itype = self._extract_info_type_by_url(url)
            if itype:
                logger.debug(f"  ✅ 信息类型(URL): {itype}")
                return itype
            text = (await page.inner_text("body"))[:2000]
            patterns = [
                ("中标结果公告", "中标结果公告"),
                ("中标候选人公示", "中标候选人公示"),
                ("结果公告", "结果公告"),
                ("采购意向", "采购意向"),
                ("招标公告", "招标公告"),
                ("答疑补遗", "答疑补遗"),
                ("变更公告", "变更公告"),
            ]
            for pattern, itype in patterns:
                if pattern in text:
                    logger.debug(f"  ✅ 信息类型(内容): {itype}")
                    return itype
        except Exception:
            pass
        return "招标公告"

    # ─── 工具方法 ────────────────────────────────────────────────

    async def _smart_wait(self) -> None:
        """智能随机等待 (0.3-0.8s)"""
        await asyncio.sleep(0.3 + random.random() * 0.5)
