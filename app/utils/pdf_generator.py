"""PDF 报表生成模块"""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

try:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _fmt_budget(amount: float) -> str:
    if amount >= 100000000:
        return f"{amount/100000000:.2f}亿"
    elif amount >= 10000:
        return f"{amount/10000:.2f}万"
    return f"{amount:.0f}元"


class PDFReportGenerator:
    def __init__(self):
        self.available = REPORTLAB_AVAILABLE
        if not self.available:
            logger.warning("reportlab not installed")

    def generate_report(
        self, projects: List[Dict], title: str = "招投标采集报表", date_range: str = None
    ) -> Optional[str]:
        if not self.available or not projects:
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = OUTPUT_DIR / f"report_{ts}.pdf"
        doc = SimpleDocTemplate(
            str(fp),
            pagesize=A4,
            leftMargin=1.5 * cm,
            rightMargin=1.5 * cm,
            topMargin=1.5 * cm,
            bottomMargin=1.5 * cm,
        )
        styles = getSampleStyleSheet()
        ts_style = ParagraphStyle(
            "T", parent=styles["Title"], fontSize=16, spaceAfter=12, textColor=HexColor("#1a56db")
        )
        sub_style = ParagraphStyle(
            "S", parent=styles["Normal"], fontSize=10, textColor=HexColor("#6b7280"), spaceAfter=20
        )
        h_style = ParagraphStyle(
            "H",
            parent=styles["Heading2"],
            fontSize=12,
            textColor=HexColor("#1f2937"),
            spaceBefore=12,
            spaceAfter=6,
        )
        els = []
        els.append(Paragraph(title, ts_style))
        sub = f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        if date_range:
            sub += f" | 日期范围: {date_range}"
        sub += f" | 共 {len(projects)} 条记录"
        els.append(Paragraph(sub, sub_style))
        els.append(HRFlowable(width="100%", thickness=1, color=HexColor("#e5e7eb"), spaceAfter=12))
        # stats
        with_budget = [p for p in projects if p.get("budget")]
        total = 0
        for p in with_budget:
            try:
                b = p.get("budget", "")
                n = float(re.sub(r"[^\d.]", "", b)) * (10000 if "万" in b else 1)
                total += n
            except Exception:
                pass
        sd = [
            [
                "采集总数",
                str(len(projects)),
                "有预算",
                str(len(with_budget)),
                "总预算",
                _fmt_budget(total),
            ]
        ]
        st = Table(sd, colWidths=[3 * cm, 2.5 * cm, 3 * cm, 2.5 * cm, 3 * cm, 3 * cm])
        st.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f3f4f6")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), HexColor("#374151")),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d1d5db")),
                ]
            )
        )
        els.append(st)
        els.append(Spacer(1, 0.5 * cm))
        # by type
        by_type = {}
        for p in projects:
            t = p.get("tender_type", p.get("type", "未知"))
            by_type.setdefault(t, []).append(p)
        for ptype, items in by_type.items():
            els.append(Paragraph(f"{ptype} ({len(items)} 条)", h_style))
            td = [["序号", "项目名称", "类型", "预算", "截止日期", "关键词"]]
            for i, p in enumerate(items[:20], 1):
                t = p.get("title", "")[:30] + ("..." if len(p.get("title", "")) > 30 else "")
                tt = p.get("tender_type", p.get("type", ""))[:8]
                b = p.get("budget", "-")[:15]
                d = p.get("submission_deadline", p.get("deadline", "-"))[:12]
                kw = ",".join(p.get("keywords_matched", "").split(",")[:2])[:15]
                td.append([str(i), t, tt, b, d, kw])
            t2 = Table(
                td, colWidths=[1.2 * cm, 6 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 2.8 * cm], repeatRows=1
            )
            t2.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#1a56db")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
                        ("ALIGN", (0, 0), (0, -1), "CENTER"),
                        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#e5e7eb")),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [HexColor("#ffffff"), HexColor("#f9fafb")],
                        ),
                    ]
                )
            )
            els.append(t2)
            els.append(Spacer(1, 0.3 * cm))
        doc.build(els)
        logger.info(f"PDF generated: {fp}")
        return str(fp)

    def generate_segmented(self, projects: List[Dict], segment_by: str = "date") -> List[str]:
        if not self.available or not projects:
            return []
        by_key = {}
        if segment_by == "date":
            for p in projects:
                d = p.get("publish_date", "未知")[:10]
                by_key.setdefault(d, []).append(p)
        else:
            for p in projects:
                t = p.get("tender_type", p.get("type", "未知"))
                by_key.setdefault(t, []).append(p)
        files = []
        for key, items in by_key.items():
            f = self.generate_report(items, title=f"招投标报表 - {key}", date_range=key)
            if f:
                files.append(f)
        return files


_pdf_gen: Optional[PDFReportGenerator] = None


def get_pdf_generator() -> PDFReportGenerator:
    global _pdf_gen
    if _pdf_gen is None:
        _pdf_gen = PDFReportGenerator()
    return _pdf_gen
