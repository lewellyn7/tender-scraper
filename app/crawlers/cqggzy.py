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
    # 新版 URL (2025-2026 重构后的交易网)
    GOV_PURCHASE_URL = "https://www.cqggzy.com/trade/014005?categoryNum=014005001"
    ENGINEERING_URL = "https://www.cqggzy.com/trade/014001?categoryNum=014001001"

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
        # 根据 page_num 构建 URL（新版 SPA 支持分页参数）
        if category == "gov_purchase":
            base_url = "https://www.cqggzy.com/trade/014005"
            url = f"{base_url}?categoryNum=014005001&page={page_num}"
        else:
            base_url = "https://www.cqggzy.com/trade/014001"
            url = f"{base_url}?categoryNum=014001001&page={page_num}"
        tender_type = "政府采购" if category == "gov_purchase" else "工程建设"
        page = None

        try:
            page = await self.browser.new_page()
            logger.info(f"📑 采集 {tender_type} 列表 第{page_num}页")
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await self._smart_wait()

            # 新版架构：从 NUXT_DATA 提取列表数据
            nuxt_data = await page.evaluate('document.querySelector("#__NUXT_DATA__")?.textContent || ""')
            if not nuxt_data:
                logger.warning("⚠️ 未找到 NUXT_DATA")
                return results

            # 解析 NUXT JSON 格式并提取 tender 条目
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
                full_url = f"{self.BASE_URL}/trade/014005?title={title[:20]}" if category == "gov_purchase" else f"{self.BASE_URL}/trade/014001?title={title[:20]}"

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
        """内部：采集单个详情页

        新版 CQGGZY SPA 架构：从列表页 NUXT_DATA 中直接提取 项目概况 内容。
        列表页加载时已包含所有 tender 的完整内容，点击按钮后可从 NUXT_DATA 提取。
        """
        page = None
        try:
            page = await self.browser.new_page()
            logger.info(f"📄 采集详情页：{tender.title[:30]}...")

            # 确定列表页 URL
            list_url = self.GOV_PURCHASE_URL if tender.tender_type == "政府采购" else self.ENGINEERING_URL

            # 加载列表页
            await page.goto(list_url, wait_until="networkidle", timeout=60000)
            await self._smart_wait()

            # 点击对应标题的按钮，触发 NUXT 加载完整内容
            clicked = await page.evaluate(
                """(title) => {
                    const buttons = Array.from(document.querySelectorAll("button.text-left"));
                    for (const btn of buttons) {
                        if (btn.textContent.trim() === title) {
                            btn.dispatchEvent(new MouseEvent("click", {bubbles: true}));
                            return true;
                        }
                    }
                    return false;
                }""",
                tender.title
            )

            if clicked:
                await page.wait_for_timeout(3000)
                logger.debug(f"  ✅ 点击成功，加载详情内容")
            else:
                logger.warning(f"  ⚠️ 未找到对应标题的按钮")

            # 从 NUXT_DATA 提取完整 content
            nuxt_data = await page.evaluate('document.querySelector("#__NUXT_DATA__")?.textContent || ""')

            if nuxt_data:
                title_anchor = f'"{tender.title}"'
                title_pos = nuxt_data.find(title_anchor)
                if title_pos > 0:
                    search_chunk = nuxt_data[title_pos:title_pos + 10000]
                    gp_pos = search_chunk.find('项目概况')
                    if gp_pos > 0:
                        content_start = gp_pos + 4
                        content_end = content_start + 5000
                        end_markers = ['-->', '二、', '三、', '采购人', '代理机构', '监督管理部门']
                        for marker in end_markers:
                            m_pos = search_chunk.find(marker, content_start)
                            if m_pos > content_start and m_pos < content_start + 6000:
                                content_end = min(content_end, m_pos)
                        
                        tender.full_content = search_chunk[content_start:content_end].strip()
                        logger.debug(f"  ✅ 从 NUXT 提取内容：{len(tender.full_content)} 字符")

            if not tender.full_content:
                await self._extract_content(page, tender)
                logger.debug(f"  📋 回退到 DOM 提取内容：{len(tender.full_content or '')} 字符")

            return tender

        except Exception as e:
            logger.warning(f"⚠️ 详情页采集失败: {e}")
            return tender
        finally:
            if page:
                await page.close()


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
                        tender.full_content = full
                        tender.content_preview = (
                            full[:500] + "..." if len(full) > 500 else full
                        )
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
                tender.full_content = full
                tender.content_preview = full[:500] + "..." if len(full) > 500 else full
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

    def _extract_info_type_by_url(self, url: str) -> str:
        """根据 URL 路径提取信息类型（优先级最高）"""
        # 政府采购
        if "/014005/014005001/" in url:
            return "采购公告"
        if "/014005/014005004/" in url:
            return "采购结果公告"
        if "/014005/014005002/" in url:
            return "答疑变更"
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
