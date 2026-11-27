import httpx2
from openai import APIConnectionError, APIStatusError, APITimeoutError


def should_retry_model_error(exc: Exception, *, retry_read_timeout: bool = True) -> bool:
    if isinstance(exc, APITimeoutError) and isinstance(exc.__cause__, httpx2.ReadTimeout):
        return retry_read_timeout
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        if exc.code == "insufficient_quota":
            return False
        return exc.status_code in (408, 409, 429) or 500 <= exc.status_code <= 599
    return False
