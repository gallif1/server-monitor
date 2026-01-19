import paramiko

from app.healthchecks.ssh_check import check_ssh


def test_check_ssh_requires_host():
    res = check_ssh("ssh://user:pass@", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert "missing host" in (res["error"] or "").lower()


def test_check_ssh_requires_credentials():
    res = check_ssh("ssh://example.com:22", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert "username and password" in (res["error"] or "").lower()


def test_check_ssh_success_connects_and_closes(mocker):
    client = mocker.Mock()
    mocker.patch("app.healthchecks.ssh_check.paramiko.SSHClient", return_value=client)
    mocker.patch("app.healthchecks.ssh_check.paramiko.AutoAddPolicy", return_value=mocker.Mock())

    res = check_ssh("ssh://u:p@example.com:2222", timeout_seconds=1.0)

    assert res["is_success"] is True
    assert res["http_status"] is None
    assert res["error"] is None
    client.set_missing_host_key_policy.assert_called_once()
    client.connect.assert_called_once()
    kwargs = client.connect.call_args.kwargs
    assert kwargs["hostname"] == "example.com"
    assert kwargs["port"] == 2222
    assert kwargs["username"] == "u"
    assert kwargs["password"] == "p"
    assert kwargs["timeout"] == 1.0
    client.close.assert_called_once()


def test_check_ssh_exception_sets_error(mocker):
    client = mocker.Mock()
    client.connect.side_effect = paramiko.SSHException("nope")
    mocker.patch("app.healthchecks.ssh_check.paramiko.SSHClient", return_value=client)
    mocker.patch("app.healthchecks.ssh_check.paramiko.AutoAddPolicy", return_value=mocker.Mock())

    res = check_ssh("ssh://u:p@example.com:22", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert "nope" in (res["error"] or "")


def test_check_ssh_latency_exceeded_forces_failure(mocker):
    client = mocker.Mock()
    mocker.patch("app.healthchecks.ssh_check.paramiko.SSHClient", return_value=client)
    mocker.patch("app.healthchecks.ssh_check.paramiko.AutoAddPolicy", return_value=mocker.Mock())

    times = iter([0.0, 2.0])
    mocker.patch("app.healthchecks.ssh_check.time.perf_counter", side_effect=lambda: next(times))

    res = check_ssh("ssh://u:p@example.com:22", timeout_seconds=1.0)
    assert res["is_success"] is False
    assert "Latency exceeded" in (res["error"] or "")
