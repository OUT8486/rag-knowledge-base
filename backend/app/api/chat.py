import logging
from typing import Annotated

from app.access import ReadScope
from app.api.search import RetrievalOptions, SearchResult
from app.services.evidence import checked_answer, pack_sources
from app.services.ingestion import Worker, runtime
from app.services.llm import (
    NO_EVIDENCE,
    LLMConfigurationError,
    generate_answer,
    generate_search_intent,
    model_route,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kbs/{kb_id}", tags=["RAG 问答"])


class ChatRequest(RetrievalOptions):
    question: str = Field(min_length=1, max_length=2000)
    require_local: bool = Field(False, description="调用方可收紧模型策略，但不能放宽知识库策略。")


class ChatSource(SearchResult):
    source_id: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    scope: ReadScope,
    rt: Annotated[Worker, Depends(runtime)],
    request: Request,
):
    question = payload.question.strip()
    if not question:
        raise HTTPException(400, "问题不能为空。")
    # A stale browser tab or evaluation run must not silently gain permission to send data outside.
    if payload.require_local and scope.policy != "local_only":
        raise HTTPException(409, "知识库不再是仅本地模式。请刷新并确认策略后再提问。")
    versions = rt.catalog.active_versions(scope.kb_id, payload.document_id)
    if not versions:
        return {"answer": NO_EVIDENCE, "sources": []}
    try:
        route = model_route(scope.policy)
    except LLMConfigurationError:
        raise HTTPException(503, "该知识库的模型配置不可用，请联系管理员。") from None
    try:
        query = generate_search_intent(question, route).query.strip() or question
    except Exception as exc:
        # Optional rewrite may fail; never change endpoint, knowledge base, or document scope.
        log.warning(
            "rewrite_fallback request_id=%s type=%s", request.state.request_id, type(exc).__name__
        )
        query = question
    try:
        sources = pack_sources(rt.search(scope.kb_id, versions, query, payload.top_k))
    except Exception:
        request.state.error_category = "retrieval_error"
        raise HTTPException(500, "知识库检索失败，请稍后重试。") from None
    if not sources:
        return {"answer": NO_EVIDENCE, "sources": []}
    try:
        answer = generate_answer(question, sources, route)
    except Exception as exc:
        log.warning(
            "answer_failed request_id=%s type=%s", request.state.request_id, type(exc).__name__
        )
        raise HTTPException(502, "模型调用失败，请稍后重试。") from None
    return checked_answer(answer, sources)
