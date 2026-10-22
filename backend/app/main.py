
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as documents_router
from app.api.search import router as search_router
from app.api.chat import router as chat_router

app = FastAPI(
    title="KnowledgeFlow RAG",
    version="0.4.0",
)

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
