
from fastapi import FastAPI

from app.api.documents import router as documents_router
from app.api.search import router as search_router
from app.api.chat import router as chat_router

app = FastAPI(
    title="KnowledgeFlow RAG",
    version="0.3.0",
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
