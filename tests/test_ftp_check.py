from app.healthchecks.ftp_check import check_ftp


def test_check_ftp_requires_host():
    res = check_ftp("ftp://", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert "missing host" in (res["error"] or "").lower()


def test_check_ftp_success_connects_logs_in_and_quits(mocker):
    ftp = mocker.Mock()
    mocker.patch("app.healthchecks.ftp_check.FTP", return_value=ftp)

    res = check_ftp("ftp://user:pass@example.com:2121", timeout_seconds=1.0)

    assert res["is_success"] is True
    assert res["http_status"] is None
    assert res["error"] is None
    ftp.connect.assert_called_once_with(host="example.com", port=2121, timeout=1.0)
    ftp.login.assert_called_once_with(user="user", passwd="pass")
    ftp.quit.assert_called_once()


def test_check_ftp_defaults_to_anonymous(mocker):
    ftp = mocker.Mock()
    mocker.patch("app.healthchecks.ftp_check.FTP", return_value=ftp)

    res = check_ftp("ftp://example.com", timeout_seconds=1.0)

    assert res["is_success"] is True
    ftp.login.assert_called_once_with(user="anonymous", passwd="anonymous@")


def test_check_ftp_exception_sets_error(mocker):
    ftp = mocker.Mock()
    ftp.connect.side_effect = OSError("nope")
    mocker.patch("app.healthchecks.ftp_check.FTP", return_value=ftp)

    res = check_ftp("ftp://example.com:21", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert "nope" in (res["error"] or "")


def test_check_ftp_latency_exceeded_forces_failure(mocker):
    ftp = mocker.Mock()
    mocker.patch("app.healthchecks.ftp_check.FTP", return_value=ftp)

    times = iter([0.0, 2.0])
    mocker.patch("app.healthchecks.ftp_check.time.perf_counter", side_effect=lambda: next(times))

    res = check_ftp("ftp://example.com:21", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert "Latency exceeded" in (res["error"] or "")
