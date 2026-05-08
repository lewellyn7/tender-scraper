"""项目匹配算法 — 名称规范化 + 编号匹配

用于将同一项目的不同阶段（招标公告、中标结果等）合并关联。
"""

import re
from typing import List, Optional, Tuple


# 需要去除的业务后缀（这些不影响项目本身）
BUSINESS_SUFFIXES = [
    "二次招标",
    "二次采购",
    "三次招标",
    "三次采购",
    "招标公告",
    "中标结果",
    "中标结果公告",
    "采购公告",
    "采购结果",
    "结果公告",
    "变更公告",
    "更正公告",
    "重新招标",
    "流标公告",
    "废标公告",
    "资格预审公告",
    "招标控制价",
    "工程量清单",
    "最高限价公告",
    "延期公告",
    "补充公告",
    "答疑澄清",
    "中标通知书",
    "合同公示",
    "招标",
    "采购",
]

# 期段后缀（保留，用于区分同一项目的不同阶段）
PHASE_SUFFIX_PATTERN = re.compile(
    r"(一期|二期|三期|四期|五期|六期|七期|八期|九期|十期|"
    r"一期工程|二期工程|三期工程|四期工程|五期工程|"
    r"第1期|第2期|第3期|第4期|第5期|"
    r"第1标段|第2标段|第3标段|第4标段|第5标段|"
    r"标段一|标段二|标段三|标段四|标段五|"
    r"A标|B标|C标|D标|E标|"
    r"一期一标段|一期二标段|一期三标段)"
)

# 重复后缀（去除后比对，同一项目的不同招标次数）
# 顺序很重要：长的在前面，避免短模式先匹配
REPEAT_SUFFIX_PATTERN = re.compile(
    r"(第10次|第1次|第2次|第3次|第4次|第5次|第6次|第7次|第8次|第9次|"
    r"第一次|第二次|第三次|第四次|第五次|第六次|第七次|第八次|第九次|第十次|"
    r"二次招标|二次采购|三次招标|三次采购|重新招标|重新采购|"
    r"二次|三次|四次|五次|六次|七次|八次|九次|十次|"
    r"第次)"
)


def normalize_project_name(name: str) -> str:
    """规范化项目名称用于比对。

    规则：
    - 去除 "二次"、"三次"、"第X次" 等重复后缀（同一项目的不同招标次数）
    - 去除 "招标公告"、"中标结果" 等业务后缀
    - 保留 "一期"、"二期" 等期段后缀（期段本身是区分标志，不去除）
    - 去除标点符号和多余空格
    - 返回小写字符串
    """
    if not name:
        return ""

    normalized = name.strip()

    # 去除重复后缀（同一项目的不同招标次数）
    normalized = REPEAT_SUFFIX_PATTERN.sub("", normalized)

    # 去除业务后缀
    for suffix in BUSINESS_SUFFIXES:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()

    # 保留期段后缀（不去除，期段是区分标志）
    # 例如 "某项目一期" 和 "某项目二期" 是不同的

    # 去除标点符号（保留中文、字母、数字，用空字符串替换）
    normalized = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", normalized)

    # 去除多余空格
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized.lower()


def extract_project_no(title: str, content: str = "") -> Optional[str]:
    """从标题或内容中提取招标编号/项目编号。

    支持格式：
    - 招标编号：XXXXXXXX
    - 项目编号：XXXXXXXX
    - 采购编号：XXXXXXXX
    - XX-YYYY-NNNN（标准格式）
    - XXXXXXXXX（纯数字/字母8位以上）
    """
    text = f"{title} {content}"

    # 常见格式：招标编号：XXXXXXXX
    patterns = [
        # 带冒号的标签格式
        r"招标编号[：:]\s*([A-Z0-9\-]{4,32})",
        r"项目编号[：:]\s*([A-Z0-9\-]{4,32})",
        r"采购编号[：:]\s*([A-Z0-9\-]{4,32})",
        r"编号[：:]\s*([A-Z0-9\-]{4,32})",
        # 方括号格式（放在标准格式之前以优先匹配）
        r"\[([A-Za-z0-9][A-Za-z0-9\-]{7,35})\]",
        # 标准格式 XX-YYYY-NNNN 或 XX-YYYY-NNN
        r"\b([A-Z]{2,4}-\d{4}-\d{3,6})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def match_project(
    project_no: Optional[str],
    project_name: str,
    existing_projects: List[dict],
) -> Optional[dict]:
    """将新项目与已有项目列表进行匹配。

    匹配规则（优先级从高到低）：
    1. 编号完全一致 -> 合并
    2. 名称规范化后一致 -> 合并
    3. 无匹配 -> 返回 None

    Args:
        project_no: 招标编号/项目编号
        project_name: 项目名称
        existing_projects: 已有关键词跟踪项目列表

    Returns:
        匹配到的已有项目，未找到则返回 None
    """
    if not project_name:
        return None

    normalized_input = normalize_project_name(project_name)

    for proj in existing_projects:
        # 规则1：编号完全一致
        if project_no and proj.get("project_no"):
            if normalize_project_no(project_no) == normalize_project_no(proj["project_no"]):
                return proj

        # 规则2：名称规范化后一致
        if normalized_input and normalize_project_name(proj.get("name", "")) == normalized_input:
            return proj
        if normalized_input and normalize_project_name(proj.get("project_name", "")) == normalized_input:
            return proj

    return None


def normalize_project_no(project_no: str) -> str:
    """规范化项目编号（去除空格、横线转大写）"""
    if not project_no:
        return ""
    # 去除空格、转大写、去除多余横线
    return re.sub(r"[\s\-_]", "", project_no.upper())


def get_project_key(project_name: str, project_no: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """生成项目的规范化键，用于去重和匹配。

    Returns:
        (规范化名称, 规范化编号或None)
    """
    return (normalize_project_name(project_name), normalize_project_no(project_no) if project_no else None)
