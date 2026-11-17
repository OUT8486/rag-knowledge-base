"""将模型输出的 JSON 文本转成py数据对象"""

import json
import re
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.services.errors import ExtractionError
from app.services.json_parser import parse_json_object


class ContractInfo(BaseModel):
    contract_type: Literal["purchase", "service", "lease", "other"]
    amount: float = Field(gt=0, strict=True)
    start_date: str
    end_date: str

    @field_validator("start_date", "end_date", mode="after")
    @classmethod
    def validate_date(cls, value: str) -> str:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("日期格式必须为 YYYY-MM-DD")

        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("日期不存在") from exc

        return value

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        # 已校验的 YYYY-MM-DD 字符串按字典序比较即为日期先后顺序。
        if self.start_date > self.end_date:
            raise ValueError("结束日期早于开始日期")
        return self


def parse_contract(raw: str) -> ContractInfo:
    data = parse_json_object(raw)

    # 第 5 步：完成字段与起止关系校验，ValidationError 要转成 ExtractionError。
    try:
        return ContractInfo(**data)
    except ValidationError as exc:
        raise ExtractionError(f"字段校验失败：{exc}") from exc
