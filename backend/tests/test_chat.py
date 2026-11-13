

from fastapi.testclient import TestClient
from app.main import app
from unittest.mock import patch
import pytest

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
        assert response.status_code == 200
        # TODO 2：检查完整响应 JSON
        assert response.json() == {
            "answer": "知识库中没有找到相关资料，暂时无法回答。",
            "sources": [],
        }
        # TODO 3：检查检索恰好调用一次
        mock_search.assert_called_once()
        # TODO 4：检查模型没有被调用
        mock_model.assert_not_called()
        
def test_chat_retrieval_failure():
    with (
            patch("app.api.chat.search_chunks", side_effect=RuntimeError("mock retrieval failed")) as mock_search,
            patch("app.api.chat.generate_answer", return_value="mock answer") as mock_model,
            TestClient(app) as client,
    ):
        response = client.post(
            "/api/chat",
            json={"question": "什么是 RAG？"},
        )
        assert response.status_code==500
        assert response.json()=={"detail": "知识库检索失败，请稍后重试。"}
        mock_search.assert_called_once()
        mock_model.assert_not_called()

@pytest.mark.parametrize(
    "text_chars, expected_status, expected_model_calls",
    [
        (2999, 200, 1),
        (3000, 200, 1),
        (3001, 413, 0),
    ],
)
def test_chat_text_budget(
    text_chars, expected_status, expected_model_calls
):
    chunks = [
        {
            "chunk_id": f"mock-chunk-{index}",
            "document_id": "mock-document",
            "filename": "mock.pdf",
            "page": 1,
            "chunk_index": index,
            "text": "x" * length,
            "distance": 0.1,
        }
        for index, length in enumerate(
            [1000, text_chars - 1000]
        )
    ]

    # TODO：替换检索和模型，发送请求，完成检查
    with (
        patch("app.api.chat.search_chunks", return_value=chunks) as mock_search,
        patch("app.api.chat.generate_answer", return_value="mock answer") as mock_model,
        TestClient(app) as client,
    ):
        response = client.post(
        "/api/chat",
        json={"question": "什么是 RAG？"},
    )
        assert response.status_code == expected_status
        mock_search.assert_called_once()
        assert mock_model.call_count == expected_model_calls
        body = response.json()
        if response.status_code == 200:
            assert body["answer"] == "mock answer"
            assert len(body["sources"]) == 2
        elif response.status_code == 413:
            assert body == {"detail": "检索资料超过本次请求的字符预算，请缩小问题范围。"}
