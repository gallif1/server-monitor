
# Server Monitor (API + Worker)

Server Monitor is a backend service that monitors servers and services (HTTP / HTTPS / FTP / SSH), stores health-check history in PostgreSQL, and exposes a REST API for managing servers and inspecting their health.

The system is composed of two parts:

* **API (FastAPI)**  
  Exposes REST endpoints to create, update, delete, and query monitored servers and their check history.

* **Worker**  
  A background process that runs every 60 seconds, performs health checks on all registered servers, stores the results in the database, updates each server’s `health_status`, and can send email alerts when a server becomes **UNHEALTHY**.

---

## Requirements

* **Python 3.11** (recommended)
* **PostgreSQL**
* `pip`

---

## Installation

Clone the repository (or download it), create a virtual environment, and install dependencies:

```bash
git clone <your-repo-url>
cd server-monitor

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Configuration (.env)

Create a `.env` file in the project root (this file is ignored by git).

### Database configuration (required)

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=server_monitor
DB_USER=postgres
DB_PASSWORD=your_password_here
```

### Email configuration (optional)

Email alerts are sent **only** when a server’s status changes to **UNHEALTHY**.

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
```

The recipient email address (`ALERT_EMAIL_TO`) is configured in `app/config.py` and can be changed there if needed.

## Database setup (PostgreSQL)

You can initialize the database in **one of the following ways**.

### Option A — Restore from database dump (recommended)

This is the fastest way to get a working database with the full schema
(and example data, if present).

```bash
psql "postgresql://USER:PASSWORD@HOST:PORT/DB_NAME" -f db_dump.sql


This will create:

* ENUM types for protocol and health status
* `servers` table (monitored targets and current `health_status`)
* `requests` table (history of checks per server)
* Required indexes

---

## Running the API

Start the FastAPI server (default port: 8000):

```bash
python -m uvicorn main:app --reload
```

Verify the service is running:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "db": "ok",
  "select_1": 1
}
```

---

## Running the worker

Run the worker in a **separate terminal**, from the project root:

```bash
python -m app.worker_runner
```

The worker:

* Fetches all servers from the database
* Performs health checks every **60 seconds**
* Stores results in the `requests` table
* Updates `health_status` on each server
* Sends email alerts on transition to **UNHEALTHY**

---

## Health status rules

A server’s `health_status` is derived from recent check history (newest → oldest):

* **HEALTHY**: 5 consecutive successful checks
* **UNHEALTHY**: 3 consecutive failed checks
* **UNKNOWN**: insufficient data or mixed results

---

## API base information

* **Base URL**: `http://localhost:8000`
* **Request format**: JSON (`Content-Type: application/json`)
* **Error responses**:

```json
{
  "detail": "error message"
}
```

---

## Supported URL formats

* **HTTP**
  `http://example.com`
  `http://example.com:8080/path`

* **HTTPS**
  `https://example.com`

* **FTP**
  `ftp://host:21`
  Optional authentication:
  `ftp://user:password@host:21`

* **SSH**
  `ssh://user:password@host:22`  
  *(Username and password are required for SSH checks.)*

---

## API Endpoints

### Create a server

**POST** `/servers`

Request body:

* `name` (string, required, not empty)
* `url` (string, required, not empty)
* `protocol` (`HTTP | HTTPS | FTP | SSH`)

Example:

```bash
curl -X POST "http://localhost:8000/servers" \
  -H "Content-Type: application/json" \
  -d '{"name":"My API","url":"https://example.com/health","protocol":"HTTPS"}'
```

---

### List all servers

**GET** `/servers`

Example:

```bash
curl "http://localhost:8000/servers"
```

---

### Get a single server

**GET** `/servers/{server_id}`

Includes:

* Server details
* Last 10 health check records (`last_requests`)

Example:

```bash
curl "http://localhost:8000/servers/1"
```

---

### Update a server (partial update)

**PATCH** `/servers/{server_id}`

Updatable fields:

* `name`
* `url`
* `protocol`

Example:

```bash
curl -X PATCH "http://localhost:8000/servers/1" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/status"}'
```

---

### Delete a server

**DELETE** `/servers/{server_id}`

Deletes the server and all related check history.

Response: `204 No Content`

Example:

```bash
curl -X DELETE "http://localhost:8000/servers/1"
```

---

### Get request history

**GET** `/servers/{server_id}/requests?limit=50`

Query parameters:

* `limit` (optional, default: 50, min: 1, max: 500)

Example:

```bash
curl "http://localhost:8000/servers/1/requests?limit=100"
```

---

### Timestamp format (ISO 8601)

`timestamp` must be a valid ISO 8601 datetime.

Examples:
- `2026-01-20T11:05:00Z` (UTC)
- `2026-01-20T13:05:00%2B02:00` (timezone offset; `+` must be URL-encoded as `%2B`)

Returns the server health status at the given time.

---

## Notes

* The worker and the API are designed to run as separate processes.
* Database access is serialized (single shared connection with a lock) to avoid concurrent use of the same connection.
* The project uses raw SQL (no ORM) by design.

