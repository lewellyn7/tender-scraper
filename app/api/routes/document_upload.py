"""资质文件上传 API"""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends
from fastapi.responses import JSONResponse

from app.database import get_db
from app.services.document_analyzer import DocumentAnalyzer
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/documents", tags=["文档管理"])

# ── 配置 ────────────────────────────────────────────────────
UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}

analyzer = DocumentAnalyzer(upload_dir=str(UPLOAD_DIR))


# ── 工具函数 ────────────────────────────────────────────────

def _validate_file(file: UploadFile) -> None:
    """验证文件类型和大小"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}，支持的格式: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # 内容长度检查（StreamingBody 没有 content_length）
    # 实际大小在读取时检查


async def _save_file(file: UploadFile) -> tuple[Path, str]:
    """保存上传文件，返回 (路径, 原文件名)"""
    original_name = file.filename or "unknown"
    ext = original_name.rsplit(".", 1)[-1].lower()

    # 生成唯一文件名
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = UPLOAD_DIR / unique_name

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 限制")

    with open(file_path, "wb") as f:
        f.write(content)

    return file_path, original_name


# ── API 路由 ────────────────────────────────────────────────


@router.post("/upload", summary="上传资质文档")
async def upload_document(
    file: UploadFile = File(...),
    qualification_id: Optional[int] = Form(None, description="关联已有资质记录ID"),
    name: Optional[str] = Form(None, description="资质名称（可选，自动从文档提取）"),
):
    """
    上传 PDF/JPG/PNG 资质文档，自动分析并提取结构化信息。
    """
    _validate_file(file)

    # 保存文件
    file_path, original_name = await _save_file(file)
    logger.info(f"Document uploaded: {file_path} ({original_name})")

    try:
        # 分析文档
        result = analyzer.analyze_document(file_path, use_llm=True)

        if not result["success"]:
            # 分析失败，保存文件但返回空结果
            return JSONResponse({
                "success": False,
                "error": result.get("error", "分析失败"),
                "file_path": str(file_path),
                "original_name": original_name,
                "fields": {},
            })

        fields = result["fields"]

        # 确定资质名称
        qual_name = name or fields.get("name") or original_name.rsplit(".", 1)[0]

        # 准备数据库记录
        record_data = {
            "name": qual_name,
            "category": fields.get("category") or "",
            "level": fields.get("level") or "",
            "certificate_no": fields.get("certificate_no") or "",
            "valid_from": fields.get("valid_from") or "",
            "valid_to": fields.get("valid_to") or "",
            "issuer": fields.get("issuer") or "",
            "file_path": str(file_path),
            "status": fields.get("status", "有效"),
        }

        qual_id: Optional[int] = qualification_id

        # 如果有关联ID，更新现有记录；否则创建新记录
        db = get_db()
        if qualification_id:
            existing = db.get_qualification(qualification_id)
            if not existing:
                raise HTTPException(status_code=404, detail="关联的资质记录不存在")
            db.update_qualification(qualification_id, record_data)
        else:
            qual_id = db.add_qualification(record_data)

        confidence = fields.get("confidence", 0.0)

        return JSONResponse({
            "success": True,
            "qualification_id": qual_id,
            "file_path": str(file_path),
            "original_name": original_name,
            "confidence": confidence,
            "status": fields.get("status", "有效"),
            "fields": {
                "name": record_data["name"],
                "category": record_data["category"],
                "level": record_data["level"],
                "certificate_no": record_data["certificate_no"],
                "valid_from": record_data["valid_from"],
                "valid_to": record_data["valid_to"],
                "issuer": record_data["issuer"],
                "status": record_data["status"],
            },
            "analysis_note": _build_analysis_note(fields),
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document upload failed: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e),
            "file_path": str(file_path),
            "original_name": original_name,
        }, status_code=500)


@router.post("/analyze-preview", summary="上传并分析（仅预览，不保存资质）")
async def analyze_preview(
    file: UploadFile = File(...),
):
    """
    上传文档并分析，返回解析结果（不保存资质记录）。
    文件保存在临时目录，确认保存时再移到正式目录。
    """
    _validate_file(file)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 限制")

    import uuid
    ext = (file.filename or "unknown").rsplit(".", 1)[-1].lower()
    tmp_path = UPLOAD_DIR / "tmp_preview" / f"{uuid.uuid4().hex}.{ext}"
    tmp_path.parent.mkdir(exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(content)

    try:
        result = analyzer.analyze_document(Path(str(tmp_path)), use_llm=True)
        return JSONResponse({
            "success": result.get("success", False),
            "error": result.get("error"),
            "fields": result.get("fields", {}),
            "file_path": str(tmp_path),
            "original_name": file.filename or "unknown",
        })
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-only", summary="仅分析文档（不上传）")
async def analyze_only(
    file: UploadFile = File(...),
):
    """
    仅分析文档内容，不保存到数据库。
    适用于预览分析结果。
    """
    _validate_file(file)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 限制")

    # 写入临时文件
    import uuid
    ext = (file.filename or "unknown").rsplit(".", 1)[-1].lower()
    tmp_path = UPLOAD_DIR / f"tmp_{uuid.uuid4().hex}.{ext}"
    with open(tmp_path, "wb") as f:
        f.write(content)

    try:
        result = analyzer.analyze_document(tmp_path, use_llm=True)
        return JSONResponse(result)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/formats", summary="支持的文档格式")
def supported_formats(user_id: str = Depends(get_current_user)):
    """返回支持的文档格式列表"""
    return JSONResponse({
        "formats": list(ALLOWED_EXTENSIONS),
        "max_size_mb": MAX_FILE_SIZE // 1024 // 1024,
    })


def _build_analysis_note(fields: dict) -> str:
    """根据分析结果生成备注"""
    parts = []
    if fields.get("certificate_no"):
        parts.append(f"编号: {fields['certificate_no']}")
    if fields.get("level"):
        parts.append(f"等级: {fields['level']}")
    if fields.get("valid_to"):
        parts.append(f"有效期至: {fields['valid_to']}")
    if fields.get("issuer"):
        parts.append(f"发证: {fields['issuer']}")
    if fields.get("confidence"):
        parts.append(f"置信度: {fields['confidence']:.0%}")
    return " | ".join(parts) if parts else ""


# 导入 logger
from loguru import logger
