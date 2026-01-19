import time
from dotenv import load_dotenv
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.healthchecks.http_check import check_http
from app.healthchecks.ftp_check import check_ftp
from app.healthchecks.ssh_check import check_ssh
from app.healthchecks.health_logic import compute_health_from_history
from app.emailer import send_unhealthy_alert

# Read from env
load_dotenv()

from app.db import init_db, close_db, locked_conn

CHECKERS = {
    "HTTP": check_http,
    "HTTPS": check_http,
    "FTP": check_ftp,
    "SSH": check_ssh,
}

def calc_workers(num_servers: int) -> int:
    cpu = os.cpu_count() or 4
    base = min(50, max(10, cpu * 5))
    return min(base, num_servers)  # לא לפתוח יותר threads ממספר המשימות



def run_network_check(protocol: str, url: str) -> dict:
    checker = CHECKERS.get(protocol)
    if not checker:
        return {"is_success": False, "latency_ms": 0, "error": f"unknown protocol {protocol}"}
    return checker(url)


def save_request(conn, server_id: int, result: dict) -> None:
    #Insert a single check result into requests table.
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO requests (server_id, is_success, latency_ms, http_status, error)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (
                server_id,
                result["is_success"],
                result["latency_ms"],
                result.get("http_status"),  # None for FTP/SSH
                result.get("error"),
            ),
        )
    conn.commit()


def fetch_recent_history(conn, server_id: int, limit: int = 10):
    """Fetch last N is_success results for a server (newest -> oldest)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT is_success
            FROM requests
            WHERE server_id = %s
            ORDER BY checked_at DESC
            LIMIT %s;
            """,
            (server_id, limit),
        )
        return cur.fetchall()


def get_current_health_status(conn, server_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT health_status FROM servers WHERE id = %s;", (server_id,))
        row = cur.fetchone()
    return row[0] if row else None


def update_health_status_if_changed(conn, server_id: int, new_status, server_name: str) -> None:
    old_status = get_current_health_status(conn, server_id)

    # If server row not found, just skip silently (or you can print a warning)
    if old_status is None:
        print(f"[worker] warning: server id={server_id} not found when updating health")
        return

    if new_status != old_status:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE servers
                SET health_status = %s, updated_at = NOW()
                WHERE id = %s;
                """,
                (new_status, server_id),
            )
        conn.commit()
        if new_status == "UNHEALTHY":
            send_unhealthy_alert(server_name)
        print(f"[worker] health_status changed {old_status} -> {new_status}")


def run_once() -> None:
    """
    Single worker iteration:
    1) Fetch servers ONCE from DB
    2) Run checks in parallel (threads) WITHOUT touching DB
    3) After checks finish, write results to DB (single thread)
    """
    # (1) Fetch ONCE
    with locked_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, url, protocol, health_status FROM servers ORDER BY id;")
            rows = cur.fetchall()

    print(f"[worker] found {len(rows)} servers")
    if not rows:
        return

    max_workers = calc_workers(len(rows))
    print(f"[worker] using max_workers={max_workers}")

    # (2) Run checks in parallel - NO DB INSIDE THREADS
    results = []  # list of (server_id, name, protocol, result_dict)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {}
        for server_id, name, url, protocol, health_status in rows:
            print(f"[worker] scheduling id={server_id} name={name} protocol={protocol}")
            fut = pool.submit(run_network_check, protocol, url)
            future_map[fut] = (server_id, name, protocol)

        for fut in as_completed(future_map):
            server_id, name, protocol = future_map[fut]
            try:
                result = fut.result()
            except Exception as e:
                result = {"is_success": False, "latency_ms": 0, "error": str(e)}
            results.append((server_id, name, protocol, result))

    # (3) Write results to DB (single thread)
    for server_id, name, protocol, result in results:
        msg = f"[worker] {protocol.lower()}_result success={result['is_success']} latency_ms={result['latency_ms']}"
        if protocol in ("HTTP", "HTTPS"):
            msg += f" status={result.get('http_status')}"
        if result.get("error"):
            msg += f" error={result.get('error')}"
        print(msg)

        with locked_conn() as conn:
            save_request(conn, server_id, result)

        with locked_conn() as conn:
            history = fetch_recent_history(conn, server_id, limit=5)

        new_status = compute_health_from_history(history)

        with locked_conn() as conn:
            update_health_status_if_changed(conn, server_id, new_status, name)


def main() -> None:
    """
    Worker process entrypoint.
    Initializes the single DB connection and runs every 60 seconds.
    """
    init_db()
    try:
        while True:
            start = time.time()
            try:
                run_once()
            except Exception as e:
                # Never crash the worker on a single iteration
                print(f"[worker] iteration error: {e}")

            elapsed = time.time() - start
            sleep_for = max(0, 60 - elapsed)
            print(f"[worker] sleeping {sleep_for:.1f}s\n")
            time.sleep(sleep_for)
    finally:
        close_db()


if __name__ == "__main__":
    main()
