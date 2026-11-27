from typing import Annotated, Literal

from app.access import ReadScope, WriteScope
from app.services.ingestion import Worker, runtime
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/kbs/{kb_id}", tags=["文档管理"])
Runtime = Annotated[Worker, Depends(runtime)]
MAX_FILE_SIZE = 10 * 1024 * 1024


class JobInfo(BaseModel):
    job_id: str
    document_id: str
    filename: str
    version: int
    status: Literal["queued", "running", "ready", "failed"]
    is_active: bool
    indexed_count: int
    page_count: int
    error: str | None


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    version: int
    chunk_count: int


class DocumentList(BaseModel):
    document_count: int
    documents: list[DocumentInfo]


@router.get("/documents", response_model=DocumentList)
def list_documents(
    scope: ReadScope,
    rt: Runtime,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return rt.catalog.listing(scope.kb_id, limit, offset)


@router.post("/documents/upload", status_code=202, response_model=JobInfo)
async def upload_pdf(scope: WriteScope, rt: Runtime, file: UploadFile = File(...)):
    try:
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name.lower().endswith(".pdf") or len(name) > 200 or any(ord(c) < 32 for c in name):
            raise HTTPException(400, "请提供有效的 PDF 文件名。")
        content = await file.read(MAX_FILE_SIZE + 1)
    finally:
        await file.close()
    if not content:
        raise HTTPException(400, "上传的文件为空。")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "文件大小不能超过 10 MB。")
    if b"%PDF-" not in content[:1024]:
        raise HTTPException(400, "文件没有有效的 PDF 标记。")
    job = await run_in_threadpool(rt.catalog.enqueue, scope.kb_id, scope.subject, name, content)
    rt.wake.set()
    return job


@router.get("/jobs/{job_id}", response_model=JobInfo)
def job_status(job_id: str, scope: ReadScope, rt: Runtime):
    job = rt.catalog.job(scope.kb_id, job_id)
    if not job:
        raise HTTPException(404, "任务不存在。")
    return job


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=JobInfo)
def retry_job(job_id: str, scope: WriteScope, rt: Runtime):
    job = rt.catalog.job(scope.kb_id, job_id, retry=True)
    if not job:
        raise HTTPException(404, "任务不存在。")
    rt.wake.set()
    return job


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, scope: WriteScope, rt: Runtime):
    if not rt.catalog.remove(scope.kb_id, document_id):
        raise HTTPException(404, "文档不存在。")
    rt.wake.set()
    return {"document_id": document_id, "message": "文档已下线，后台将清理索引。"}
