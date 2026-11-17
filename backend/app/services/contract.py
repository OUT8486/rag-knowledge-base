"""将模型输出的 JSON 文本转成py数据对象"""

from datetime import date
import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.services.extract import ExtractionError


class ContractInfo(BaseModel):
    contract_type: Literal["purchase", "service", "lease", "other"]
    amount: float = Field(gt=0, strict=True)
    start_date: date
    end_date: date

def parse_contract(raw: str) ->ContractInfo:
    """把模型输出的文本解析并校验成 ContractInfo。
    
    按顺序实现下面 5 步，每步失败都只抛 ExtractionError。
    """
    try:
    
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
        
        if data["start_date"] > data["end_date"]:
            raise ExtractionError("结束日期早于开始日期")
        
        try:
            return ContractInfo(**data)
        except ValidationError as exc:
            raise ExtractionError(f"字段校验失败：{exc}") from exc
    except ValueError as exc:
        raise ExtractionError("日期不存在") from exc