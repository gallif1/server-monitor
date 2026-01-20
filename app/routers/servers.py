from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.db import get_conn
from app.schemas import (
    RequestOut,
    ServerCreate,
    ServerOut,
    ServerUpdate,
    ServerWithLastRequests,
    WasHealthyOut,
)
from app.healthchecks.health_logic import compute_health_from_history

router = APIRouter(prefix="/servers", tags=["servers"])


def _rollback_quietly(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        # best-effort rollback; ignore rollback errors
        pass


def _ensure_positive_server_id(server_id: int) -> None:
    if server_id <= 0:
        raise HTTPException(status_code=400, detail="server_id must be a positive integer")


def _normalize_non_empty(value: str, field_name: str) -> str:
    v = value.strip()
    if not v:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
    return v


@dataclass(frozen=True, slots=True)
class Server:
    id: int
    name: str
    url: str
    protocol: str
    health_status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row) -> "Server":
        return cls(
            id=row[0],
            name=row[1],
            url=row[2],
            protocol=row[3],
            health_status=row[4],
            created_at=row[5],
            updated_at=row[6],
        )

    def to_out_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "protocol": self.protocol,
            "health_status": self.health_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class RequestRow:
    id: int
    server_id: int
    checked_at: datetime
    is_success: bool
    latency_ms: int
    http_status: int | None
    error: str | None

    @classmethod
    def from_row(cls, row) -> "RequestRow":
        return cls(
            id=row[0],
            server_id=row[1],
            checked_at=row[2],
            is_success=row[3],
            latency_ms=row[4],
            http_status=row[5],
            error=row[6],
        )

    def to_out_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "checked_at": self.checked_at,
            "is_success": self.is_success,
            "latency_ms": self.latency_ms,
            "http_status": self.http_status,
            "error": self.error,
        }


class ServerRepository:
    """
    Centralizes DB access + mapping rows -> domain objects.
    Keeps endpoints thin and consistent (commit/rollback + HTTP errors).
    """

    def create(self, conn, *, name: str, url: str, protocol: str) -> Server:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO servers (name, url, protocol)
                    VALUES (%s, %s, %s)
                    RETURNING id, name, url, protocol, health_status, created_at, updated_at;
                    """,
                    (name, url, protocol),
                )
                row = cur.fetchone()
            conn.commit()
            if row is None:
                raise HTTPException(status_code=500, detail="DB error: insert did not return a row")
            return Server.from_row(row)
        except HTTPException:
            _rollback_quietly(conn)
            raise
        except Exception as e:
            _rollback_quietly(conn)
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    def get_by_id(self, conn, *, server_id: int) -> Server | None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, url, protocol, health_status, created_at, updated_at
                    FROM servers
                    WHERE id = %s;
                    """,
                    (server_id,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return Server.from_row(row)
        except Exception as e:
            _rollback_quietly(conn)
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    def list_all(self, conn) -> list[Server]:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, url, protocol, health_status, created_at, updated_at
                    FROM servers
                    ORDER BY id;
                    """
                )
                rows = cur.fetchall()
            return [Server.from_row(r) for r in rows]
        except Exception as e:
            _rollback_quietly(conn)
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    def delete_by_id(self, conn, *, server_id: int) -> bool:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM servers WHERE id = %s RETURNING id;", (server_id,))
                deleted = cur.fetchone()
            if deleted is None:
                return False
            conn.commit()
            return True
        except Exception as e:
            _rollback_quietly(conn)
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    def update_partial(self, conn, *, server_id: int, set_fields: dict) -> Server | None:
        # Build dynamic SET clause safely based on provided fields
        fields: list[str] = []
        values: list = []

        if "name" in set_fields:
            fields.append("name = %s")
            values.append(set_fields["name"])

        if "url" in set_fields:
            fields.append("url = %s")
            values.append(set_fields["url"])

        if "protocol" in set_fields:
            fields.append("protocol = %s")
            values.append(set_fields["protocol"])

        if not fields:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        # Always update updated_at
        fields.append("updated_at = NOW()")

        values.append(server_id)
        query = f"""
            UPDATE servers
            SET {", ".join(fields)}
            WHERE id = %s
            RETURNING id, name, url, protocol, health_status, created_at, updated_at;
        """

        try:
            with conn.cursor() as cur:
                cur.execute(query, tuple(values))
                row = cur.fetchone()

            if row is None:
                return None

            conn.commit()
            return Server.from_row(row)
        except HTTPException:
            _rollback_quietly(conn)
            raise
        except Exception as e:
            _rollback_quietly(conn)
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    def ensure_exists(self, conn, *, server_id: int) -> None:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM servers WHERE id = %s;", (server_id,))
                if cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail="Server not found")
        except HTTPException:
            raise
        except Exception as e:
            _rollback_quietly(conn)
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    def list_requests(self, conn, *, server_id: int, limit: int) -> list[RequestRow]:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, server_id, checked_at, is_success, latency_ms, http_status, error
                    FROM requests
                    WHERE server_id = %s
                    ORDER BY checked_at DESC
                    LIMIT %s;
                    """,
                    (server_id, limit),
                )
                rows = cur.fetchall()
            return [RequestRow.from_row(r) for r in rows]
        except Exception as e:
            _rollback_quietly(conn)
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    def list_recent_success_history(
        self, conn, *, server_id: int, timestamp: datetime, limit: int
    ) -> list:
        """
        Returns rows shaped like: [(True,), (False,), ...]
        so it can be fed into compute_health_from_history() unchanged.
        """
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT is_success
                    FROM requests
                    WHERE server_id = %s AND checked_at <= %s
                    ORDER BY checked_at DESC
                    LIMIT %s;
                    """,
                    (server_id, timestamp, limit),
                )
                return cur.fetchall()
        except Exception as e:
            _rollback_quietly(conn)
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")


repo = ServerRepository()


# Define POST /servers endpoint
# - response_model: shape of the returned JSON
# - status_code: HTTP 201 Created on success
@router.post("", response_model=ServerOut, status_code=status.HTTP_201_CREATED)
def create_server(payload: ServerCreate, conn=Depends(get_conn)):
    # Extra input validation (beyond pydantic schema)
    name = _normalize_non_empty(payload.name, "name")
    url = _normalize_non_empty(payload.url, "url")

    server = repo.create(conn, name=name, url=url, protocol=payload.protocol)
    return server.to_out_dict()

@router.get("/{server_id}", response_model=ServerWithLastRequests)
def get_server(server_id: int, conn=Depends(get_conn)):
    """
    Get a single server by its ID, including:
    - Basic server details
    - Current health status
    - Last 10 monitoring requests (history)
    """
    _ensure_positive_server_id(server_id)

    server = repo.get_by_id(conn, server_id=server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    last_requests = [r.to_out_dict() for r in repo.list_requests(conn, server_id=server_id, limit=10)]
    return {**server.to_out_dict(), "last_requests": last_requests}


@router.get("", response_model=list[ServerOut])
def list_servers(conn=Depends(get_conn)):
    """
    Get a list of all servers with their current health status.
    """
    servers = repo.list_all(conn)
    return [s.to_out_dict() for s in servers]

@router.delete("/{server_id}", status_code=204)
def delete_server(server_id: int, conn=Depends(get_conn)):
    """
    Delete a server by ID.
    All related health check requests will be deleted as well.
    """
    _ensure_positive_server_id(server_id)

    if not repo.delete_by_id(conn, server_id=server_id):
        raise HTTPException(status_code=404, detail="Server not found")

@router.patch("/{server_id}", response_model=ServerOut)
def update_server(server_id: int, payload: ServerUpdate, conn=Depends(get_conn)):
    """
    Partially update a server (name/url/protocol).
    Only fields provided in the request body will be updated.
    """
    _ensure_positive_server_id(server_id)

    set_fields: dict = {}
    if payload.name is not None:
        set_fields["name"] = _normalize_non_empty(payload.name, "name")

    if payload.url is not None:
        set_fields["url"] = _normalize_non_empty(payload.url, "url")

    if payload.protocol is not None:
        set_fields["protocol"] = payload.protocol

    server = repo.update_partial(conn, server_id=server_id, set_fields=set_fields)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server.to_out_dict()


@router.get("/{server_id}/requests", response_model=list[RequestOut])
def get_server_requests(
    server_id: int,
    limit: int = Query(50, ge=1, le=500),
    conn=Depends(get_conn),
):
    """
    Get monitoring request history for a specific server.
    Results are ordered from newest to oldest.
    """
    _ensure_positive_server_id(server_id)

    repo.ensure_exists(conn, server_id=server_id)
    rows = repo.list_requests(conn, server_id=server_id, limit=limit)
    return [r.to_out_dict() for r in rows]

@router.get("/{server_id}/was-healthy", response_model=WasHealthyOut)
def was_healthy(server_id: int, timestamp: datetime, conn=Depends(get_conn)):
    """
    Determine if the server was HEALTHY at a given timestamp.
    """
    _ensure_positive_server_id(server_id)

    # 1) Ensure server exists
    repo.ensure_exists(conn, server_id=server_id)

    # 2) Fetch recent history up to timestamp (enough for streak logic)
    rows = repo.list_recent_success_history(conn, server_id=server_id, timestamp=timestamp, limit=5)

    # 3) Compute health using shared logic
    status = compute_health_from_history(rows)

    return {
        "server_id": server_id,
        "timestamp": timestamp,
        "status": status,
    }