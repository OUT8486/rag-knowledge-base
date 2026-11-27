def build_model_metrics(response, elapsed_ms):
    usage = getattr(response, "usage", None)
    choice = response.choices[0]
    return {
        "elapsed_ms": elapsed_ms,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "finish_reason": getattr(choice, "finish_reason", None),
        "answer_empty": not (choice.message.content or "").strip(),
    }
