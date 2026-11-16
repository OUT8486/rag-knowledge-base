"""parse_intent 的行为测试：只验证文本到结构体的转换，不调用模型。"""

import pytest

from app.services.extract import ExtractionError, SearchIntent, parse_intent


def test_valid_json():
    raw = '{"query": "退货运费谁承担", "top_k": 3, "document_id": "doc-1"}'

    intent = parse_intent(raw)

    assert isinstance(intent, SearchIntent)
    assert intent.query == "退货运费谁承担"
    assert intent.top_k == 3
    assert intent.document_id == "doc-1"


def test_json_in_code_fence():
    raw = '```json\n{"query": "发票怎么开"}\n```'

    intent = parse_intent(raw)

    assert intent.query == "发票怎么开"


def test_default_top_k():
    raw = '{"query": "会员积分规则"}'

    intent = parse_intent(raw)

    assert intent.top_k == 5
    assert intent.document_id is None


def test_missing_query():
    raw = '{"top_k": 3}'

    with pytest.raises(ExtractionError):
        parse_intent(raw)


def test_top_k_out_of_range():
    raw = '{"query": "退货", "top_k": 99}'

    with pytest.raises(ExtractionError):
        parse_intent(raw)


def test_not_json():
    raw = "我不知道该检索什么"

    with pytest.raises(ExtractionError):
        parse_intent(raw)


def test_not_object():
    raw = '["退货", "发票"]'

    with pytest.raises(ExtractionError):
        parse_intent(raw)


def test_blank_text():
    raw = "   \n  "

    with pytest.raises(ExtractionError):
        parse_intent(raw)
