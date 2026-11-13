

from fastapi.testclient import TestClient
from app.main import app
from unittest.mock import patch


def test_chat1():
    with TestClient(app) as client:
        response = client.post("/api/chat", json={})
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["type"] == "missing"
    assert error["loc"] == ["body", "question"]

def test_chat2():
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"question":""})
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["type"] == "string_too_short"
    assert error["loc"] == ["body", "question"]

def test_chat3():
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"question":" "})
    assert response.status_code == 400
    assert response.json() == {"detail": "问题不能为空。"}

def test_chat_no_results():
    with (
        patch("app.api.chat.search_chunks", return_value=[]) as mock_search,
        patch("app.api.chat.generate_answer", return_value="mock answer") as mock_model,
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/chat",
            json={"question": "什么是 RAG？"},
        )

        # TODO 1：检查状态码
        # TODO 2：检查完整响应 JSON
        # TODO 3：检查检索恰好调用一次
        # TODO 4：检查模型没有被调用