"""build_model_metrics 的行为测试：用假的 SDK 响应对象，不调用真实模型。"""

from types import SimpleNamespace

import pytest

from app.services.llm_metrics import build_model_metrics

METRICS_KEYS = {
    "elapsed_ms",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "finish_reason",
    "answer_empty",
}


def make_response(content, finish_reason="stop", usage=(20, 30, 50)):
    """按 OpenAI SDK 响应的形状造一个假对象。

    usage 传 None 表示服务端没有报告用量。
    """
    if usage is None:
        usage_obj = None
    else:
        prompt_tokens, completion_tokens, total_tokens = usage
        usage_obj = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=usage_obj,
    )


def test_normal_answer_maps_all_six_fields():
    response = make_response("RAG是检索增强生成。", finish_reason="stop")

    metrics = build_model_metrics(response, 1250.5)

    assert metrics == {
        "elapsed_ms": 1250.5,
        "prompt_tokens": 20,
        "completion_tokens": 30,
        "total_tokens": 50,
        "finish_reason": "stop",
        "answer_empty": False,
    }


def test_metrics_dict_has_exactly_six_keys():
    metrics = build_model_metrics(make_response("有答案"), 12)

    assert set(metrics.keys()) == METRICS_KEYS


def test_elapsed_ms_is_stored_as_passed():
    metrics = build_model_metrics(make_response("有答案"), 0)

    assert metrics["elapsed_ms"] == 0


def test_truncated_answer_is_not_empty():
    response = make_response(
        "RAG首先检索资料，然后", finish_reason="length", usage=(20, 128, 148)
    )

    metrics = build_model_metrics(response, 2000)

    assert metrics["finish_reason"] == "length"
    assert metrics["answer_empty"] is False
    assert metrics["prompt_tokens"] == 20
    assert metrics["completion_tokens"] == 128
    assert metrics["total_tokens"] == 148


def test_usage_none_keeps_token_fields_unknown():
    response = make_response("  \n\t  ", usage=None)

    metrics = build_model_metrics(response, 600)

    assert metrics["prompt_tokens"] is None
    assert metrics["completion_tokens"] is None
    assert metrics["total_tokens"] is None
    assert metrics["answer_empty"] is True
    assert metrics["elapsed_ms"] == 600


def test_zero_usage_is_kept_as_zero_not_none():
    """0 是有意义的用量，不能被当成“没有用量”而改回 None。"""

    response = make_response("有答案", usage=(0, 0, 0))

    metrics = build_model_metrics(response, 10)

    assert metrics["prompt_tokens"] == 0
    assert metrics["completion_tokens"] == 0
    assert metrics["total_tokens"] == 0
    assert metrics["prompt_tokens"] is not None


def test_content_none_is_empty_and_does_not_raise():
    response = make_response(None, finish_reason="length")

    metrics = build_model_metrics(response, 1800)

    assert metrics["answer_empty"] is True
    assert metrics["finish_reason"] == "length"


@pytest.mark.parametrize(
    "content",
    ["", " ", "\t", "\n", "  \t\r\n  "],
    ids=["empty", "space", "tab", "newline", "mixed"],
)
def test_blank_content_is_empty(content):
    metrics = build_model_metrics(make_response(content), 100)

    assert metrics["answer_empty"] is True


@pytest.mark.parametrize(
    "content",
    ["有答案", "  有答案  ", "\nRAG是检索增强生成。\t"],
    ids=["plain", "padded", "surrounded"],
)
def test_non_blank_content_is_not_empty(content):
    metrics = build_model_metrics(make_response(content), 100)

    assert metrics["answer_empty"] is False


def test_answer_empty_is_a_real_boolean():
    metrics = build_model_metrics(make_response("有答案"), 100)

    assert isinstance(metrics["answer_empty"], bool)

def test_my_test(content="已找到资料", finish_reason="stop", usage=None, time=250):
    response = make_response(content, "stop", None)
    metrics = build_model_metrics(response, 250)
    
    assert metrics == {
        "elapsed_ms": 250,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "finish_reason": "stop",
        "answer_empty": False,
    }