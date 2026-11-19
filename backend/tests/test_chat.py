

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.errors import ExtractionError
from app.services.extract import SearchIntent
from app.services.llm import LLMConfigurationError

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
    question = "什么是 RAG？"
    intent = SearchIntent(query="RAG 定义")
    with (
        patch("app.api.chat.generate_search_intent", return_value=intent) as mock_intent,
        patch("app.api.chat.search_chunks", return_value=[]) as mock_search,
        patch("app.api.chat.generate_answer", return_value="mock answer") as mock_model,
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/chat",
            json={"question": question},
        )

        assert response.status_code == 200
        assert response.json() == {
            "answer": "知识库中没有找到相关资料，暂时无法回答。",
            "sources": [],
        }
        mock_intent.assert_called_once_with(question)
        mock_search.assert_called_once_with(intent.query, 5, None)
        mock_model.assert_not_called()
        
def test_chat_retrieval_failure():
    question = "什么是 RAG？"
    intent = SearchIntent(query="RAG 定义")
    with (
        patch("app.api.chat.generate_search_intent", return_value=intent) as mock_intent,
        patch(
            "app.api.chat.search_chunks", side_effect=RuntimeError("mock retrieval failed")
        ) as mock_search,
        patch("app.api.chat.generate_answer", return_value="mock answer") as mock_model,
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/chat",
            json={"question": question},
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "知识库检索失败，请稍后重试。"}
        mock_intent.assert_called_once_with(question)
        mock_search.assert_called_once_with(intent.query, 5, None)
        mock_model.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        pytest.param(
            ExtractionError("模型输出不是合法 JSON"),
            502,
            "模型调用失败，请稍后重试。",
            id="extraction-error",
        ),
        pytest.param(
            LLMConfigurationError("缺少模型配置"),
            503,
            "服务配置不完整，请联系管理员。",
            id="configuration-error",
        ),
        pytest.param(
            RuntimeError("意图模型调用失败"),
            502,
            "模型调用失败，请稍后重试。",
            id="model-call-error",
        ),
    ],
)
def test_chat_intent_generation_failure(error, expected_status, expected_detail):
    question = "申请年假需要哪些材料？"
    with (
        patch("app.api.chat.generate_search_intent", side_effect=error) as mock_intent,
        patch("app.api.chat.search_chunks") as mock_search,
        patch("app.api.chat.generate_answer") as mock_answer,
        TestClient(app) as client,
    ):
        response = client.post("/api/chat", json={"question": question})

        assert response.status_code == expected_status
        assert response.json() == {"detail": expected_detail}
        mock_intent.assert_called_once_with(question)
        mock_search.assert_not_called()
        mock_answer.assert_not_called()


def test_chat_uses_rewritten_query_and_user_search_scope():
    question = "请问我刚入职三个月，申请年假要准备哪些材料？"
    rewritten_query = "入职三个月员工 年假申请所需材料"
    intent = SearchIntent(query=rewritten_query)
    assert intent.top_k == 5
    assert intent.document_id is None

    chunks = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-abc",
            "filename": "handbook.pdf",
            "page": 2,
            "chunk_index": 0,
            "text": "申请年假需要填写申请表。",
            "distance": 0.1,
        },
        {
            "chunk_id": "chunk-2",
            "document_id": "doc-abc",
            "filename": "handbook.pdf",
            "page": 3,
            "chunk_index": 1,
            "text": "申请表由直属主管审批。",
            "distance": 0.2,
        },
    ]
    expected_sources = [
        {"source_id": "S1", **chunks[0]},
        {"source_id": "S2", **chunks[1]},
    ]
    answer = "需要填写年假申请表 [S1]，交由直属主管审批 [S2]。"

    with (
        patch("app.api.chat.generate_search_intent", return_value=intent) as mock_intent,
        patch("app.api.chat.search_chunks", return_value=chunks) as mock_search,
        patch("app.api.chat.generate_answer", return_value=answer) as mock_answer,
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/chat",
            json={"question": question, "top_k": 2, "document_id": "doc-abc"},
        )

        assert response.status_code == 200
        assert response.json() == {"answer": answer, "sources": expected_sources}
        mock_intent.assert_called_once_with(question)
        mock_search.assert_called_once_with(rewritten_query, 2, "doc-abc")
        mock_answer.assert_called_once_with(question, expected_sources)


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
    question = "什么是 RAG？"
    intent = SearchIntent(query="RAG 定义")
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

    with (
        patch("app.api.chat.generate_search_intent", return_value=intent) as mock_intent,
        patch("app.api.chat.search_chunks", return_value=chunks) as mock_search,
        patch("app.api.chat.generate_answer", return_value="mock answer") as mock_model,
        TestClient(app) as client,
    ):
        response = client.post(
            "/api/chat",
            json={"question": question},
        )
        assert response.status_code == expected_status
        mock_intent.assert_called_once_with(question)
        mock_search.assert_called_once_with(intent.query, 5, None)
        assert mock_model.call_count == expected_model_calls
        body = response.json()
        if response.status_code == 200:
            assert body["answer"] == "mock answer"
            assert len(body["sources"]) == 2
        elif response.status_code == 413:
            assert body == {"detail": "检索资料超过本次请求的字符预算，请缩小问题范围。"}
