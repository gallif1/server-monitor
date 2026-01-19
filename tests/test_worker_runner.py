from __future__ import annotations

from contextlib import contextmanager

import pytest

from tests.conftest import FakeConn, _Step


def test_calc_workers_bounds():
    from app.worker_runner import calc_workers

    # should never exceed num_servers
    assert calc_workers(1) == 1
    assert calc_workers(5) == 5
    # should be at least 10 or cpu*5 but capped by num_servers
    assert calc_workers(1000) <= 50


def test_run_network_check_unknown_protocol():
    from app.worker_runner import run_network_check

    res = run_network_check("TELNET", "telnet://example.com:23")
    assert res["is_success"] is False
    assert "unknown protocol" in (res["error"] or "")


def test_update_health_status_if_changed_sends_email_on_unhealthy(mocker):
    from app.worker_runner import update_health_status_if_changed

    fake_conn = FakeConn(
        [
            _Step("SELECT health_status FROM servers", fetchone=("UNKNOWN",)),
            _Step("UPDATE servers"),
        ]
    )
    send = mocker.patch("app.worker_runner.send_unhealthy_alert")

    update_health_status_if_changed(fake_conn, server_id=1, new_status="UNHEALTHY", server_name="srv1")

    assert fake_conn.commits == 1
    send.assert_called_once_with("srv1")


def test_update_health_status_if_changed_no_change_no_update(mocker):
    from app.worker_runner import update_health_status_if_changed

    fake_conn = FakeConn([_Step("SELECT health_status FROM servers", fetchone=("HEALTHY",))])
    send = mocker.patch("app.worker_runner.send_unhealthy_alert")

    update_health_status_if_changed(fake_conn, server_id=1, new_status="HEALTHY", server_name="srv1")

    assert fake_conn.commits == 0
    send.assert_not_called()


def test_run_once_writes_requests_and_updates_health(mocker):
    """
    Full-ish run_once test with:
    - deterministic single worker thread
    - no real network
    - DB interactions validated via scripted steps
    """
    import app.worker_runner as wr

    mocker.patch("app.worker_runner.calc_workers", return_value=1)
    mocker.patch("app.worker_runner.run_network_check", side_effect=[
        {"is_success": True, "latency_ms": 10, "http_status": 200, "error": None},
        {"is_success": False, "latency_ms": 20, "http_status": None, "error": "boom"},
    ])

    send = mocker.patch("app.worker_runner.send_unhealthy_alert")

    fake_conn = FakeConn(
        [
            _Step(
                "SELECT id, name, url, protocol, health_status FROM servers",
                fetchall=[
                    (1, "srv1", "https://example.com", "HTTP", "UNKNOWN"),
                    (2, "srv2", "ssh://u:p@example.com:22", "SSH", "UNKNOWN"),
                ],
            ),
            # srv1: save_request + history + status update
            _Step("INSERT INTO requests"),
            _Step("SELECT is_success", fetchall=[(True,), (True,), (True,), (True,), (True,)]),
            _Step("SELECT health_status FROM servers", fetchone=("UNKNOWN",)),
            _Step("UPDATE servers"),
            # srv2
            _Step("INSERT INTO requests"),
            _Step("SELECT is_success", fetchall=[(False,), (False,), (False,)]),
            _Step("SELECT health_status FROM servers", fetchone=("UNKNOWN",)),
            _Step("UPDATE servers"),
        ]
    )

    @contextmanager
    def _locked_conn():
        yield fake_conn

    mocker.patch.object(wr, "locked_conn", _locked_conn)

    wr.run_once()

    # 2 servers => save_request commit + update commit each => 4
    assert fake_conn.commits == 4
    send.assert_called_once_with("srv2")

