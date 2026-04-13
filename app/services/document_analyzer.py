"""资质文档解析服务 - PDF文字提取 + 图片OCR + LLM智能分析

支持识别证件类型：
- 营业执照 (business license)
- 建造师证书 (constructor)
- 工程师职称 (engineer title)
- 安全员证 (safety officer)
- 身份证 (ID card)
- 通用资质证书
"""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict

from loguru import logger

# ── 依赖检查 ────────────────────────────────────────────────
PDF_AVAILABLE = False
OCR_AVAILABLE = False

try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except ImportError:
    logger.warning("pypdf not installed, PDF extraction disabled")

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    logger.warning("pytesseract not installed, OCR disabled")


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

# ── 共用 prompt 模板 ─────────────────────────────────────────
EXTRACT_FIELDS = """提取字段（全部为字符串或null）：
- certificate_type: 证件类型，选值：营业执照|建造师|工程师|安全员|身份证|资质证书|其他
- name: 证件名称或企业/个人姓名
- person_name: 姓名（个人证件必填）
- id_number: 身份证号（18位，身份证必填）
- certificate_no: 统一社会信用代码或注册号
- construction_no: 注册建造师编号（如"建筑123456"）
- title: 职称或资格等级（如"高级工程师"、"一级建造师"）
- registered_city: 注册城市或注册单位
- level: 资质等级（如"一级"、"甲级"）
- valid_from: 有效期开始，ISO格式"2020-01-01"，无则null
- valid_to: 有效期结束，ISO格式"2025-12-31"，无则null
- issuer: 发证机关
- address: 注册地址（营业执照）
- legal_person: 法定代表人（营业执照）
- confidence: 置信度0.0-1.0"""

CERTIFICATE_TYPES = ["营业执照", "建造师", "工程师", "安全员", "身份证", "资质证书", "其他"]


def _detect_certificate_type(text: str) -> str:
    """根据文本内容判断证件类型"""
    t = text[:2000]  # 只看前2000字
    type_scores = {
        "身份证": [
            r"公民身份号码", r"居民身份证", r"身份证号", r"\d{17}[\dXx]",
            r"性别[男女]", r"出生[年月日在]", r"民族[汉蒙藏回]"
        ],
        "建造师": [
            r"注册建造师", r"一级建造师", r"二级建造师",
            r"建造师证书", r"建筑.+号", r"专业:"
        ],
        "工程师": [
            r"工程师", r"高级工程师", r"中级工程师",
            r"职称证书", r"专业技术职务", r"任职资格"
        ],
        "安全员": [
            r"安全员", r"安全生产考核", r"安全考核合格证",
            r"建筑施工企业", r"三类人员"
        ],
        "营业执照": [
            r"营业执照", r"统一社会信用代码", r"法定代表人",
            r"注册资本", r"注册地址", r"经营范围",
            r"企业名称", r"成立日期"
        ],
        "资质证书": [
            r"资质证书", r"建筑业企业资质", r"安全生产许可证",
            r"等级证书", r"许可证书"
        ],
    }
    best_type = "资质证书"
    best_score = 0
    for ctype, patterns in type_scores.items():
        score = sum(1 for p in patterns if re.search(p, t))
        if score > best_score:
            best_score = score
            best_type = ctype
    return best_type


def _normalize_date(s: str) -> str:
    """将各种日期格式转为 ISO 格式"""
    s = s.strip().replace("年", "-").replace("月", "-").replace("日", "").rstrip("-")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _rule_based_extract(text: str) -> Dict:
    """基于规则的正则提取（无LLM时的后备方案）"""
    result = {
        "certificate_type": None,
        "name": None,
        "person_name": None,
        "id_number": None,
        "certificate_no": None,
        "construction_no": None,
        "title": None,
        "registered_city": None,
        "level": None,
        "valid_from": None,
        "valid_to": None,
        "issuer": None,
        "address": None,
        "legal_person": None,
        "confidence": 0.3,
        "method": "rule_based",
    }

    lines = text.split("\n")
    full_text = text

    # ── 1. 证件类型判断 ───────────────────────────────────
    cert_type = _detect_certificate_type(text)
    result["certificate_type"] = cert_type

    # ── 2. 通用字段提取 ───────────────────────────────────

    # 身份证号（18位）
    m = re.search(r"\b(\d{17}[\dXx])\b", full_text)
    if m:
        result["id_number"] = m.group(1).upper()

    # 统一社会信用代码（18位）
    m = re.search(r"\b([0-9A-Z]{18})\b", full_text)
    if m:
        result["certificate_no"] = m.group(1)

    # 注册建造师编号
    for pat in [
        r"注册编号[：:\s]*([A-Z0-9\-]{6,20})",
        r"注册建造师[：:\s]*([A-Z0-9\-]{6,20})",
        r"证书编号[：:\s]*([A-Z0-9\-]{5,})",
        r"编号[：:\s]*([A-Z0-9]{5,})",
    ]:
        m = re.search(pat, full_text)
        if m:
            val = m.group(1).strip()
            if not result["construction_no"] or len(val) > len(result.get("construction_no","")):
                result["construction_no"] = val
            if not result["certificate_no"] or len(val) > len(result.get("certificate_no","")):
                result["certificate_no"] = val
            break

    # 姓名
    for pat in [
        r"姓\s*名[：:\s]*([^\n,，、]{2,8})",
        r"持有人[：:\s]*([^\n,，、]{2,8})",
        r"本人[：:\s]*([^\n,，、]{2,8})",
    ]:
        m = re.search(pat, full_text)
        if m:
            name = m.group(1).strip()
            if len(name) >= 2 and not any(c.isdigit() for c in name):
                result["person_name"] = name
                if not result["name"]:
                    result["name"] = name
                break

    # 职称 / 资格等级
    title_kws = [
        "高级工程师", "中级工程师", "初级工程师",
        "一级建造师", "二级建造师", "注册建造师",
        "高级经济师", "中级经济师",
        "工程师", "经济师", "会计师"
    ]
    for kw in title_kws:
        if kw in full_text:
            result["title"] = kw
            break

    # 资质等级
    level_kws = ["特级", "一级", "二级", "三级", "甲级", "乙级", "丙级", "丁级"]
    for kw in level_kws:
        if kw in full_text:
            result["level"] = kw
            break

    # 有效期至
    for pat in [
        r"有效期[至到]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}日?)",
        r"有效期至\s*(\d{4})年(\d{1,2})月(\d{1,2})日?",
        r"有效期限?\s*(\d{4})年(\d{1,2})月",
        r"至\s*(\d{4})年(\d{1,2})月(\d{1,2})日?",
        r"有效期[：:\s]*(\d{4})[年\-](\d{1,2})[月\-](\d{1,2})",
    ]:
        m = re.search(pat, full_text)
        if m:
            if len(m.groups()) == 3:
                result["valid_to"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            else:
                result["valid_to"] = _normalize_date(m.group(1))
            break

    # 有效期从
    m = re.search(r"有效期[：:\s]*(\d{4})年(\d{1,2})月(\d{1,2})日?[至\-~到].*?(\d{4})年(\d{1,2})月(\d{1,2})日?", full_text)
    if m:
        result["valid_from"] = f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"
    else:
        m2 = re.search(r"有效期[：:\s]*(\d{4})年(\d{1,2})月(\d{1,2})日?", full_text)
        if m2:
            result["valid_from"] = f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"

    # 发证机关
    for pat in [
        r"发证机关[：:]\s*([^\n]{2,30})",
        r"颁发机关[：:]\s*([^\n]{2,30})",
        r"发证单位[：:]\s*([^\n]{2,30})",
        r"签发机关[：:]\s*([^\n]{2,30})",
    ]:
        m = re.search(pat, full_text)
        if m:
            result["issuer"] = m.group(1).strip().rstrip("。,，")
            break

    # 注册地址
    for pat in [
        r"注册地址[：:]\s*([^\n]{5,50})",
        r"地址[：:]\s*([^\n]{5,50})",
        r"营业场所[：:]\s*([^\n]{5,50})",
    ]:
        m = re.search(pat, full_text)
        if m:
            result["address"] = m.group(1).strip().rstrip("。,，")
            break

    # 法定代表人
    for pat in [
        r"法定代表人[：:]\s*([^\n]{2,10})",
        r"法人代表[：:]\s*([^\n]{2,10})",
        r"负责人[：:]\s*([^\n]{2,10})",
    ]:
        m = re.search(pat, full_text)
        if m:
            result["legal_person"] = m.group(1).strip()
            break

    # 注册城市 / 注册单位
    for pat in [
        r"注册地[区点][：:]\s*([^\n]{2,20})",
        r"注册单位[：:]\s*([^\n]{2,30})",
        r"工作单位[：:]\s*([^\n]{2,30})",
        r"聘用企业[：:]\s*([^\n]{2,30})",
    ]:
        m = re.search(pat, full_text)
        if m:
            result["registered_city"] = m.group(1).strip().rstrip("。,，")
            break

    # 企业/证件名称
    name_candidates = []
    for line in lines:
        line = line.strip()
        if 4 < len(line) < 100:
            if any(kw in line for kw in ["企业名称", "公司名称", "名称", "名称："]):
                m = re.search(r"[：:]\s*([^\n]{3,50})", line)
                if m:
                    name_candidates.append(m.group(1).strip())
            elif result["certificate_type"] == "身份证" and any(kw in line for kw in ["姓名", "持有人"]):
                m = re.search(r"[：:]\s*([^\n]{2,8})", line)
                if m:
                    name_candidates.append(m.group(1).strip())
    if name_candidates:
        result["name"] = max(name_candidates, key=len).strip()
    elif result["person_name"]:
        result["name"] = result["person_name"]

    # 推断类别
    if cert_type != "其他":
        result["category"] = cert_type

    return result


# ── LLM 分析 ──────────────────────────────────────────────
def _build_llm_prompt(text: str) -> str:
    return f"""你是资质文档分析专家。从以下证件/文档内容中提取结构化信息，返回严格JSON格式（无markdown）。

{EXTRACT_FIELDS}

如果无法提取某字段，设为null。不要编造信息。

证件类型候选：{', '.join(CERTIFICATE_TYPES)}
请根据内容自行判断最合适的certificate_type。

文档内容：
{text[:8000]}

返回JSON（只返回JSON，无其他内容）："""


def _analyze_with_llm_service(text: str) -> Dict:
    """通过 LLMService 多模型调用分析文档"""
    try:
        import asyncio
        from app.services.llm_service import get_llm_service

        async def _call():
            service = await get_llm_service()
            if not service.providers:
                return None
            result = await service.chat(
                prompt=_build_llm_prompt(text),
                json_mode=True,
                temperature=0.1,
                max_tokens=2048,
            )
            return result

        llm_result = asyncio.run(_call())
        if not llm_result or not llm_result.success:
            return {"error": llm_result.error if llm_result else "no providers configured"}

        try:
            parsed = json.loads(llm_result.content)
            if "confidence" not in parsed:
                parsed["confidence"] = 0.8
            parsed["_llm_provider"] = llm_result.provider
            parsed["_llm_model"] = llm_result.model
            parsed["_llm_latency_ms"] = llm_result.latency_ms
            return parsed
        except json.JSONDecodeError:
            return {"error": f"JSON解析失败: {llm_result.content[:200]}"}
    except Exception as e:
        logger.error(f"LLMService call failed: {e}")
        return {"error": str(e)}


def _call_openai_analysis(text: str) -> Dict:
    """调用 OpenAI API 分析文档内容"""
    try:
        import openai
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return {"error": "OPENAI_API_KEY not set"}

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": _build_llm_prompt(text)}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        result = json.loads(raw)
        if "confidence" not in result:
            result["confidence"] = 0.8
        return result
    except Exception as e:
        logger.error(f"OpenAI analysis failed: {e}")
        return {"error": str(e)}


def _call_ragflow_analysis(text: str) -> Dict:
    """调用 RAGFlow API 分析文档内容"""
    try:
        import httpx
        ragflow_url = os.getenv("RAGFLOW_URL", "http://localhost:8080")
        api_key = os.getenv("RAGFLOW_API_KEY", "")
        if not api_key:
            return {"error": "RAGFLOW_API_KEY not set"}

        resp = httpx.post(
            f"{ragflow_url}/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "question": _build_llm_prompt(text),
                "response_mode": "direct",
                "dataset_ids": [],
                "document_ids": [],
            },
            timeout=60.0,
        )
        data = resp.json()
        content = data.get("data", {}).get("answer", "") or data.get("answer", "")
        match = re.search(r"\{[\s\S]+\}", content)
        if match:
            result = json.loads(match.group())
            if "confidence" not in result:
                result["confidence"] = 0.8
            return result
        return {"raw_answer": content, "error": "无法解析结构化结果"}
    except Exception as e:
        logger.error(f"RAGFlow analysis failed: {e}")
        return {"error": str(e)}


# ── 主分析器 ────────────────────────────────────────────────


class DocumentAnalyzer:
    """资质文档分析器（支持营业执照/建造师/工程师/安全员/身份证/资质证书）"""

    SUPPORTED_FORMATS = {"pdf", "jpg", "jpeg", "png"}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self, upload_dir: str = "uploads"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def extract_text_from_pdf(self, file_path: Path) -> str:
        """从 PDF 提取文字"""
        if not PDF_AVAILABLE:
            return "[PDF提取不可用: pypdf未安装]"

        try:
            reader = PdfReader(str(file_path))
            texts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
            return "\n".join(texts)
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return f"[PDF提取失败: {e}]"

    def extract_text_from_image(self, file_path: Path) -> str:
        """从图片 OCR 提取文字"""
        if not OCR_AVAILABLE:
            return "[OCR不可用: pytesseract未安装]"

        try:
            import pytesseract
            from PIL import Image

            img = Image.open(str(file_path))
            if img.mode not in ("L", "RGB"):
                img = img.convert("RGB")
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            return text or "[OCR未识别到文字]"
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return f"[OCR失败: {e}]"

    def extract_text(self, file_path: Path) -> str:
        """根据文件类型自动选择提取方法"""
        suffix = file_path.suffix.lower().lstrip(".")
        if suffix == "pdf":
            return self.extract_text_from_pdf(file_path)
        elif suffix in ("jpg", "jpeg", "png"):
            return self.extract_text_from_image(file_path)
        else:
            return f"[不支持的格式: {suffix}]"

    def analyze_with_llm(self, text: str) -> Dict:
        """调用 LLM 进行结构化信息提取（多模型 + 自动 fallback）"""
        if LLM_PROVIDER == "none":
            return _rule_based_extract(text)

        llm_result = _analyze_with_llm_service(text)
        if llm_result and "error" not in llm_result:
            return llm_result

        if LLM_PROVIDER == "openai":
            return _call_openai_analysis(text)
        elif LLM_PROVIDER == "ragflow":
            return _call_ragflow_analysis(text)

        logger.warning(f"LLM分析失败，回退到规则提取: {llm_result}")
        fields = _rule_based_extract(text)
        if llm_result:
            fields["llm_error"] = llm_result.get("error", "unknown")
        return fields

    def analyze_document(self, file_path: Path, use_llm: bool = True) -> Dict:
        """
        完整分析流程：提取文字 → 判断证件类型 → LLM解析 → 返回结果
        """
        suffix = file_path.suffix.lower().lstrip(".")

        # 1. 文字提取
        raw_text = self.extract_text(file_path)

        if not raw_text or len(raw_text.strip()) < 5:
            return {
                "success": False,
                "error": "文档内容提取失败或内容为空",
                "raw_text": raw_text,
                "fields": {},
            }

        # 2. 先用规则快速判断证件类型
        fields = _rule_based_extract(raw_text)

        # 3. LLM 深度解析
        if use_llm and LLM_PROVIDER != "none":
            llm_result = self.analyze_with_llm(raw_text)
            if "error" not in llm_result:
                # 合并规则结果到LLM结果（规则提供证件类型判断）
                for k, v in fields.items():
                    if k not in ("confidence", "method") and not llm_result.get(k):
                        llm_result[k] = v
                if not llm_result.get("certificate_type"):
                    llm_result["certificate_type"] = fields.get("certificate_type")
                fields = llm_result
            else:
                fields["llm_error"] = llm_result.get("error")
                # LLM失败，用规则结果，置信度维持较低
                fields["confidence"] = 0.3

        # 4. 补充元数据
        fields["file_name"] = file_path.name
        fields["file_size"] = file_path.stat().st_size
        fields["file_type"] = suffix
        fields["text_length"] = len(raw_text)
        fields["analyzed_at"] = datetime.now().isoformat()

        # 5. 确定状态
        status = "有效"
        if fields.get("valid_to"):
            try:
                valid_to = date.fromisoformat(fields["valid_to"])
                if valid_to < date.today():
                    status = "过期"
            except (ValueError, TypeError):
                pass
        fields["status"] = status

        return {
            "success": True,
            "raw_text": raw_text[:500] + "..." if len(raw_text) > 500 else raw_text,
            "fields": fields,
        }
