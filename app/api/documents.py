"""文档上传 / 列表 / 删除 接口。

知识点：
1. UploadFile + File(...) 处理 multipart 上传；
   千万不要一次 read() 全读进内存 —— 边读边写、按字节限额（streaming 上传）。
2. 扩展名白名单校验是“第一道门”，但扩展名可伪造 —— 内容解析失败时
   服务端要有清晰的 400 报错（真实验收内容类型要 magic bytes，见文档 Step1）。
3. 所有业务都委托给 engine：路由保持“薄”，逻辑集中在 core 便于测试。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..core.parsing import ParseError
from ..schemas import DocInfo, UploadResponse

router = APIRouter(prefix="/api/documents", tags=["documents"])

_CHUNK = 1024 * 1024  # 1 MiB


# 辅助函数，获取 engine，避免重复写代码
def _engine(request):
    return request.app.state.engine


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
        request: Request,
        file: UploadFile = File(...),
        title: str | None = Form(default=None),   # 可选“自定义标题”（表单字段）
) -> UploadResponse:
    settings = get_settings()
    engine = _engine(request)

    filename = (file.filename or "unnamed").strip()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in settings.allowed_extension_set:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 .{ext}，仅允许："
                   f"{', '.join(sorted(settings.allowed_extension_set))}",
        )

    # 边读边写 + 超限中断（不把整个文件读进内存）
    tmp_name = f"{uuid.uuid4().hex}.{ext}"
    tmp_path = settings.upload_dir / tmp_name
    total = 0
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过大小上限 {settings.max_upload_mb:.0f} MiB",
                    )
                out.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    try:
        result = await engine.ingest_file(str(tmp_path), filename, title)
    except ParseError as e:  # 解析失败（如扫描版 PDF）
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # 兜底：统一转 500，别把堆栈漏给前端
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"入库失败：{e}") from e

    return UploadResponse(
        doc_id=result["doc_id"],
        title=(title or "").strip() or filename.rsplit(".", 1)[0],
        filename=filename,
        char_count=result["char_count"],
        chunk_count=result["chunk_count"],
        elapsed_ms=result["elapsed_ms"],
    )

# 文档列表
@router.get("", response_model=list[DocInfo])
async def list_documents(request: Request) -> list[DocInfo]:
    docs = _engine(request).store.doc_list()
    # 按上传时间倒序（字符串时间戳可排序）
    docs.sort(key=lambda d: d.uploaded_at, reverse=True)
    return [
        DocInfo(
            doc_id=d.doc_id,
            title=d.title,
            filename=d.filename,
            char_count=d.char_count,
            chunk_count=d.chunk_count,
            uploaded_at=d.uploaded_at,
        )
        for d in docs
    ]


@router.delete("/{doc_id}")
async def delete_document(request: Request, doc_id: str):
    ok = await _engine(request).delete_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return JSONResponse({"ok": True, "doc_id": doc_id})
