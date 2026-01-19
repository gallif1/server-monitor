import time
from ftplib import FTP
from urllib.parse import urlparse


def check_ftp(url: str, timeout_seconds: float = 45.0) -> dict:
    """
    Perform an FTP health check.
    Success conditions:
    - Successful TCP connection + FTP login (anonymous by default)
    - latency < timeout_seconds

    
    """
    start = time.perf_counter()
    error = None
    is_success = False

    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 21
    user = parsed.username or "anonymous"
    password = parsed.password or "anonymous@"

    try:
        if not host:
            raise ValueError("Invalid FTP URL (missing host)")

        ftp = FTP()
        ftp.connect(host=host, port=port, timeout=timeout_seconds)
        ftp.login(user=user, passwd=password)
        ftp.quit()
        is_success = True
    except Exception as e:
        error = str(e)
        is_success = False

    latency_ms = int((time.perf_counter() - start) * 1000)

    if latency_ms >= int(timeout_seconds * 1000):
        is_success = False
        if error is None:
            error = f"Latency exceeded {timeout_seconds}s"

    return {
        "is_success": is_success,
        "latency_ms": latency_ms,
        "http_status": None,   # not relevant for FTP
        "error": error,
    }
