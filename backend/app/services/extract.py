"""把模型返回的文本转换成结构化的检索意图。"""

import json

from pydantic import BaseModel, Field, ValidationError


class ExtractionError(Exception):
    """模型输出无法转换成合法的检索意图。"""


class SearchIntent(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=5, ge=1, le=10)
    document_id: str | None = None


def parse_intent(raw: str) -> SearchIntent:
    """把模型输出的文本解析并校验成 SearchIntent。

    按顺序实现下面 5 步，每步失败都只抛 ExtractionError。
    """
    # 第 1 步：去掉首尾空白，结果存进 text。
    #   如果 text 为空，抛 ExtractionError。
    text = raw.strip()
    if not text:
        raise ExtractionError

    # 第 2 步：如果 text 以三个反引号开头，说明被包进代码围栏了。
    #   去掉开头的反引号和可能跟着的语言标记（json、JSON 等），
    #   再去掉结尾的三反引号，最后 strip() 一次。
    if text.startswith("```"):
        text = text.removeprefix("```")
        text = text.partition("\n")[2]
        text = text.removesuffix("```")
        text = text.strip()

    # 第 3 步：用 json.loads(text) 解析成 data。
    #   json.JSONDecodeError 要转成 ExtractionError。
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"模型输出不是合法 JSON：{exc}") from exc
    
    # 第 4 步：如果 data 不是 dict（比如是 list 或 str），抛 ExtractionError。
    if not isinstance(data, dict):
        raise ExtractionError("模型输出的顶层结构不是 JSON 对象")
    
    # 第 5 步：用 SearchIntent(**data) 校验。
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