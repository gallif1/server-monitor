import time
import httpx


def check_http(url: str, timeout_seconds: float = 45.0) -> dict:
    """
    Perform an HTTP(S) health check.
    Success conditions:
    - HTTP status code is 2xx
    - latency < timeout_seconds (enforced via request timeout)
    Returns a dict with:
    - is_success (bool)
    - latency_ms (int)
    - http_status (int|None)
    - error (str|None)
    """
    start = time.perf_counter()
    http_status = None
    error = None
    is_success = False

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(url)
            http_status = resp.status_code
            is_success = 200 <= resp.status_code < 300
    except Exception as e:
        error = str(e)
        is_success = False

    latency_ms = int((time.perf_counter() - start) * 1000)

    # Even if we got 2xx, treat it as failure if it exceeded 45 seconds (extra safety)
    if latency_ms >= int(timeout_seconds * 1000):
        is_success = False
        if error is None:
            error = f"Latency exceeded {timeout_seconds}s"

    return {
        "is_success": is_success,
        "latency_ms": latency_ms,
        "http_status": http_status,
        "error": error,
    }
