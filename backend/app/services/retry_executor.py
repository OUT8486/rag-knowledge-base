import time

from app.services.retry_policy import should_retry_model_error


def call_with_retry(
    operation, max_attempts: int = 3, base_delay: float = 0.5, *, retry_read_timeout: bool = True
):
    times = 0
    while max_attempts > 0:
        try:
            oper_result = operation()
        except Exception as exc:
            max_attempts -= 1
            if max_attempts == 0 or not should_retry_model_error(
                exc, retry_read_timeout=retry_read_timeout
            ):
                raise
            time.sleep(base_delay * (2**times))
            times += 1
        else:
            break
    return oper_result
