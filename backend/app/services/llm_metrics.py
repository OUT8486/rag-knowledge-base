def build_model_metrics(response, elapsed_ms):
    """把模型响应与已有耗时整理成一个普通字典。

    response：SDK响应对象，保证choices至少有一项。
    elapsed_ms：调用方已经计算好的毫秒耗时。
    返回：包含下面六个字段的字典。
    """

    # 先准备输出容器。用量未知时，三个token字段保留None。
    # elapsed_ms、finish_reason、answer_empty目前也是占位，需完成下面TODO。
    metrics = {
        "elapsed_ms": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "finish_reason": None,
        "answer_empty": None,
    }

    # TODO 1：把传入的elapsed_ms保存到metrics对应的键中。
    # 这里不需要重新计时。
    metrics["elapsed_ms"] = elapsed_ms

    usage = response.usage
    if usage is not None:
        # TODO 2：读取usage中的三个token计数，分别写入metrics。
        # usage是对象，读取属性用点号；metrics是字典，写入用键。
        metrics["completion_tokens"] = usage.completion_tokens
        metrics["prompt_tokens"] = usage.prompt_tokens
        metrics["total_tokens"] = usage.total_tokens
    # 没有usage时，不读取它的属性，三个token字段保持None。

    # 下面两行只负责取得第一项回答及其文本。
    choice = response.choices[0]
    content = choice.message.content

    # TODO 3：读取choice的停止原因，写入metrics。
    metrics["finish_reason"] = choice.finish_reason

    # TODO 4：根据content填写answer_empty，最终应为True或False。
    # 分别考虑：None、空串、纯空白字符串、含有实际文字。
    # 注意先处理None，再进行字符串操作。
    if content is None:
        metrics["answer_empty"] = True
    elif content.strip() == "":
        metrics["answer_empty"] = True
    else:
        metrics["answer_empty"] = False
    
    return metrics
