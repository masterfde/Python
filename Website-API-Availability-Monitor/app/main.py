"""RK_Python_1 - RK API Pulse: a small FastAPI app that watches public APIs."""
import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.checker import diagnose, monitoring_loop, run_checks, validate_url
from app.database import connect, init_db, seconds_between


class EndpointIn(BaseModel):
    """The JSON the dashboard sends when adding an endpoint."""
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=8, max_length=2048)
    slow_ms: int = Field(default=1500, ge=100, le=30000)


@asynccontextmanager
async def lifespan(app):
    """Start the background checker when the server starts, stop it on exit."""
    init_db()
    task = asyncio.create_task(monitoring_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="RK API Pulse", version="2.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "static"), name="static")


def clamp_limit(limit):
    """Keep ?limit= between 1 and 500."""
    return min(max(limit, 1), 500)


@app.get("/")
def home():
    return FileResponse(config.BASE_DIR / "static" / "index.html")


@app.get("/api/summary")
def summary():
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()

    with connect() as db:
        latest = db.execute("""
            SELECT e.*, c.status, c.http_code, c.response_ms, c.checked_at, c.error
            FROM endpoints e
            LEFT JOIN checks c ON c.id = (
                SELECT MAX(id) FROM checks WHERE endpoint_id = e.id)
            ORDER BY e.id""").fetchall()

        counts = {row["endpoint_id"]: row for row in db.execute("""
            SELECT endpoint_id,
                   SUM(status IN ('UP', 'SLOW')) AS available,
                   SUM(status IN ('UP', 'SLOW', 'DOWN')) AS conclusive
            FROM checks GROUP BY endpoint_id""")}

        open_incidents = {row["endpoint_id"]: row for row in db.execute("""
            SELECT endpoint_id, started_at, incident_type FROM incidents
            WHERE ended_at IS NULL ORDER BY id""")}  # later rows win

        last_success = {row["endpoint_id"]: row["last_ok"] for row in db.execute("""
            SELECT endpoint_id, MAX(checked_at) AS last_ok FROM checks
            WHERE status IN ('UP', 'SLOW') GROUP BY endpoint_id""")}

    endpoints = []
    for row in latest:
        item = dict(row)
        count = counts.get(item["id"])
        conclusive = (count["conclusive"] or 0) if count else 0
        available = (count["available"] or 0) if count else 0
        item["uptime_pct"] = round(100 * available / conclusive, 2) if conclusive else None

        incident = open_incidents.get(item["id"])
        item["incident_type"] = incident["incident_type"] if incident else None
        item["down_since"] = None
        item["access_issue_since"] = None
        item["downtime_seconds"] = 0
        if incident and incident["incident_type"] == "DOWN":
            item["down_since"] = incident["started_at"]
            item["downtime_seconds"] = seconds_between(incident["started_at"], now_text)
        elif incident:
            item["access_issue_since"] = incident["started_at"]

        item["last_success_at"] = last_success.get(item["id"])
        item["diagnostic_code"], item["diagnostic_detail"] = diagnose(
            item["status"], item["http_code"], item["error"])
        endpoints.append(item)

    times = [e["response_ms"] for e in endpoints if e["response_ms"] is not None]
    statuses = [e["status"] for e in endpoints]
    return {
        "endpoints": endpoints,
        "total": len(endpoints),
        "up": statuses.count("UP"),
        "slow": statuses.count("SLOW"),
        "down": statuses.count("DOWN"),
        "blocked": statuses.count("BLOCKED"),
        "unknown": sum(s not in ("UP", "SLOW", "DOWN", "BLOCKED") for s in statuses),
        "avg_ms": round(sum(times) / len(times), 1) if times else None,
        "checked_at": now_text,
    }


@app.get("/api/incidents")
def incidents(limit: int = 100):
    now_text = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        rows = [dict(r) for r in db.execute("""
            SELECT i.*, e.name, e.url FROM incidents i
            JOIN endpoints e ON e.id = i.endpoint_id
            ORDER BY i.id DESC LIMIT ?""", (clamp_limit(limit),))]

    for row in rows:
        if row["ended_at"] is None:
            row["duration_seconds"] = seconds_between(row["started_at"], now_text)
            row["state"] = "ONGOING"
        else:
            row["state"] = "RECOVERED"
    return rows


@app.get("/api/history")
def history(limit: int = 100):
    with connect() as db:
        return [dict(r) for r in db.execute("""
            SELECT c.*, e.name FROM checks c
            JOIN endpoints e ON e.id = c.endpoint_id
            ORDER BY c.id DESC LIMIT ?""", (clamp_limit(limit),))]


@app.post("/api/endpoints", status_code=201)
def add_endpoint(item: EndpointIn):
    try:
        validate_url(item.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    name = item.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name cannot be empty")

    try:
        with connect() as db:
            cursor = db.execute(
                "INSERT INTO endpoints (name, url, slow_ms) VALUES (?, ?, ?)",
                (name, item.url, item.slow_ms))
            new_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="URL already monitored") from exc

    return {"id": new_id, "name": name, "url": item.url, "slow_ms": item.slow_ms}


@app.post("/api/check-now")
async def check_now():
    await run_checks()
    return {"message": "Checks completed"}


@app.delete("/api/endpoints/{endpoint_id}")
def delete_endpoint(endpoint_id: int):
    """Delete an endpoint together with its checks and incidents."""
    with connect() as db:
        found = db.execute("SELECT id FROM endpoints WHERE id = ?", (endpoint_id,)).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="Endpoint not found")
        db.execute("DELETE FROM incidents WHERE endpoint_id = ?", (endpoint_id,))
        db.execute("DELETE FROM checks WHERE endpoint_id = ?", (endpoint_id,))
        db.execute("DELETE FROM endpoints WHERE id = ?", (endpoint_id,))
    return {"message": "Endpoint and monitoring history deleted", "id": endpoint_id}
