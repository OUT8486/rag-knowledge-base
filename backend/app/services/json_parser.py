"""模型输出文本 → 字典"""
import json

from app.services.errors import ExtractionError


def parse_json_object(raw: str)-> dict:
    """模型输出文本 → 字典"""
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
    
    return data