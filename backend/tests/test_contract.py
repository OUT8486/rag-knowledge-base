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

    with pytest.raises(ExtractionError, match="字段校验失败") as exc_info:
        parse_contract(json.dumps(valid_contract_data))

    cause = exc_info.value.__cause__
    assert isinstance(cause, ValidationError)
    assert {error["loc"] for error in cause.errors()} == {(field,)}


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        ("2024-02-29", "2024-03-01"),
        ("2000-02-29", "2000-03-01"),
        ("0001-01-01", "9999-12-31"),
    ],
)
def test_valid_dates_remain_strings(valid_contract_data, start_date, end_date):
    valid_contract_data["start_date"] = start_date
    valid_contract_data["end_date"] = end_date

    contract = parse_contract(json.dumps(valid_contract_data))

    assert isinstance(contract.start_date, str)
    assert isinstance(contract.end_date, str)
    assert contract.model_dump() == valid_contract_data


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-date",
        "20261116",
        "2026-1-16",
        "2026-11-6",
        "26-11-16",
        "02026-11-16",
        "2026/11/16",
        "16-11-2026",
        "2026-W47-1",
        "2026-11-16T00:00:00",
        "2026-11-16 00:00:00",
        "2026-11-16T00:00:00Z",
        " 2026-11-16",
        "2026-11-16 ",
        "2026-11-16\n",
        "２０２６-１１-１６",
    ],
)
def test_date_fields_reject_invalid_format(valid_contract_data, field, value):
    # 日期必须严格符合 YYYY-MM-DD，不接受时间、空白或其他 ISO 日期表示。
    valid_contract_data[field] = value

    with pytest.raises(ExtractionError, match="日期格式必须为 YYYY-MM-DD") as exc_info:
        parse_contract(json.dumps(valid_contract_data))

    cause = exc_info.value.__cause__
    assert isinstance(cause, ValidationError)
    assert {error["loc"] for error in cause.errors()} == {(field,)}


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize(
    "value",
    [
        "2026-02-29",
        "1900-02-29",
        "2026-04-31",
        "2026-00-16",
        "2026-13-16",
        "2026-11-00",
        "2026-11-32",
        "0000-01-01",
    ],
)
def test_date_fields_reject_nonexistent_dates(valid_contract_data, field, value):
    valid_contract_data[field] = value

    with pytest.raises(ExtractionError, match="日期不存在") as exc_info:
        parse_contract(json.dumps(valid_contract_data))

    cause = exc_info.value.__cause__
    assert isinstance(cause, ValidationError)
    assert {error["loc"] for error in cause.errors()} == {(field,)}


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        ("2027-11-15", "2026-11-16"),
        ("2026-11-17", "2026-11-16"),
        ("2024-03-01", "2024-02-29"),
    ],
)
def test_end_date_cannot_precede_start_date(valid_contract_data, start_date, end_date):
    valid_contract_data["start_date"] = start_date
    valid_contract_data["end_date"] = end_date

    with pytest.raises(ExtractionError, match="结束日期早于开始日期") as exc_info:
        parse_contract(json.dumps(valid_contract_data))

    cause = exc_info.value.__cause__
    assert isinstance(cause, ValidationError)
    assert {error["loc"] for error in cause.errors()} == {()}


@pytest.mark.parametrize("value", ["2026-11-16", "2024-02-29"])
def test_same_day_contract_is_allowed(valid_contract_data, value):
    valid_contract_data["start_date"] = value
    valid_contract_data["end_date"] = value

    contract = parse_contract(json.dumps(valid_contract_data))

    assert contract.model_dump() == valid_contract_data


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_date", None),
        ("end_date", None),
        ("start_date", "not-a-date"),
        ("end_date", "2026-02-30"),
        ("amount", "12000"),
        ("contract_type", "invalid"),
    ],
)
def test_field_validation_precedes_date_order(valid_contract_data, field, value):
    # 日期倒置且有字段错误时，必须先报告字段错误，不能执行模型的起止检查。
    valid_contract_data["start_date"] = "2027-11-15"
    valid_contract_data["end_date"] = "2026-11-16"
    valid_contract_data[field] = value

    with pytest.raises(ExtractionError, match="字段校验失败") as exc_info:
        parse_contract(json.dumps(valid_contract_data))

    cause = exc_info.value.__cause__
    assert isinstance(cause, ValidationError)
    assert {error["loc"] for error in cause.errors()} == {(field,)}


def test_extra_fields_are_ignored(valid_contract_data):
    raw = json.dumps({**valid_contract_data, "vendor": "测试公司"})

    contract = parse_contract(raw)

    assert contract.model_dump() == valid_contract_data
