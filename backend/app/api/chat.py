
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.services.llm import (
    LLMConfigurationError,
    generate_answer,
)
from app.services.vector_store import search_chunks

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chat",
    tags=["RAG 问答"],
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)
    document_id: str | None = None


class ChatSource(BaseModel):
    source_id: str
    chunk_id: str
    document_id: str
    filename: str
    page: int
    chunk_index: int
    text: str
    distance: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """检索知识库并生成带来源的回答。"""

    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="问题不能为空。",
        )

    # 第一步：检索相关文本
    chunks = await run_in_threadpool(
        search_chunks,
        question,
        request.top_k,
        request.document_id,
    )

    if not chunks:
        return {
            "answer": "知识库中没有找到相关资料，暂时无法回答。",
            "sources": [],
        }

    # 第二步：为每个检索结果分配来源编号
    sources = []

    for index, chunk in enumerate(chunks, start=1):
        sources.append({
            "source_id": f"S{index}",
            **chunk,
        })

    # 第三步：调用大模型生成答案
    try:
        answer = await run_in_threadpool(
            generate_answer,
            question,
            sources,
        )

    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("RAG 大模型调用失败")

        raise HTTPException(
            status_code=502,
            detail=(
                "大模型调用失败。请检查模型服务是否运行、"
                "接口地址、模型名称和 API 配置。"
            ),
        ) from exc

    # 第四步：返回答案和可追溯的来源
    return {
        "answer": answer,
        "sources": sources,
    }
