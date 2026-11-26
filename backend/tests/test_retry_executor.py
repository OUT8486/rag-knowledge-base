"""call_with_retry 的调用次数、退避等待和结果/异常透传测试。"""

from unittest.mock import Mock, call, patch

import httpx2
import pytest
from openai import APIConnectionError, APIStatusError

from app.services.retry_executor import call_with_retry

REQUEST_URL = "https://example.invalid/v1/chat/completions"


@pytest.fixture
def http_request():
    return httpx2.Request("POST", REQUEST_URL)


def make_status_error(request, status_code, body=None):
    response = httpx2.Response(status_code, request=request)
    return APIStatusError("mock service error", response=response, body=body)


@pytest.mark.parametrize("result", [False, None], ids=["false", "none"])
def test_first_success_returns_false_or_none_without_waiting(result):
    operation = Mock(return_value=result)

    with patch("app.services.retry_executor.time.sleep") as sleep:
        actual = call_with_retry(operation)

    assert actual is result
    assert operation.call_count == 1
    sleep.assert_not_called()


def test_first_success_returns_value_without_waiting():
    result = object()
    operation = Mock(return_value=result)

    with patch("app.services.retry_executor.time.sleep") as sleep:
        actual = call_with_retry(operation)

    assert actual is result
    assert operation.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize(
    ("failures", "expected_waits"),
    [(1, [0.5]), (2, [0.5, 1.0])],
)
def test_connection_failures_then_success(failures, expected_waits, http_request):
    errors = [APIConnectionError(request=http_request) for _ in range(failures)]
    result = object()
    with patch("app.services.retry_executor.time.sleep") as sleep:
        # Side effects keep the number and ordering of attempts explicit.
        operation = Mock(side_effect=[*errors, result])
        actual = call_with_retry(operation)

    assert operation.call_count == failures + 1
    assert actual is result
    assert sleep.call_args_list == [call(delay) for delay in expected_waits]


def test_three_connection_failures_reraise_third_exception(http_request):
    errors = [APIConnectionError(request=http_request) for _ in range(3)]
    operation = Mock(side_effect=errors)

    with patch("app.services.retry_executor.time.sleep") as sleep:
        with pytest.raises(APIConnectionError) as raised:
            call_with_retry(operation)

    assert operation.call_count == 3
    assert raised.value is errors[2]
    assert sleep.call_args_list == [call(0.5), call(1.0)]


def test_http_400_is_not_retried(http_request):
    error = make_status_error(http_request, 400)
    operation = Mock(side_effect=error)

    with patch("app.services.retry_executor.time.sleep") as sleep:
        with pytest.raises(APIStatusError) as raised:
            call_with_retry(operation)

    assert operation.call_count == 1
    assert raised.value is error
    sleep.assert_not_called()


def test_insufficient_quota_is_not_retried(http_request):
    error = make_status_error(
        http_request, 429, body={"code": "insufficient_quota"}
    )
    operation = Mock(side_effect=error)

    with patch("app.services.retry_executor.time.sleep") as sleep:
        with pytest.raises(APIStatusError) as raised:
            call_with_retry(operation)

    assert operation.call_count == 1
    assert raised.value is error
    sleep.assert_not_called()


def test_quota_error_after_connection_failure_is_reraised(http_request):
    connection_error = APIConnectionError(request=http_request)
    quota_error = make_status_error(
        http_request, 429, body={"code": "insufficient_quota"}
    )
    operation = Mock(side_effect=[connection_error, quota_error])

    with patch("app.services.retry_executor.time.sleep") as sleep:
        with pytest.raises(APIStatusError) as raised:
            call_with_retry(operation)

    assert operation.call_count == 2
    assert raised.value is quota_error
    assert sleep.call_args_list == [call(0.5)]


def test_max_attempts_one_does_not_retry(http_request):
    error = APIConnectionError(request=http_request)
    operation = Mock(side_effect=error)

    with patch("app.services.retry_executor.time.sleep") as sleep:
        with pytest.raises(APIConnectionError) as raised:
            call_with_retry(operation, max_attempts=1)

    assert operation.call_count == 1
    assert raised.value is error
    sleep.assert_not_called()


def test_non_default_base_delay_controls_entire_wait_sequence(http_request):
    errors = [APIConnectionError(request=http_request) for _ in range(3)]
    operation = Mock(side_effect=[*errors, "recovered"])

    with patch("app.services.retry_executor.time.sleep") as sleep:
        actual = call_with_retry(operation, max_attempts=4, base_delay=0.2)

    assert operation.call_count == 4
    assert actual == "recovered"
    assert sleep.call_args_list == [call(0.2), call(0.4), call(0.8)]
