
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.services.llm import (
    LLMConfigurationError,
    generate_answer,
)
from app.services.vector_store import search_chunks

logger = logging.getLogger(__name__)

MAX_RETRIEVED_TEXT_CHARS = 3000

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
async def chat(payload: ChatRequest,http_request: Request):
    """检索知识库并生成带来源的回答。"""

    question = payload.question.strip()

    if not question:
        http_request.state.error_category="input_error"
        raise HTTPException(
            status_code=400,
            detail="问题不能为空。",
        )

    # 第一步：检索相关文本
    try:
        chunks = await run_in_threadpool(
            search_chunks,
            question,
            payload.top_k,
            payload.document_id,
        )
    except Exception as exc:
        # TODO：设置本次请求的错误类别
        http_request.state.error_category = "tool_error"
        # TODO：输出带请求编号的异常详情日志
        logger.exception(json.dumps({
            "event":"retrieval_failed",
            "request_id":http_request.state.request_id,
            "error_category":"tool_error",
            "error_type":type(exc).__name__
        }))
        # TODO：抛出 HTTPException，返回明确的错误说明
        raise HTTPException(
            status_code=500,
            detail="知识库检索失败，请稍后重试。"
        ) from exc

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

    retrieved_text_chars = sum(
        len(source["text"]) for source in sources
    )
    
    if retrieved_text_chars > MAX_RETRIEVED_TEXT_CHARS:
        http_request.state.error_category = "budget_exceeded"
        logger.warning(json.dumps({
            "event":"budget_exceeded",
            "request_id":http_request.state.request_id,
            "error_category":"budget_exceeded",
            "retrieved_text_chars":retrieved_text_chars,
            "limit":MAX_RETRIEVED_TEXT_CHARS
        }))
        raise HTTPException(
            status_code=413,
            detail="检索资料超过本次请求的字符预算，请缩小问题范围。"
        )

    # 第三步：调用大模型生成答案
    try:
        answer = await run_in_threadpool(
            generate_answer,
            question,
            sources,
        )

    except LLMConfigurationError as exc:
        http_request.state.error_category="config_error"
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        http_request.state.error_category="upstream_error"
        logger.exception(json.dumps({
            "event":"model_call_failed",
            # TODO：request_id，使用中间件保存的编号
            "request_id":http_request.state.request_id,
            # TODO：error_category，使用 "upstream_error"
            "error_category":"upstream_error",
            # TODO：error_type，使用当前异常的类型名
            "error_type":type(exc).__name__
        }))

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
