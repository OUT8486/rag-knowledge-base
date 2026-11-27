"""generate_search_intent 的行为测试：替换模型客户端，使用真实的意图解析器。"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx2
import pytest
from app.services.errors import ExtractionError
from app.services.extract import SearchIntent
from app.services.llm import (
    generate_answer,
    generate_customer_answer,
    generate_search_intent,
    model_route,
)
from openai import APIConnectionError, APITimeoutError, OpenAIError
from pydantic import ValidationError


@pytest.fixture
def mock_openai(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-api-key")
    monkeypatch.setenv("LLM_MODEL", "test-search-model")

    # OpenAI 在函数内部导入，因此替换其来源模块上的类。
    with patch("openai.OpenAI") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )
        yield mock_client


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param(
            '{"query": "退货运费谁承担", "top_k": 3, "document_id": "doc-1"}',
            {"query": "退货运费谁承担", "top_k": 3, "document_id": "doc-1"},
            id="all-fields",
        ),
        pytest.param(
            '{"query": "发票怎么开"}',
            {"query": "发票怎么开", "top_k": 5, "document_id": None},
            id="default-fields",
        ),
    ],
)
def test_generate_search_intent_returns_valid_intent(mock_openai, content, expected):
    question = "请问退货运费由谁承担？"
    mock_create = mock_openai.return_value.chat.completions.create
    mock_create.return_value.choices[0].message.content = content

    intent = generate_search_intent(question, model_route("approved_cloud"))

    assert isinstance(intent, SearchIntent)
    assert intent.query == expected["query"]
    assert intent.top_k == expected["top_k"]
    assert intent.document_id == expected["document_id"]
    mock_openai.assert_called_once()
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "test-search-model"
    user_messages = [message for message in call_kwargs["messages"] if message["role"] == "user"]
    assert len(user_messages) == 1
    assert question in user_messages[0]["content"]


def test_generate_search_intent_retries_after_connection_error(mock_openai):
    mock_create = mock_openai.return_value.chat.completions.create
    response = mock_create.return_value
    response.choices[
        0
    ].message.content = '{"query": "退货运费谁承担", "top_k": 3, "document_id": "doc-1"}'
    request = httpx2.Request("POST", "https://llm.example.test/v1/chat/completions")
    mock_create.side_effect = [APIConnectionError(request=request), response]

    with patch("app.services.retry_executor.time.sleep"):
        intent = generate_search_intent("请问退货运费由谁承担？", model_route("approved_cloud"))

    assert mock_create.call_count == 2
    assert isinstance(intent, SearchIntent)
    assert intent.query == "退货运费谁承担"
    assert intent.top_k == 3
    assert intent.document_id == "doc-1"


def test_question_is_trimmed_before_model_call(mock_openai):
    mock_create = mock_openai.return_value.chat.completions.create
    mock_create.return_value.choices[0].message.content = '{"query": "年假申请"}'

    intent = generate_search_intent(" \t年假申请\t ", model_route("approved_cloud"))

    assert intent.query == "年假申请"
    mock_create.assert_called_once()
    user_messages = [
        message for message in mock_create.call_args.kwargs["messages"] if message["role"] == "user"
    ]
    assert len(user_messages) == 1
    # 直接检查发给模型的内容，避免测试中再 strip() 掩盖问题正文的空白。
    assert user_messages[0]["content"] == "用户问题：\n    年假申请"


@pytest.mark.parametrize("question", ["", " ", "\t", "\n", " \t\r\n "])
def test_empty_question_does_not_call_model(mock_openai, question):
    with pytest.raises(ValueError):
        generate_search_intent(question, model_route("approved_cloud"))

    mock_openai.assert_not_called()
    mock_openai.return_value.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("content", [None, "", " ", "\t", "\n", " \t\r\n "])
def test_empty_model_content_raises_extraction_error(mock_openai, content):
    mock_create = mock_openai.return_value.chat.completions.create
    mock_create.return_value.choices[0].message.content = content

    with pytest.raises(ExtractionError):
        generate_search_intent("退货运费谁承担？", model_route("approved_cloud"))

    mock_create.assert_called_once()


@pytest.mark.parametrize(
    "content",
    ["我不知道该检索什么", "{", "{'query': '退货'}", '{"query": "退货",}'],
)
def test_invalid_model_json_is_rejected(mock_openai, content):
    mock_create = mock_openai.return_value.chat.completions.create
    mock_create.return_value.choices[0].message.content = content

    with pytest.raises(ExtractionError, match="模型输出不是合法 JSON") as exc_info:
        generate_search_intent("退货运费谁承担？", model_route("approved_cloud"))

    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)
    mock_create.assert_called_once()


@pytest.mark.parametrize("content", ["[]", '"退货"', "null"])
def test_non_object_model_json_is_rejected(mock_openai, content):
    mock_create = mock_openai.return_value.chat.completions.create
    mock_create.return_value.choices[0].message.content = content

    with pytest.raises(ExtractionError, match="模型输出的顶层结构不是 JSON 对象"):
        generate_search_intent("退货运费谁承担？", model_route("approved_cloud"))

    mock_create.assert_called_once()


@pytest.mark.parametrize(
    ("data", "invalid_field"),
    [
        pytest.param({"top_k": 3}, "query", id="missing-query"),
        pytest.param({"query": ""}, "query", id="empty-query"),
        pytest.param({"query": "x" * 201}, "query", id="query-too-long"),
        pytest.param({"query": None}, "query", id="null-query"),
        pytest.param({"query": 123}, "query", id="non-string-query"),
        pytest.param({"query": "退货", "top_k": 0}, "top_k", id="top-k-too-small"),
        pytest.param({"query": "退货", "top_k": 11}, "top_k", id="top-k-too-large"),
        pytest.param({"query": "退货", "top_k": "many"}, "top_k", id="invalid-top-k"),
        pytest.param(
            {"query": "退货", "document_id": 123},
            "document_id",
            id="non-string-document-id",
        ),
    ],
)
def test_invalid_model_fields_are_rejected(mock_openai, data, invalid_field):
    mock_create = mock_openai.return_value.chat.completions.create
    mock_create.return_value.choices[0].message.content = json.dumps(data)

    with pytest.raises(ExtractionError, match="字段校验失败") as exc_info:
        generate_search_intent("退货运费谁承担？", model_route("approved_cloud"))

    cause = exc_info.value.__cause__
    assert isinstance(cause, ValidationError)
    assert {error["loc"] for error in cause.errors()} == {(invalid_field,)}
    mock_create.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [RuntimeError("模型调用失败"), OpenAIError("模型服务不可用")],
    ids=["runtime-error", "openai-error"],
)
def test_model_call_failure_propagates(mock_openai, error):
    mock_create = mock_openai.return_value.chat.completions.create
    mock_create.side_effect = error

    with pytest.raises(type(error)) as exc_info:
        generate_search_intent("退货运费谁承担？", model_route("approved_cloud"))

    assert exc_info.value is error
    mock_create.assert_called_once()


@pytest.mark.parametrize(
    ("policy", "generate", "args", "failure", "expected_read", "attempts"),
    [
        ("local_only", generate_answer, ("Q", []), httpx2.ReadTimeout, 60, 1),
        ("local_only", generate_customer_answer, ("Q", [], []), httpx2.ReadTimeout, 60, 1),
        ("local_only", generate_search_intent, ("Q",), httpx2.ReadTimeout, 25, 2),
        ("approved_cloud", generate_answer, ("Q", []), httpx2.ReadTimeout, 25, 2),
        ("approved_cloud", generate_customer_answer, ("Q", [], []), httpx2.ReadTimeout, 25, 2),
        ("approved_cloud", generate_search_intent, ("Q",), httpx2.ReadTimeout, 25, 2),
        ("local_only", generate_answer, ("Q", []), httpx2.ConnectTimeout, 60, 2),
    ],
)
def test_model_wire_timeouts(monkeypatch, policy, generate, args, failure, expected_read, attempts):
    """Inspect the real SDK's outgoing timeout options and retries without opening a socket."""
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "local-test")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LLM_MODEL", "cloud-test")
    monkeypatch.setenv("LLM_API_KEY", "test")
    seen = []

    def fail(_transport, request):
        seen.append(request.extensions["timeout"])
        raise failure("test timeout", request=request)

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", fail)
    with patch("app.services.retry_executor.time.sleep"), pytest.raises(APITimeoutError):
        generate(*args, route=model_route(policy))

    assert seen == [{"connect": 25, "read": expected_read, "write": 25, "pool": 25}] * attempts
