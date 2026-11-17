"""直接测试 parse_json_object 的字典返回值和解析失败行为。"""

import json

import pytest

from app.services.errors import ExtractionError
from app.services.json_parser import parse_json_object


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("{}", {}, id="empty-object"),
        pytest.param(
            '{"query": "退货运费谁承担", "top_k": 3, "document_id": "doc-1"}',
            {"query": "退货运费谁承担", "top_k": 3, "document_id": "doc-1"},
            id="simple-object",
        ),
        pytest.param(
            '{"标题": "合同", "amount": 12.5, "active": true, "note": null, '
            '"items": [1, false, {"name": "附件"}], "metadata": {"year": 2026}}',
            {
                "标题": "合同",
                "amount": 12.5,
                "active": True,
                "note": None,
                "items": [1, False, {"name": "附件"}],
                "metadata": {"year": 2026},
            },
            id="nested-object",
        ),
    ],
)
def test_valid_json_object(raw, expected):
    data = parse_json_object(raw)

    assert isinstance(data, dict)
    assert data == expected


def test_json_object_with_surrounding_whitespace():
    raw = ' \t\r\n{"message": "  测试  "}\r\n\t '

    data = parse_json_object(raw)

    assert data == {"message": "  测试  "}


@pytest.mark.parametrize("language", ["json", "JSON", ""])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_json_object_in_code_fence(language, newline):
    raw = (
        f" \t{newline}```{language}{newline}"
        f'  {{"query": "发票怎么开"}}  {newline}```{newline}\t '
    )

    data = parse_json_object(raw)

    assert data == {"query": "发票怎么开"}


@pytest.mark.parametrize("raw", ["", " ", "\t", "\n", " \t\r\n "])
def test_blank_text_raises_extraction_error(raw):
    with pytest.raises(ExtractionError):
        parse_json_object(raw)


@pytest.mark.parametrize(
    "raw",
    ["```\n```", "```json\n \t\n```", "```JSON\r\n\r\n```"],
)
def test_empty_code_fence_raises_extraction_error(raw):
    with pytest.raises(ExtractionError, match="模型输出不是合法 JSON") as exc_info:
        parse_json_object(raw)

    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


@pytest.mark.parametrize(
    "raw",
    [
        "我不知道该输出什么",
        "{",
        "{'query': '退货'}",
        '{"query": "退货",}',
        "说明：{}",
        "{}\n额外说明",
        "{}{}",
        '```json\n{"query":}\n```',
        "```JSON\r\n{'query': '退货'}\r\n```",
    ],
)
def test_invalid_json_raises_extraction_error(raw):
    with pytest.raises(ExtractionError, match="模型输出不是合法 JSON") as exc_info:
        parse_json_object(raw)

    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        '[{"query": "退货"}]',
        '"退货"',
        "null",
        "true",
        "false",
        "12000",
        "12.5",
    ],
)
@pytest.mark.parametrize("fenced", [False, True], ids=["plain", "fenced"])
def test_non_object_json_raises_extraction_error(raw, fenced):
    if fenced:
        raw = f"```json\n{raw}\n```"

    with pytest.raises(ExtractionError, match="模型输出的顶层结构不是 JSON 对象"):
        parse_json_object(raw)
