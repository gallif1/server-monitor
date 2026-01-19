from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db import get_conn
from app.routers.servers import router
from tests.conftest import FakeConn, _Step, override_get_conn


def test_create_server_success(make_app, make_client):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_conn = FakeConn(
        [
            _Step(
                "INSERT INTO servers",
                fetchone=(1, "srv", "https://x", "HTTP", "UNKNOWN", now, now),
            )
        ]
    )
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.post("/servers", json={"name": "srv", "url": "https://x", "protocol": "HTTP"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 1
    assert body["health_status"] == "UNKNOWN"
    assert fake_conn.commits == 1


def test_create_server_db_error_returns_500(make_app, make_client):
    fake_conn = FakeConn([_Step("INSERT INTO servers", raise_on_execute=RuntimeError("db down"))])
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.post("/servers", json={"name": "srv", "url": "https://x", "protocol": "HTTP"})
    assert r.status_code == 500
    assert "DB error" in r.json()["detail"]


def test_list_servers(make_app, make_client):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_conn = FakeConn(
        [
            _Step(
                "SELECT id, name, url, protocol, health_status",
                fetchall=[
                    (1, "a", "https://a", "HTTP", "UNKNOWN", now, now),
                    (2, "b", "ftp://b", "FTP", "HEALTHY", now, now),
                ],
            )
        ]
    )
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.get("/servers")
    assert r.status_code == 200
    body = r.json()
    assert [s["id"] for s in body] == [1, 2]


def test_get_server_not_found(make_app, make_client):
    fake_conn = FakeConn([_Step("FROM servers", fetchone=None)])
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.get("/servers/123")
    assert r.status_code == 404


def test_get_server_includes_last_requests(make_app, make_client):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_conn = FakeConn(
        [
            _Step(
                "FROM servers",
                fetchone=(1, "srv", "https://x", "HTTP", "UNKNOWN", now, now),
            ),
            _Step(
                "FROM requests",
                fetchall=[
                    (10, 1, now, True, 12, 200, None),
                    (11, 1, now, False, 50, 500, "err"),
                ],
            ),
        ]
    )
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.get("/servers/1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert len(body["last_requests"]) == 2
    assert body["last_requests"][0]["id"] == 10


def test_delete_server_success(make_app, make_client):
    fake_conn = FakeConn([_Step("DELETE FROM servers", fetchone=(1,))])
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.delete("/servers/1")
    assert r.status_code == 204
    assert fake_conn.commits == 1


def test_delete_server_not_found(make_app, make_client):
    fake_conn = FakeConn([_Step("DELETE FROM servers", fetchone=None)])
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.delete("/servers/999")
    assert r.status_code == 404


def test_update_server_no_fields_returns_400(make_app, make_client):
    fake_conn = FakeConn([])
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.patch("/servers/1", json={})
    assert r.status_code == 400


def test_update_server_success(make_app, make_client):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_conn = FakeConn(
        [
            _Step(
                "UPDATE servers",
                fetchone=(1, "new", "https://x", "HTTP", "UNKNOWN", now, now),
            )
        ]
    )
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.patch("/servers/1", json={"name": "new"})
    assert r.status_code == 200
    assert r.json()["name"] == "new"
    assert fake_conn.commits == 1


def test_get_server_requests_requires_server_exists(make_app, make_client):
    fake_conn = FakeConn([_Step("SELECT 1 FROM servers", fetchone=None)])
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.get("/servers/1/requests")
    assert r.status_code == 404


def test_get_server_requests_returns_rows(make_app, make_client):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_conn = FakeConn(
        [
            _Step("SELECT 1 FROM servers", fetchone=(1,)),
            _Step(
                "FROM requests",
                fetchall=[
                    (10, 1, now, True, 12, 200, None),
                ],
            ),
        ]
    )
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.get("/servers/1/requests?limit=50")
    assert r.status_code == 200
    assert r.json()[0]["id"] == 10


def test_was_healthy_happy_path(make_app, make_client):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_conn = FakeConn(
        [
            _Step("SELECT 1 FROM servers", fetchone=(1,)),
            _Step(
                "FROM requests",
                fetchall=[(True,), (True,), (True,), (True,), (True,)],
            ),
        ]
    )
    app = make_app(router, {get_conn: override_get_conn(fake_conn)})
    client = make_client(app)

    r = client.get("/servers/1/was-healthy", params={"timestamp": now.isoformat()})
    assert r.status_code == 200
    assert r.json()["status"] == "HEALTHY"

