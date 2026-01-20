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
from datetime import datetime
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


# Define POST /servers endpoint
# - response_model: shape of the returned JSON
# - status_code: HTTP 201 Created on success
@router.post("", response_model=ServerOut, status_code=status.HTTP_201_CREATED)
def create_server(payload: ServerCreate, conn=Depends(get_conn)):
    # Extra input validation (beyond pydantic schema)
    name = _normalize_non_empty(payload.name, "name")
    url = _normalize_non_empty(payload.url, "url")

    # Insert a new server record into the database
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO servers (name, url, protocol)
                VALUES (%s, %s, %s)
                RETURNING id, name, url, protocol, health_status, created_at, updated_at;
                """,
                (name, url, payload.protocol),
            )
            row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(status_code=500, detail="DB error: insert did not return a row")
    except HTTPException:
        _rollback_quietly(conn)
        raise
    except Exception as e:
        _rollback_quietly(conn)
        # if something DB-related fails
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    # Map the database row to the response schema
    return {
        "id": row[0],
        "name": row[1],
        "url": row[2],
        "protocol": row[3],
        "health_status": row[4],
        "created_at": row[5],
        "updated_at": row[6],
    }

@router.get("/{server_id}", response_model=ServerWithLastRequests)
def get_server(server_id: int, conn=Depends(get_conn)):
    """
    Get a single server by its ID, including:
    - Basic server details
    - Current health status
    - Last 10 monitoring requests (history)
    """
    _ensure_positive_server_id(server_id)

    # 1) Fetch server
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
            s = cur.fetchone()
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if s is None:
        raise HTTPException(status_code=404, detail="Server not found")

    # 2) Fetch last 10 requests
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, server_id, checked_at, is_success, latency_ms, http_status, error
                FROM requests
                WHERE server_id = %s
                ORDER BY checked_at DESC
                LIMIT 10;
                """,
                (server_id,),
            )
            rows = cur.fetchall()
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    last_requests = [
        {
            "id": r[0],
            "server_id": r[1],
            "checked_at": r[2],
            "is_success": r[3],
            "latency_ms": r[4],
            "http_status": r[5],
            "error": r[6],
        }
        for r in rows
    ]

    return {
        "id": s[0],
        "name": s[1],
        "url": s[2],
        "protocol": s[3],
        "health_status": s[4],
        "created_at": s[5],
        "updated_at": s[6],
        "last_requests": last_requests,
    }


@router.get("", response_model=list[ServerOut])
def list_servers(conn=Depends(get_conn)):
    """
    Get a list of all servers with their current health status.
    """
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
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    return [
        {
            "id": row[0],
            "name": row[1],
            "url": row[2],
            "protocol": row[3],
            "health_status": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }
        for row in rows
    ]

@router.delete("/{server_id}", status_code=204)
def delete_server(server_id: int, conn=Depends(get_conn)):
    """
    Delete a server by ID.
    All related health check requests will be deleted as well.
    """
    _ensure_positive_server_id(server_id)

    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM servers WHERE id = %s RETURNING id;",
                (server_id,),
            )
            deleted = cur.fetchone()
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if deleted is None:
        # No server was deleted -> ID does not exist
        raise HTTPException(status_code=404, detail="Server not found")

    try:
        conn.commit()
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

@router.patch("/{server_id}", response_model=ServerOut)
def update_server(server_id: int, payload: ServerUpdate, conn=Depends(get_conn)):
    """
    Partially update a server (name/url/protocol).
    Only fields provided in the request body will be updated.
    """
    _ensure_positive_server_id(server_id)

    # Build dynamic SET clause safely based on provided fields
    fields = []
    values = []

    if payload.name is not None:
        fields.append("name = %s")
        values.append(_normalize_non_empty(payload.name, "name"))

    if payload.url is not None:
        fields.append("url = %s")
        values.append(_normalize_non_empty(payload.url, "url"))

    if payload.protocol is not None:
        fields.append("protocol = %s")
        values.append(payload.protocol)

    if not fields:
        # Nothing to update
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
            raise HTTPException(status_code=404, detail="Server not found")

        conn.commit()

        return {
            "id": row[0],
            "name": row[1],
            "url": row[2],
            "protocol": row[3],
            "health_status": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }
    except HTTPException:
        _rollback_quietly(conn)
        raise
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")


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

    # Check server exists
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM servers WHERE id = %s;", (server_id,))
            exists = cur.fetchone()
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    if exists is None:
        raise HTTPException(status_code=404, detail="Server not found")

    # Fetch request history
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
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    return [
        {
            "id": r[0],
            "server_id": r[1],
            "checked_at": r[2],
            "is_success": r[3],
            "latency_ms": r[4],
            "http_status": r[5],
            "error": r[6],
        }
        for r in rows
    ]

@router.get("/{server_id}/was-healthy", response_model=WasHealthyOut)
def was_healthy(server_id: int, timestamp: datetime, conn=Depends(get_conn)):
    """
    Determine if the server was HEALTHY at a given timestamp.
    """
    _ensure_positive_server_id(server_id)

    # 1) Ensure server exists
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

    # 2) Fetch recent history up to timestamp (enough for streak logic)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT is_success
                FROM requests
                WHERE server_id = %s AND checked_at <= %s
                ORDER BY checked_at DESC
                LIMIT 5;
                """,
                (server_id, timestamp),
            )
            rows = cur.fetchall()
    except Exception as e:
        _rollback_quietly(conn)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    # 3) Compute health using shared logic
    status = compute_health_from_history(rows)

    return {
        "server_id": server_id,
        "timestamp": timestamp,
        "status": status,
    }