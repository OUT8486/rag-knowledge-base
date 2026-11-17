"""把模型返回的文本转换成结构化的检索意图。"""

import json

from pydantic import BaseModel, Field, ValidationError

from app.services.errors import ExtractionError
from app.services.json_parser import parse_json_object


class SearchIntent(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=5, ge=1, le=10)
    document_id: str | None = None


def parse_intent(raw: str) -> SearchIntent:
    data = parse_json_object(raw)
    
    #   用 SearchIntent(**data) 校验。
    #   pydantic 的 ValidationError 要转成 ExtractionError；
    #   校验通过就 return 这个 SearchIntent 对象。
    try:
        return SearchIntent(**data)
    except ValidationError as exc:
        raise ExtractionError(f"字段校验失败：{exc}") from exc

def is_json_object(raw):
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False
    if not isinstance(data, dict):
        return False
    else:
        return True