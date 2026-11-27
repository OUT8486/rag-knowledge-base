from typing import Annotated

from app.access import ReadScope
from app.services.ingestion import Worker, runtime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/kbs/{kb_id}", tags=["语义检索"])


class RetrievalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_k: int = Field(default=5, ge=1, le=10)
    document_id: str | None = None


class SearchRequest(RetrievalOptions):
    query: str = Field(min_length=1, max_length=1000)


class SearchResult(BaseModel):
    chunk_id: str
    text: str
    document_id: str
    version_id: str
    filename: str
    page: int
    chunk_index: int
    distance: float


class SearchResponse(BaseModel):
    query: str
    result_count: int
    results: list[SearchResult]


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest, scope: ReadScope, rt: Annotated[Worker, Depends(runtime)]):
    query = payload.query.strip()
    if not query:
        raise HTTPException(400, "查询问题不能为空。")
    versions = rt.catalog.active_versions(scope.kb_id, payload.document_id)
    results = rt.search(scope.kb_id, versions, query, payload.top_k)
    return {"query": query, "result_count": len(results), "results": results}
