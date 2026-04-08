"""资质自动匹配服务"""

import re
from typing import Any, Dict, List

CATEGORY_KEYWORDS = {
    "建筑": ["建筑", "施工", "装修", "装饰", "钢结构", "幕墙", "消防", "电梯", "空调", "水电", "市政", "园林", "公路", "桥梁", "隧道", "地基", "防水", "防腐", "拆迁", "加固", "监理", "造价", "设计"],
    "IT": ["软件", "系统", "网络", "信息化", "智能化", "安防", "监控", "会议", "广播", "音响", "大屏", "显示", "存储", "服务器", "数据", "云", "安全", "等保", "集成", "运维"],
    "服务": ["物业", "保洁", "保安", "绿化", "餐饮", "酒店", "旅游", "咨询", "代理", "招标", "评估", "审计", "法律", "会计", "培训", "印刷", "租赁"],
    "设备": ["设备", "机械", "车辆", "医疗", "教学", "实验", "科研", "办公", "家具", "厨房", "家电", "LED", "灯具", "电梯", "泵", "阀", "仪表"],
}

LEVEL_KEYWORDS = {
    "特级": ["特级"],
    "一级": ["一级", "壹级"],
    "二级": ["二级", "贰级"],
    "三级": ["三级", "叁级"],
    "甲级": ["甲级"],
    "乙级": ["乙级"],
    "丙级": ["丙级"],
}


class QualificationMatcher:
    """资质自动匹配器"""

    def match(
        self,
        tender: Dict[str, Any],
        qualifications: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        对招标项目的资质要求与已有资质进行匹配

        :param tender: 招标项目信息（含 requirements_text 字段）
        :param qualifications: 已有资质列表
        :return: 匹配结果
        """
        requirements_text = tender.get("requirements_text", "")
        if not requirements_text:
            # 尝试从 title 推断
            requirements_text = tender.get("title", "")

        # 1. 解析资质要求
        required_categories = self._extract_categories(requirements_text)
        required_levels = self._extract_levels(requirements_text)
        missing_qualifications = self._find_missing(requirements_text, qualifications)

        # 2. 匹配已有资质
        matched = []
        partial = []
        for q in qualifications:
            score, reasons = self._score_qualification(q, requirements_text, required_categories, required_levels)
            if score >= 80:
                matched.append({
                    "qualification": q,
                    "score": score,
                    "reasons": reasons,
                    "match_type": "full",
                })
            elif score >= 40:
                partial.append({
                    "qualification": q,
                    "score": score,
                    "reasons": reasons,
                    "match_type": "partial",
                })

        # 3. 按匹配度排序
        matched.sort(key=lambda x: x["score"], reverse=True)
        partial.sort(key=lambda x: x["score"], reverse=True)

        # 4. 汇总评分
        coverage = 0.0
        if required_categories:
            covered_cats = set()
            for m in matched:
                cat = m["qualification"].get("category", "")
                if cat in required_categories:
                    covered_cats.add(cat)
            coverage = len(covered_cats) / len(required_categories) * 100

        return {
            "tender": tender,
            "summary": {
                "total_qualifications": len(qualifications),
                "matched_count": len(matched),
                "partial_count": len(partial),
                "missing_count": len(missing_qualifications),
                "coverage_percent": round(coverage, 1),
                "required_categories": required_categories,
                "required_levels": required_levels,
            },
            "matched": matched,
            "partial": partial,
            "missing": missing_qualifications,
        }

    def _extract_categories(self, text: str) -> List[str]:
        """从资质要求文本中提取资质类别"""
        found = []
        for cat, keywords in CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    if cat not in found:
                        found.append(cat)
                    break
        return found

    def _extract_levels(self, text: str) -> List[str]:
        """从资质要求文本中提取资质等级"""
        found = []
        for level, keywords in LEVEL_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    if level not in found:
                        found.append(level)
                    break
        return found

    def _find_missing(self, text: str, qualifications: List[Dict]) -> List[Dict]:
        """找出缺失的资质要求"""
        required_categories = self._extract_categories(text)
        required_levels = self._extract_levels(text)
        existing_cats = {q.get("category", "") for q in qualifications if q.get("status") == "有效"}

        missing = []
        for cat in required_categories:
            if cat not in existing_cats:
                missing.append({
                    "category": cat,
                    "reason": f"缺少 {cat} 类资质",
                    "suggestion": f"请添加 {cat} 类资质证书",
                })
        return missing

    def _score_qualification(
        self,
        q: Dict,
        requirements_text: str,
        required_categories: List[str],
        required_levels: List[str],
    ) -> tuple:
        """
        计算单项资质与招标要求的匹配评分
        返回 (score: int, reasons: list)
        """
        score = 0
        reasons = []
        q_cat = q.get("category", "")
        q_level = q.get("level", "")
        q_name = q.get("name", "")
        q_status = q.get("status", "有效")

        # 状态检查
        if q_status == "过期":
            reasons.append("资质已过期")
            return 10, reasons
        if q_status == "待审核":
            reasons.append("资质待审核")

        # 类别匹配
        if required_categories:
            if q_cat in required_categories:
                score += 50
                reasons.append(f"类别匹配: {q_cat}")
            else:
                # 检查 name 是否含有关键词
                for cat, keywords in CATEGORY_KEYWORDS.items():
                    if cat in required_categories:
                        for kw in keywords:
                            if kw in q_name:
                                score += 30
                                reasons.append(f"名称含 {kw} ({cat})")
                                break
        else:
            # 无明确类别要求时，name 匹配即给分
            for cat, keywords in CATEGORY_KEYWORDS.items():
                for kw in keywords:
                    if kw in q_name:
                        score += 20
                        reasons.append(f"名称含 {kw}")
                        break

        # 等级匹配
        if required_levels:
            if q_level in required_levels:
                score += 30
                reasons.append(f"等级匹配: {q_level}")
            elif q_level and any(q_level in rl for rl in required_levels):
                # 部分等级覆盖，如要求"一级"有"特级"
                level_order = ["丙级", "乙级", "三级", "二级", "甲级", "一级", "特级"]
                try:
                    if level_order.index(q_level) < level_order.index(required_levels[0]):
                        score += 15
                        reasons.append(f"等级超出要求: {q_level} > {required_levels[0]}")
                except ValueError:
                    pass
        else:
            if q_level:
                score += 10
                reasons.append(f"具有等级: {q_level}")

        # 证书编号正则验证
        cert_no = q.get("certificate_no", "")
        if cert_no and re.search(r"\\d{4,}", cert_no):
            score += 10
            reasons.append("有证书编号")

        return min(score, 100), reasons
