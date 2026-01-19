from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@dataclass
class _Step:
    match: str
    fetchone: Any | None = None
    fetchall: Any | None = None
    raise_on_execute: Exception | None = None


class FakeCursor:
    def __init__(self, steps: list[_Step]):
        self._steps = steps
        self._current: _Step | None = None
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((query, params))
        if not self._steps:
            raise AssertionError(f"No more scripted DB steps. Got query: {query!r}")

        step = self._steps.pop(0)
        if step.match not in query:
            raise AssertionError(
                f"Unexpected query.\nExpected to include: {step.match!r}\nGot: {query!r}"
            )
        if step.raise_on_execute is not None:
            raise step.raise_on_execute
        self._current = step

    def fetchone(self):
        if self._current is None:
            raise AssertionError("fetchone() called before execute()")
        return self._current.fetchone

    def fetchall(self):
        if self._current is None:
            raise AssertionError("fetchall() called before execute()")
        return self._current.fetchall


class FakeConn:
    def __init__(self, steps: Iterable[_Step]):
        self._steps = list(steps)
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._steps)

    def commit(self) -> None:
        self.commits += 1


def override_get_conn(fake_conn: FakeConn) -> Callable[[], Any]:
    def _dep():
        yield fake_conn

    return _dep


@pytest.fixture
def make_app():
    def _make_app(router, dep_overrides: dict[Callable[..., Any], Callable[..., Any]] | None = None):
        app = FastAPI()
        app.include_router(router)
        if dep_overrides:
            app.dependency_overrides.update(dep_overrides)
        return app

    return _make_app


@pytest.fixture
def make_client():
    def _make_client(app: FastAPI) -> TestClient:
        return TestClient(app)

    return _make_client
