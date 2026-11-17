"""parse_contract 的行为测试：只验证文本到结构体的转换，不调用模型。"""

import json

import pytest
from pydantic import ValidationError

from app.services.contract import ContractInfo, parse_contract
from app.services.extract import ExtractionError


@pytest.fixture
def valid_contract_data():
    return {
        "contract_type": "service",
        "amount": 12000,
        "start_date": "2026-11-16",
        "end_date": "2027-11-15",
    }


def test_valid_json(valid_contract_data):
    contract = parse_contract(json.dumps(valid_contract_data))

    assert isinstance(contract, ContractInfo)
    assert contract.model_dump() == valid_contract_data


@pytest.mark.parametrize("contract_type", ["purchase", "service", "lease", "other"])
def test_supported_contract_types(valid_contract_data, contract_type):
    valid_contract_data["contract_type"] = contract_type

    contract = parse_contract(json.dumps(valid_contract_data))

    assert contract.contract_type == contract_type


@pytest.mark.parametrize("amount", [1, 0.01, 12000.5])
def test_positive_amount(valid_contract_data, amount):
    valid_contract_data["amount"] = amount

    contract = parse_contract(json.dumps(valid_contract_data))

    assert contract.amount == amount
    assert isinstance(contract.amount, float)


def test_json_with_surrounding_whitespace(valid_contract_data):
    raw = f" \t\r\n{json.dumps(valid_contract_data)}\r\n\t "

    contract = parse_contract(raw)

    assert contract.model_dump() == valid_contract_data


@pytest.mark.parametrize("language", ["json", "JSON", ""])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_json_in_code_fence(valid_contract_data, language, newline):
    payload = json.dumps(valid_contract_data)
    raw = f" \t{newline}```{language}{newline}  {payload}  {newline}```{newline}\t "

    contract = parse_contract(raw)

    assert contract.model_dump() == valid_contract_data


@pytest.mark.parametrize("raw", ["", " ", "\t", "\n", " \t\r\n "])
def test_blank_text(raw):
    with pytest.raises(ExtractionError):
        parse_contract(raw)


@pytest.mark.parametrize(
    "raw",
    ["```\n```", "```json\n \t\n```", "```JSON\r\n\r\n```"],
)
def test_empty_code_fence(raw):
    with pytest.raises(ExtractionError, match="模型输出不是合法 JSON"):
        parse_contract(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "我无法提取合同信息",
        "{",
        "{'contract_type': 'service'}",
        '{"contract_type": "service",}',
        "说明：{}",
        "{}\n额外说明",
    ],
)
def test_invalid_json(raw):
    with pytest.raises(ExtractionError, match="模型输出不是合法 JSON") as exc_info:
        parse_contract(raw)

    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        '[{"contract_type": "service"}]',
        '"service"',
        "null",
        "true",
        "false",
        "12000",
        "12.5",
    ],
)
def test_non_object_json(raw):
    with pytest.raises(ExtractionError, match="模型输出的顶层结构不是 JSON 对象"):
        parse_contract(raw)


@pytest.mark.parametrize("contract_type", ["employment", "SERVICE", "", None, 1])
def test_invalid_contract_type(valid_contract_data, contract_type):
    valid_contract_data["contract_type"] = contract_type

    with pytest.raises(ExtractionError, match="字段校验失败"):
        parse_contract(json.dumps(valid_contract_data))


@pytest.mark.parametrize("field", ["contract_type", "amount", "start_date", "end_date"])
def test_missing_required_field(valid_contract_data, field):
    del valid_contract_data[field]

    with pytest.raises(ExtractionError, match="字段校验失败") as exc_info:
        parse_contract(json.dumps(valid_contract_data))

    cause = exc_info.value.__cause__
    assert isinstance(cause, ValidationError)
    assert any(error["loc"] == (field,) for error in cause.errors())


def test_empty_object():
    with pytest.raises(ExtractionError, match="字段校验失败") as exc_info:
        parse_contract("{}")

    cause = exc_info.value.__cause__
    assert isinstance(cause, ValidationError)
    assert {error["loc"] for error in cause.errors()} == {
        ("contract_type",),
        ("amount",),
        ("start_date",),
        ("end_date",),
    }


@pytest.mark.parametrize("amount", [0, -1, -0.01])
def test_non_positive_amount(valid_contract_data, amount):
    valid_contract_data["amount"] = amount

    with pytest.raises(ExtractionError, match="字段校验失败"):
        parse_contract(json.dumps(valid_contract_data))


@pytest.mark.parametrize("amount", ["12000", "", True, False, None, [], {}])
def test_amount_rejects_non_numeric_values(valid_contract_data, amount):
    valid_contract_data["amount"] = amount

    with pytest.raises(ExtractionError, match="字段校验失败"):
        parse_contract(json.dumps(valid_contract_data))


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize("value", [None, 20261116, True, [], {}])
def test_date_fields_require_strings(valid_contract_data, field, value):
    valid_contract_data[field] = value

    with pytest.raises(ExtractionError, match="字段校验失败"):
        parse_contract(json.dumps(valid_contract_data))


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        ("not-a-date", "also-not-a-date"),
        ("", ""),
        ("2027-11-15", "2026-11-16"),
    ],
)
def test_date_strings_are_not_validated(valid_contract_data, start_date, end_date):
    # 当前模型只要求日期是字符串，没有日期格式或先后顺序约束。
    valid_contract_data["start_date"] = start_date
    valid_contract_data["end_date"] = end_date

    with pytest.raises(ExtractionError, match="字段校验失败|日期不存在|结束日期早于开始日期"):
        contract = parse_contract(json.dumps(valid_contract_data))
        assert contract.start_date == start_date
        assert contract.end_date == end_date


def test_extra_fields_are_ignored(valid_contract_data):
    raw = json.dumps({**valid_contract_data, "vendor": "测试公司"})

    contract = parse_contract(raw)

    assert contract.model_dump() == valid_contract_data
