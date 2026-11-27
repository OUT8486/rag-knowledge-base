import json
import logging
from time import perf_counter
from uuid import uuid4

from app import access, telemetry
from app.api import chat, customer, customer_desk, documents, search
from app.services.embedding import get_embedding_model
from app.services.ingestion import lifespan, runtime
from app.services.llm import model_route
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
app = FastAPI(title="KnowledgeFlow RAG", version="0.5.0", lifespan=lifespan)


@app.middleware("http")
async def request_log(request: Request, call_next):
    start = perf_counter()
    request.state.request_id = str(uuid4())
    trace = telemetry.request_id.set(request.state.request_id)
    try:
        response = await call_next(request)
    except Exception as exc:
        request.state.error_category = type(exc).__name__
        response = JSONResponse({"detail": "服务器内部错误"}, status_code=500)
    finally:
        telemetry.request_id.reset(trace)
    elapsed = round((perf_counter() - start) * 1000, 2)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Process-Time-Ms"] = str(elapsed)
    response.headers["Cache-Control"] = "private, no-store"
    record = {
        "method": request.method,
        "path": request.url.path,
        "request_id": request.state.request_id,
        "subject": getattr(request.state, "subject", None),
        "kb_id": getattr(request.state, "kb_id", None),
        "elapsed_ms": elapsed,
        "status_code": response.status_code,
    }
    defaults = {
        400: "input_error",
        401: "unauthenticated",
        403: "access_denied",
        404: "not_found",
        409: "conflict",
        413: "input_error",
        422: "input_error",
        502: "upstream_error",
        503: "unavailable",
    }
    if category := getattr(request.state, "error_category", None) or defaults.get(
        response.status_code
    ):
        record["error_category"] = category
    logger.log(logging.ERROR if response.status_code >= 500 else logging.INFO, json.dumps(record))
    return response


for router in (
    access.router,
    documents.router,
    search.router,
    chat.router,
    customer.router,
    customer_desk.router,
):
    app.include_router(router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "RAG Knowledge Base is running"}


@app.get("/api/ready")
def readiness(request: Request):
    try:
        access.auth_mode()
        config = access.configuration()
        for policy in {kb.policy for kb in config.knowledge_bases.values()}:
            # Validate configuration without performing inference.
            model_route(policy)
        rt = runtime(request)
        if not rt.thread.is_alive():
            raise RuntimeError("worker")
        with rt.catalog.connection() as db:
            db.execute("SELECT id FROM docs LIMIT 1").fetchone()
        get_embedding_model()  # Local files only; subsequent probes reuse the cached model.
        rt.vectors.client().heartbeat()
    except Exception:
        raise HTTPException(503, "依赖尚未就绪。") from None
    return {"status": "ready"}
