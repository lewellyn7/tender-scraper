"""DocumentAnalyzer OCR/PDF 失败判定测试 (qualification-ai P0-2)

修复 2026-06-07: 之前 extract_text 失败时返回的 placeholder
（如 "[OCR失败: ...]"）会被 analyze_document 当作真实文档内容继续解析，
导致把错误信息文本当成证件类型识别。

新逻辑：analyze_document 在调用 extract_text 后立即检测 placeholder，
若是失败占位符则直接返回 success: False。
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def analyzer(tmp_path):
    """DocumentAnalyzer 实例，临时上传目录"""
    from app.services.document_analyzer import DocumentAnalyzer
    return DocumentAnalyzer(upload_dir=str(tmp_path))


def _create_test_file(tmp_path, suffix=".png", content=b"fake-image-bytes"):
    p = tmp_path / f"test{suffix}"
    p.write_bytes(content)
    return p


class TestExtractionErrorPlaceholder:
    """测试 placeholder 检测函数"""

    def test_ocr_unavailable_detected(self):
        from app.services.document_analyzer import _is_extraction_error
        assert _is_extraction_error("[OCR不可用: pytesseract未安装]") is True

    def test_ocr_failed_detected(self):
        from app.services.document_analyzer import _is_extraction_error
        assert _is_extraction_error("[OCR失败: out of memory]") is True

    def test_ocr_no_text_detected(self):
        from app.services.document_analyzer import _is_extraction_error
        assert _is_extraction_error("[OCR未识别到文字]") is True

    def test_pdf_unavailable_detected(self):
        from app.services.document_analyzer import _is_extraction_error
        assert _is_extraction_error("[PDF提取不可用: pypdf未安装]") is True

    def test_pdf_failed_detected(self):
        from app.services.document_analyzer import _is_extraction_error
        assert _is_extraction_error("[PDF提取失败: invalid PDF]") is True

    def test_unsupported_format_detected(self):
        from app.services.document_analyzer import _is_extraction_error
        assert _is_extraction_error("[不支持的格式: docx]") is True

    def test_empty_string_detected(self):
        from app.services.document_analyzer import _is_extraction_error
        assert _is_extraction_error("") is True
        assert _is_extraction_error(None) is True

    def test_real_text_not_detected_as_error(self):
        from app.services.document_analyzer import _is_extraction_error
        assert _is_extraction_error("营业执照\n统一社会信用代码: 91110000XXXXXXXXXX") is False
        assert _is_extraction_error("中华人民共和国居民身份证") is False


class TestAnalyzeDocumentFailureHandling:
    """测试 analyze_document 在提取失败时返回 success: False"""

    def test_ocr_disabled_returns_failure(self, analyzer, tmp_path):
        """pytesseract 未装时上传图片 → success=False，不解析占位符"""
        from app.services import document_analyzer as da_mod

        file_path = _create_test_file(tmp_path, ".png")
        original_ocr = da_mod.OCR_AVAILABLE
        try:
            da_mod.OCR_AVAILABLE = False
            result = analyzer.analyze_document(file_path, use_llm=False)
            assert result["success"] is False
            assert "OCR不可用" in result["error"]
            assert result["fields"] == {}
        finally:
            da_mod.OCR_AVAILABLE = original_ocr

    def test_pdf_disabled_returns_failure(self, analyzer, tmp_path):
        """pypdf 未装时上传 PDF → success=False"""
        from app.services import document_analyzer as da_mod

        file_path = _create_test_file(tmp_path, ".pdf")
        original_pdf = da_mod.PDF_AVAILABLE
        try:
            da_mod.PDF_AVAILABLE = False
            result = analyzer.analyze_document(file_path, use_llm=False)
            assert result["success"] is False
            assert "PDF提取不可用" in result["error"]
            assert result["fields"] == {}
        finally:
            da_mod.PDF_AVAILABLE = original_pdf

    def test_unsupported_format_returns_failure(self, analyzer, tmp_path):
        """不支持的格式 → success=False（不假装成功）"""
        file_path = _create_test_file(tmp_path, ".docx")
        result = analyzer.analyze_document(file_path, use_llm=False)
        assert result["success"] is False
        assert "不支持的格式" in result["error"]

    def test_ocr_exception_returns_failure(self, analyzer, tmp_path):
        """OCR 抛异常（image corrupt）→ success=False"""
        from app.services import document_analyzer as da_mod

        file_path = _create_test_file(tmp_path, ".png")

        def fake_ocr_failure(path):
            return "[OCR失败: cannot identify image file]"

        # extract_text_from_image 是 DocumentAnalyzer 实例方法
        original_image = analyzer.extract_text_from_image
        try:
            analyzer.extract_text_from_image = fake_ocr_failure
            result = analyzer.analyze_document(file_path, use_llm=False)
            assert result["success"] is False
            assert "OCR失败" in result["error"]
        finally:
            analyzer.extract_text_from_image = original_image

    def test_real_text_still_parsed_normally(self, analyzer, tmp_path):
        """真实文本 → 走正常解析路径（不误判为失败）"""
        from app.services import document_analyzer as da_mod

        file_path = _create_test_file(tmp_path, ".txt")
        # 直接修改 extract_text 返真实文本
        analyzer.extract_text = lambda p: "营业执照\n统一社会信用代码: 91110000ABCDEFGHIJ\n法定代表人: 张三"

        result = analyzer.analyze_document(file_path, use_llm=False)
        assert result["success"] is True
        # _rule_based_extract 应该识别出证书号
        assert result["fields"].get("certificate_no") == "91110000ABCDEFGHIJ" or \
               result["fields"].get("id_number") is not None or \
               len(result["fields"]) > 0
