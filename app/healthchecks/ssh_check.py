import time
import paramiko
from urllib.parse import urlparse


def check_ssh(url: str, timeout_seconds: float = 45.0) -> dict:
    """
    Perform an SSH health check.
    Success conditions:
    - Successful SSH connection
    - latency < timeout_seconds

    """
    start = time.perf_counter()
    error = None
    is_success = False

    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 22
    user = parsed.username
    password = parsed.password

    try:
        if not host:
            raise ValueError("Invalid SSH URL (missing host)")
        if not user or not password:
            raise ValueError("SSH URL must include username and password (ssh://user:pass@host:22)")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        client.connect(
            hostname=host,
            port=port,
            username=user,
            password=password,
            timeout=timeout_seconds,
            banner_timeout=timeout_seconds,
            auth_timeout=timeout_seconds,
            allow_agent=False,
            look_for_keys=False,
        )
        client.close()
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
        "http_status": None,  # not relevant for SSH
        "error": error,
    }
