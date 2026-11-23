from openai import APIConnectionError, APIStatusError


def should_retry_model_error(exc: Exception) -> bool:
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        if exc.code == "insufficient_quota":
            return False
        elif exc.status_code == 408 or exc.status_code == 409 or exc.status_code == 429:
            return True
        elif exc.status_code >= 500 and exc.status_code <= 599:
            return True
    return False
