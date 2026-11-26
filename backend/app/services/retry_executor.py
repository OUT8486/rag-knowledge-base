
import time

from app.services.retry_policy import should_retry_model_error


def call_with_retry(operation, max_attempts: int = 3, base_delay: float = 0.5):
    times = 0
    while max_attempts > 0:
        try:
            oper_result = operation()
        except Exception as exc:
            max_attempts -= 1
            zige = should_retry_model_error(exc)
            if zige == False or max_attempts == 0:
                raise exc
            if zige == True and max_attempts > 0:
                time.sleep(base_delay*(2**times))
            times += 1
        else:
            break
    return oper_result