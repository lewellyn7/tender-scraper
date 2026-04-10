"""资质文档解析服务 - PDF文字提取 + 图片OCR + LLM智能分析"""

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


# ── LLM 分析 ────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai | ragflow | none


def _call_openai_analysis(text: str) -> Dict:
    """调用 OpenAI API 分析文档内容"""
    try:
        import openai
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return {"error": "OPENAI_API_KEY not set"}

        client = openai.OpenAI(api_key=api_key)
        prompt = f"""你是资质文档分析专家。从以下资质文档内容中提取结构化信息，返回严格JSON格式（无markdown）。

提取字段：
- name: 资质名称（字符串）
- category: 资质类别，如"建筑"、"IT"、"服务"等（字符串）
- level: 资质等级，如"一级"、"甲级"、"特级"等（字符串）
- certificate_no: 证书编号（字符串）
- valid_from: 有效期开始，ISO格式如"2020-01-01"，无则null（字符串|null）
- valid_to: 有效期结束，ISO格式如"2025-12-31"，无则null（字符串|null）
- issuer: 发证机关（字符串）
- confidence: 置信度0.0-1.0（浮点数）

如果无法提取某字段，设为null。不要编造信息。

文档内容：
{text[: 8000]}

返回JSON："""

        response = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
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

        prompt = f"""你是资质文档分析专家。从以下资质文档内容中提取结构化信息，返回严格JSON格式。

提取字段：
- name: 资质名称
- category: 资质类别
- level: 资质等级
- certificate_no: 证书编号
- valid_from: 有效期开始(ISO格式)，无则null
- valid_to: 有效期结束(ISO格式)，无则null
- issuer: 发证机关
- confidence: 置信度0.0-1.0

文档内容：
{text[: 8000]}"""

        resp = httpx.post(
            f"{ragflow_url}/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "question": prompt,
                "response_mode": "direct",
                "dataset_ids": [],
                "document_ids": [],
            },
            timeout=60.0,
        )
        data = resp.json()
        content = data.get("data", {}).get("answer", "") or data.get("answer", "")
        # 尝试从回答中提取 JSON
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


def _rule_based_extract(text: str) -> Dict:
    """基于规则的正则提取（无LLM时的后备方案）"""
    result = {
        "name": None,
        "category": None,
        "level": None,
        "certificate_no": None,
        "valid_from": None,
        "valid_to": None,
        "issuer": None,
        "confidence": 0.3,
        "method": "rule_based",
    }

    lines = text.split("\n")
    full_text = text

    # 证书编号
    cert_patterns = [
        r"证书编号[：:]\s*([A-Z0-9\-]+)",
        r"编号[：:]\s*([A-Z0-9\-]{5,})",
        r"证书号[：:]\s*([A-Z0-9\-]+)",
        r"No[.\s]*([A-Z0-9\-]+)",
    ]
    for pat in cert_patterns:
        m = re.search(pat, full_text)
        if m:
            result["certificate_no"] = m.group(1).strip()
            break

    # 有效期
    date_patterns = [
        r"有效期[至到]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}日?)",
        r"有效期[至到]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2})",
        r"有效期[：:]\s*(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2})",
    ]
    for pat in date_patterns:
        m = re.search(pat, full_text)
        if m:
            date_str = m.group(1).replace("年", "-").replace("月", "-").replace("日", "")
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                result["valid_to"] = dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
            break

    # 有效期开始
    from_patterns = [
        r"有效期.*?(\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2})",
    ]
    m = re.search(r"有效期[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日?", full_text)
    if m:
        result["valid_from"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 发证机关
    issuer_patterns = [
        r"发证机关[：:]\s*([^\n\d]{2,30})",
        r"颁发机关[：:]\s*([^\n\d]{2,30})",
        r"发证单位[：:]\s*([^\n\d]{2,30})",
    ]
    for pat in issuer_patterns:
        m = re.search(pat, full_text)
        if m:
            result["issuer"] = m.group(1).strip().rstrip("。")
            break

    # 资质等级
    level_keywords = ["特级", "一级", "二级", "三级", "甲级", "乙级", "丙级", "丁级"]
    for kw in level_keywords:
        if kw in full_text:
            result["level"] = kw
            break

    # 资质名称（取最长的含关键词的行）
    name_keywords = ["资质", "许可", "认证", "证书", "执照", "登记"]
    candidates = []
    for line in lines:
        line = line.strip()
        if any(kw in line for kw in name_keywords) and 4 < len(line) < 80:
            candidates.append(line)
    if candidates:
        result["name"] = max(candidates, key=len).strip()
        # 从名称中推断类别
        if "建筑" in result["name"]:
            result["category"] = "建筑"
        elif "信息" in result["name"] or "系统" in result["name"]:
            result["category"] = "IT"
        elif "服务" in result["name"]:
            result["category"] = "服务"

    return result


# ── 主分析器 ────────────────────────────────────────────────


class DocumentAnalyzer:
    """资质文档分析器"""

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
            # 转为灰度提升识别率
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
        """调用 LLM 进行结构化信息提取"""
        if LLM_PROVIDER == "openai":
            return _call_openai_analysis(text)
        elif LLM_PROVIDER == "ragflow":
            return _call_ragflow_analysis(text)
        else:
            return _rule_based_extract(text)

    def analyze_document(
        self,
        file_path: Path,
        use_llm: bool = True,
    ) -> Dict:
        """
        完整分析流程：提取文字 → LLM解析 → 返回结果
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

        # 2. LLM 分析
        if use_llm and LLM_PROVIDER != "none":
            llm_result = self.analyze_with_llm(raw_text)
            if "error" in llm_result and not any(k in llm_result for k in ("name", "certificate_no")):
                # LLM 失败，回退到规则提取
                logger.warning(f"LLM分析失败，回退到规则提取: {llm_result.get('error')}")
                fields = _rule_based_extract(raw_text)
                fields["llm_error"] = llm_result.get("error")
            else:
                fields = llm_result
        else:
            fields = _rule_based_extract(raw_text)

        # 3. 补充元数据
        fields["file_name"] = file_path.name
        fields["file_size"] = file_path.stat().st_size
        fields["file_type"] = suffix
        fields["text_length"] = len(raw_text)
        fields["analyzed_at"] = datetime.now().isoformat()

        # 4. 确定状态
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
            "raw_text": raw_text[: 500] + "..." if len(raw_text) > 500 else raw_text,
            "fields": fields,
        }
