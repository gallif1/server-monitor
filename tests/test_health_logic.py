from app.healthchecks.health_logic import compute_health_from_history


def test_compute_health_healthy_after_5_successes():
    rows = [(True,), (True,), (True,), (True,), (True,)]
    assert compute_health_from_history(rows) == "HEALTHY"


def test_compute_health_unhealthy_after_3_failures():
    rows = [(False,), (False,), (False,)]
    assert compute_health_from_history(rows) == "UNHEALTHY"


def test_compute_health_unknown_when_not_enough_streak():
    rows = [(True,), (True,), (False,), (True,), (True,)]
    assert compute_health_from_history(rows) == "UNKNOWN"


def test_compute_health_resets_streak_on_flip():
    rows = [(True,), (True,), (True,), (False,), (False,), (False,)]
    # newest -> oldest, so first 3 are successes then 3 failures; should detect UNHEALTHY at the end
    assert compute_health_from_history(rows) == "UNHEALTHY"
