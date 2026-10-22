
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.services.chunker import chunk_pages
from app.services.document_parser import extract_pdf_pages
from app.services.vector_store import (
    add_chunks,
    delete_document as remove_document,
    list_documents as get_documents,
)


router = APIRouter(
    prefix="/api/documents",
    tags=["文档管理"],
)

MAX_FILE_SIZE = 10 * 1024 * 1024

@router.get("")
async def list_all_documents():
    """获取知识库文档列表。"""

    documents = await run_in_threadpool(
        get_documents
    )

    return {
        "document_count": len(documents),
        "documents": documents,
    }


@router.delete("/{document_id}")
async def delete_one_document(document_id: str):
    """删除指定文档的所有向量片段。"""

    deleted_count = await run_in_threadpool(
        remove_document,
        document_id,
    )

    if deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail="文档不存在，或该文档没有已入库的文本块。",
        )

    return {
        "document_id": document_id,
        "deleted_chunks": deleted_count,
        "message": "文档及其向量片段已删除。",
    }

@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """上传 PDF、提取文本、切分并写入向量数据库。"""

    filename = file.filename or "unnamed.pdf"

    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="当前只支持 PDF 文件。",
        )

    content = await file.read(MAX_FILE_SIZE + 1)
    await file.close()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="上传的文件为空。",
        )

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="文件大小不能超过 10 MB。",
        )

    try:
        pages = extract_pdf_pages(content)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    document_id = uuid4().hex

    chunks = chunk_pages(
        pages=pages,
        document_id=document_id,
        chunk_size=600,
        overlap=100,
    )

    # 将向量编码与数据库写入放在线程池中运行
    indexed_count = await run_in_threadpool(
        add_chunks,
        chunks,
        Path(filename).name,
    )

    total_characters = sum(
        len(page["text"]) for page in pages
    )

    pages_with_text = sum(
        bool(page["text"].strip()) for page in pages
    )

    return {
        "document_id": document_id,
        "filename": Path(filename).name,
        "file_size_bytes": len(content),
        "page_count": len(pages),
        "pages_with_text": pages_with_text,
        "total_characters": total_characters,
        "chunk_count": len(chunks),
        "indexed_count": indexed_count,
        "chunks_preview": chunks[:3],
        "message": (
            "文档解析、切分和向量入库成功"
            if indexed_count == len(chunks) and chunks
            else "文档没有生成可用的文本块"
        ),
    }
