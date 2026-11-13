
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as documents_router
from app.api.search import router as search_router
from app.api.chat import router as chat_router

from uuid import uuid4

from time import perf_counter

import json
import logging

from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="KnowledgeFlow RAG",
    version="0.4.0",
)

@app.middleware("http")
async def add_request_id(request, call_next):
    
    start_time = perf_counter()
    record=dict()
    # TODO：生成编号，保存到 request.state.request_id
    request.state.request_id = str(uuid4())
    record["method"]=request.method
    record["path"]=request.url.path
    record["request_id"]=request.state.request_id

    try:
        response = await call_next(request)
        error_category = getattr(request.state, "error_category", None)
    except Exception as exc:
        # TODO：计算失败时的耗时，构造并输出错误日志
        fail_time=(perf_counter()-start_time)*1000
        record["elapsed_ms"]=fail_time
        record["status_code"]=500
        record["error_type"]=type(exc).__name__
        record["error_category"]="internal_error"
        logger.error(json.dumps(record))
        error_response = JSONResponse(
            status_code=500,
            content={"detail":"服务器内部错误"},
        )
        
        # TODO：给 error_response 设置两个响应头
        error_response.headers["X-Request-ID"] = request.state.request_id
        error_response.headers["X-Process-Time-Ms"] = str(fail_time)

        return error_response
    
    elapsed_ms = (perf_counter()-start_time)*1000
    # TODO：把同一编号写入 response.headers["X-Request-ID"]
    response.headers["X-Request-ID"]=request.state.request_id
    response.headers["X-Process-Time-Ms"]=str(elapsed_ms)

    record["elapsed_ms"]=elapsed_ms
    record["status_code"]=response.status_code
    
    # TODO：状态码为 400、413、422 时，
    # 给 record 添加 error_category，值为 "input_error"
    if error_category is not None:
        # TODO：把路由给出的类别写入 record
        record["error_category"] = request.state.error_category
    elif response.status_code in (400,413,422):
        record["error_category"] = "input_error"
    elif response.status_code == 502:
        record["error_category"] = "upstream_error"
    elif response.status_code == 503:
            record["error_category"] = "config_error"
    if response.status_code >= 500:
        logger.error(json.dumps(record))
    else:
        logger.info(json.dumps(record))
    
    return response

# 允许本地 Vue 开发服务器访问后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(search_router)
app.include_router(chat_router)


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "message": "RAG Knowledge Base is running",
    }
