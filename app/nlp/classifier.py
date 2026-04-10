"""TenderClassifier - 招标文本分类器
支持：类别分类、优先级判定、地域识别、关键词抽取
"""

import jieba
import re
from collections import Counter
from typing import Dict, List, Tuple

# 行业类别关键词
CATEGORY_PATTERNS = {
    "建筑工程": ["建筑", "施工", "装修", "装饰", "钢结构", "幕墙", "消防", "电梯", "空调", "水电", "市政", "园林", "公路", "桥梁", "隧道", "地基", "防水", "防腐", "拆迁", "加固", "监理", "造价", "设计", "土建", "砼", "钢筋", "灌注", "管网", "道排", "绿化", "路灯", "外墙", "内装", "改造"],
    "信息技术": ["软件", "系统", "网络", "信息化", "智能化", "安防", "监控", "会议", "广播", "音响", "大屏", "显示", "存储", "服务器", "数据", "云", "安全", "等保", "集成", "运维", "IT", "计算机", "数据库", "OA", "ERP", "智慧", "数字化", "物联网", "5G", "光纤", "带宽"],
    "物资采购": ["设备", "机械", "车辆", "医疗", "教学", "实验", "科研", "办公", "家具", "厨房", "家电", "LED", "灯具", "电梯", "泵", "阀", "仪表", "耗材", "配件", "工具", "劳保", "服装", "面料"],
    "服务类": ["物业", "保洁", "保安", "绿化", "餐饮", "酒店", "旅游", "咨询", "代理", "招标", "评估", "审计", "法律", "会计", "培训", "印刷", "租赁", "物流", "快递", "人力资源", "外包"],
    "弱电智能化": ["监控", "门禁", "考勤", "巡更", "报警", "楼宇对讲", "停车场", "道闸", "人脸识别", "车牌识别", "视频监控", "综合布线", "有限电视", "广播系统", "会议系统", "大屏", "拼接屏", "信息发布"],
}

# 地域关键词
REGION_PATTERNS = {
    "重庆": ["重庆", "重庆市", "主城区", "渝中", "渝北", "南岸", "沙坪坝", "九龙坡", "江北", "大渡口", "巴南", "北碚"],
    "四川": ["四川", "成都", "绵阳", "德阳", "宜宾", "泸州", "南充", "达州", "乐山"],
    "贵州": ["贵州", "贵阳", "遵义", "六盘水", "安顺", "毕节", "铜仁"],
    "云南": ["云南", "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江"],
}

# 优先级关键词
PRIORITY_PATTERNS = {
    5: ["紧急", "急迫", "立即", "限时", "今日", "本周"],
    4: ["重点", "重大", "优先", "主要"],
    3: ["一般", "普通", "常规"],
}

# 金额级别（万元）
BUDGET_LEVELS = {
    "超大": (5000, float("inf")),
    "大": (1000, 5000),
    "中": (100, 1000),
    "小": (0, 100),
}


class TenderClassifier:
    """招标文本分类器"""

    def __init__(self):
        self._category_cache: Dict[str, str] = {}

    def segment(self, text: str) -> List[str]:
        """中文分词"""
        return [w for w in jieba.cut(text) if w.strip() and len(w) > 1]

    def extract_keywords(self, text: str, top_k: int = 10) -> List[Tuple[str, int]]:
        """抽取关键词（基于词频）"""
        words = self.segment(text)
        # 停用词过滤
        stopwords = {"的", "了", "和", "是", "在", "与", "或", "及", "为", "以", "等", "于", "从", "到", "由", "对", "这", "那", "有", "我", "你", "他"}
        words = [w for w in words if w not in stopwords and len(w) > 1]
        counter = Counter(words)
        return counter.most_common(top_k)

    def classify_category(self, text: str) -> str:
        """分类：返回最匹配的行业类别"""
        text_lower = text
        scores = {}
        for category, keywords in CATEGORY_PATTERNS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[category] = score
        if not scores:
            return "其他"
        return max(scores, key=scores.get)

    def classify_region(self, text: str) -> str:
        """识别：返回匹配地域"""
        for region, keywords in REGION_PATTERNS.items():
            if any(kw in text for kw in keywords):
                return region
        return "全国"

    def classify_priority(self, text: str, budget: str = "") -> int:
        """判定优先级 1-5"""
        score = 3  # 默认一般
        for level, keywords in PRIORITY_PATTERNS.items():
            if any(kw in text for kw in keywords):
                score = max(score, level)
        # 金额加成
        if budget:
            level = self._budget_level(budget)
            if level == "超大":
                score = min(5, score + 1)
            elif level == "大":
                score = min(5, score + 1)
        return score

    def _budget_level(self, budget: str) -> str:
        """根据金额字符串判断级别"""
        try:
            val = float(re.sub(r"[^\d.]", "", budget))
            for level, (low, high) in BUDGET_LEVELS.items():
                if low <= val < high:
                    return level
        except (ValueError, TypeError):
            pass
        return "小"

    def classify(self, title: str, content: str = "", budget: str = "") -> Dict:
        """综合分类"""
        text = f"{title} {content}"
        return {
            "category": self.classify_category(text),
            "region": self.classify_region(title),
            "priority": self.classify_priority(text, budget),
            "budget_level": self._budget_level(budget),
            "keywords": [kw for kw, _ in self.extract_keywords(text, top_k=5)],
        }
