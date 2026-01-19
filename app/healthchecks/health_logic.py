def compute_health_from_history(rows: list[tuple[bool]]) -> str:
    """
    Compute server health based on recent request history.

    Rules:
    - HEALTHY if 5 consecutive successes
    - UNHEALTHY if 3 consecutive failures
    - Otherwise UNKNOWN

    rows: list of tuples [(is_success,), ...] ordered from newest to oldest
    """
    success_streak = 0
    fail_streak = 0

    for (is_success,) in rows:
        if is_success:
            success_streak += 1
            fail_streak = 0
        else:
            fail_streak += 1
            success_streak = 0

        if success_streak >= 5:
            return "HEALTHY"
        if fail_streak >= 3:
            return "UNHEALTHY"

    return "UNKNOWN"
