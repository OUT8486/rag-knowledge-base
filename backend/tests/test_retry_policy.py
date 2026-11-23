"""should_retry_model_error 的行为测试：用内存中的 httpx2/openai 异常对象，不发送真实请求。"""

import httpx2
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.services.errors import ExtractionError
from app.services.retry_policy import should_retry_model_error

REQUEST_URL = "https://example.invalid/v1/chat/completions"


@pytest.fixture
def http_request():
    """每个用例一个独立的 httpx2.Request，只构造内存对象。"""
    return httpx2.Request("POST", REQUEST_URL)


def make_status_error(request, status_code, body=None):
    """构造带指定 HTTP 状态码的 APIStatusError，body 决定 error.code。"""
    response = httpx2.Response(status_code, request=request)
    return APIStatusError("mock service error", response=response, body=body)


def test_constructed_errors_carry_expected_fields(http_request):
    # 先证明构造方式本身可靠，后面的断言才有意义。
    error = make_status_error(http_request, 503)
    assert error.status_code == 503
    assert error.code is None

    quota = make_status_error(http_request, 429, body={"code": "insufficient_quota"})
    assert quota.status_code == 429
    assert quota.code == "insufficient_quota"

    assert isinstance(APITimeoutError(request=http_request), APIConnectionError)
    assert not isinstance(APIConnectionError(request=http_request), APIStatusError)


def test_connection_error_is_retried(http_request):
    error = APIConnectionError(request=http_request)

    assert should_retry_model_error(error) is True


def test_timeout_error_is_retried(http_request):
    # APITimeoutError 是 APIConnectionError 的子类，命中同一个分支。
    error = APITimeoutError(request=http_request)

    assert isinstance(error, APIConnectionError)
    assert should_retry_model_error(error) is True


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(None, id="no-body"),
        pytest.param({}, id="empty-body"),
        pytest.param({"code": None}, id="null-code"),
        pytest.param({"code": "rate_limit_exceeded"}, id="other-code"),
    ],
)
def test_rate_limit_without_quota_code_is_retried(http_request, body):
    error = make_status_error(http_request, 429, body=body)

    assert error.status_code == 429
    assert error.code != "insufficient_quota"
    assert should_retry_model_error(error) is True


@pytest.mark.parametrize(
    "status_code",
    [500, 502, 503, 504, 599],
    ids=["500", "502", "503", "504", "599"],
)
def test_server_error_is_retried(http_request, status_code):
    error = make_status_error(http_request, status_code)

    assert error.status_code == status_code
    assert should_retry_model_error(error) is True


@pytest.mark.parametrize(
    "status_code",
    [400, 401, 403, 404, 422],
    ids=["400", "401", "403", "404", "422"],
)
def test_client_error_is_not_retried(http_request, status_code):
    error = make_status_error(http_request, status_code)

    assert error.status_code == status_code
    assert should_retry_model_error(error) is False


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        pytest.param(429, {"code": "insufficient_quota"}, id="429-quota"),
        pytest.param(
            503,
            {"code": "insufficient_quota"},
            id="503-quota-code-wins",
        ),
        pytest.param(
            400,
            {"code": "insufficient_quota"},
            id="400-quota",
        ),
    ],
)
def test_insufficient_quota_is_not_retried(http_request, status_code, body):
    # 业务码 insufficient_quota 优先于状态码：重试只会继续消耗失败请求。
    error = make_status_error(http_request, status_code, body=body)

    assert error.code == "insufficient_quota"
    assert should_retry_model_error(error) is False


@pytest.mark.parametrize(
    "status_code",
    [408, 409],
    ids=["408", "409"],
)
def test_conflict_and_request_timeout_status_are_retried(http_request, status_code):
    error = make_status_error(http_request, status_code)

    assert error.status_code == status_code
    assert should_retry_model_error(error) is True


def test_extraction_error_is_not_retried():
    # 模型本身已正常返回，只是输出不合规，重试同样的提示词没有意义。
    error = ExtractionError("模型输出不是合法 JSON")

    assert should_retry_model_error(error) is False


@pytest.mark.parametrize(
    "status_code",
    [199, 200, 302, 600],
    ids=["199", "200", "302", "600"],
)
def test_non_5xx_success_and_out_of_range_status_are_not_retried(
    http_request, status_code
):
    error = make_status_error(http_request, status_code)

    assert error.status_code == status_code
    assert should_retry_model_error(error) is False

def test_my_test(http_request, status_code=499):
    error = make_status_error(http_request, status_code)

    assert error.status_code == status_code
    assert should_retry_model_error(error) is False
