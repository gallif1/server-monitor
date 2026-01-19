import httpx

from app.healthchecks.http_check import check_http


class _Resp:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _Client:
    def __init__(self, resp: _Resp | None = None, raise_exc: Exception | None = None):
        self._resp = resp
        self._raise = raise_exc

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get(self, url: str):
        if self._raise:
            raise self._raise
        return self._resp


def test_check_http_success_2xx(mocker):
    mocker.patch("app.healthchecks.http_check.httpx.Client", return_value=_Client(_Resp(204)))
    res = check_http("https://example.com", timeout_seconds=1.0)
    assert res["is_success"] is True
    assert res["http_status"] == 204
    assert res["error"] is None
    assert isinstance(res["latency_ms"], int)


def test_check_http_failure_non_2xx(mocker):
    mocker.patch("app.healthchecks.http_check.httpx.Client", return_value=_Client(_Resp(503)))
    res = check_http("https://example.com", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert res["http_status"] == 503


def test_check_http_exception_sets_error(mocker):
    mocker.patch(
        "app.healthchecks.http_check.httpx.Client",
        return_value=_Client(raise_exc=httpx.TimeoutException("boom")),
    )
    res = check_http("https://example.com", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert res["http_status"] is None
    assert "boom" in (res["error"] or "")


def test_check_http_latency_exceeded_forces_failure(mocker):
    # force perf_counter to simulate slow call
    times = iter([0.0, 2.0])
    mocker.patch("app.healthchecks.http_check.time.perf_counter", side_effect=lambda: next(times))
    mocker.patch("app.healthchecks.http_check.httpx.Client", return_value=_Client(_Resp(200)))
    res = check_http("https://example.com", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert res["http_status"] == 200
    assert "Latency exceeded" in (res["error"] or "")
