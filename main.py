from fastapi import FastAPI, Depends
import os
from dotenv import load_dotenv
from app.db import init_db, close_db, get_conn
from app.routers.servers import router as servers_router



load_dotenv()

app = FastAPI()

app.include_router(servers_router)


@app.on_event("startup")
def on_startup():
    init_db()

@app.on_event("shutdown")
def on_shutdown():
    close_db()

# Health check endpoint to verify the API and database are working
@app.get("/health")
def health(conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT 1;")
        row = cur.fetchone()
    return {"status": "ok", "db": "ok", "select_1": row[0]}

