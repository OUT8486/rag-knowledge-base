
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.services.vector_store import search_chunks

router = APIRouter(
    prefix="/api/search",
    tags=["语义检索"],
)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=10)
    document_id: str | None = None


class SearchResult(BaseModel):
    chunk_id: str
    text: str
    document_id: str
    filename: str
    page: int
    chunk_index: int
    distance: float


class SearchResponse(BaseModel):
    query: str
    result_count: int
    results: list[SearchResult]


@router.post("", response_model=SearchResponse)
async def search(request: SearchRequest):
    """在向量知识库中查找相关文本。"""

    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="查询问题不能为空。",
        )

    results = await run_in_threadpool(
        search_chunks,
        query,
        request.top_k,
        request.document_id,
    )

    return {
        "query": query,
        "result_count": len(results),
        "results": results,
    }
