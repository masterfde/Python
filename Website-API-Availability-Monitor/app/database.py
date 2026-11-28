"""All the SQLite code: creating tables, saving checks, tracking incidents."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from app import config


@contextmanager
def connect():
    """Open the database, commit if all went well, roll back on error, always close.

    (A plain `with sqlite3.connect(...)` commits but never closes the
    connection, so I wrap it to avoid leaking connections.)
    """
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Create the tables if they are missing and add sample endpoints once."""
    with connect() as db:
        # WAL mode lets the dashboard read while a check is being saved
        db.execute("PRAGMA journal_mode = WAL")

        db.execute("""
            CREATE TABLE IF NOT EXISTS endpoints (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                slow_ms INTEGER NOT NULL DEFAULT 1500
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY,
                endpoint_id INTEGER NOT NULL,
                checked_at TEXT NOT NULL,
                status TEXT NOT NULL,
                http_code INTEGER,
                response_ms REAL,
                error TEXT,
                FOREIGN KEY (endpoint_id) REFERENCES endpoints(id)
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY,
                endpoint_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_seconds REAL,
                reason TEXT,
                incident_type TEXT NOT NULL DEFAULT 'DOWN',
                FOREIGN KEY (endpoint_id) REFERENCES endpoints(id)
            )""")

        # Databases made by older versions may not have incident_type yet
        columns = [row["name"] for row in db.execute("PRAGMA table_info(incidents)")]
        if "incident_type" not in columns:
            db.execute("ALTER TABLE incidents ADD COLUMN incident_type TEXT NOT NULL DEFAULT 'DOWN'")

        db.execute("CREATE INDEX IF NOT EXISTS idx_checks_endpoint ON checks(endpoint_id, id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_incidents_endpoint ON incidents(endpoint_id, ended_at)")

        fix_old_incidents(db)

        # First run only: add the sample endpoints
        if db.execute("SELECT 1 FROM endpoints LIMIT 1").fetchone() is None:
            db.executemany(
                "INSERT INTO endpoints (name, url, slow_ms) VALUES (?, ?, ?)",
                config.SAMPLE_ENDPOINTS,
            )


def fix_old_incidents(db):
    """Clean up incidents that older versions of this project got wrong.

    Early versions counted TLS / DNS problems as real outages. Any incident
    that never had a confirmed DOWN check is relabelled ACCESS_ISSUE.
    """
    db.execute("""
        UPDATE incidents SET incident_type = 'ACCESS_ISSUE'
        WHERE incident_type = 'DOWN' AND NOT EXISTS (
            SELECT 1 FROM checks c
            WHERE c.endpoint_id = incidents.endpoint_id
              AND c.checked_at >= incidents.started_at
              AND (incidents.ended_at IS NULL OR c.checked_at <= incidents.ended_at)
              AND c.status = 'DOWN')""")

    # An old open DOWN incident whose latest check is BLOCKED/UNKNOWN:
    # close it at that check and open an ACCESS_ISSUE incident instead.
    stale = db.execute("""
        SELECT i.id, i.endpoint_id, i.started_at, c.checked_at, c.status, c.error
        FROM incidents i
        JOIN checks c ON c.id = (SELECT MAX(id) FROM checks WHERE endpoint_id = i.endpoint_id)
        WHERE i.ended_at IS NULL AND i.incident_type = 'DOWN'
          AND c.status IN ('BLOCKED', 'UNKNOWN')""").fetchall()
    for row in stale:
        seconds = seconds_between(row["started_at"], row["checked_at"])
        db.execute("UPDATE incidents SET ended_at = ?, duration_seconds = ? WHERE id = ?",
                   (row["checked_at"], seconds, row["id"]))
        db.execute("""INSERT INTO incidents (endpoint_id, started_at, reason, incident_type)
                      VALUES (?, ?, ?, 'ACCESS_ISSUE')""",
                   (row["endpoint_id"], row["checked_at"], row["error"] or row["status"]))


def seconds_between(start_text, end_text):
    """Seconds between two ISO timestamps (never negative)."""
    start = datetime.fromisoformat(start_text)
    end = datetime.fromisoformat(end_text)
    return round(max(0, (end - start).total_seconds()), 1)


def incident_type_for(status):
    """Which kind of incident does this status belong to? None = healthy."""
    if status == "DOWN":
        return "DOWN"
    if status in ("BLOCKED", "UNKNOWN"):
        return "ACCESS_ISSUE"
    return None


def record_check(endpoint_id, checked_at, status, code, ms, error):
    """Save one check result and open / close incidents as needed.

    Rules:
    - a new incident starts at the first DOWN (or access problem) check
    - it ends when the type changes or the endpoint answers UP / SLOW
    """
    new_type = incident_type_for(status)
    with connect() as db:
        db.execute(
            """INSERT INTO checks (endpoint_id, checked_at, status, http_code, response_ms, error)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (endpoint_id, checked_at, status, code, ms, error),
        )

        open_incident = db.execute(
            """SELECT id, started_at, incident_type FROM incidents
               WHERE endpoint_id = ? AND ended_at IS NULL
               ORDER BY id DESC LIMIT 1""",
            (endpoint_id,),
        ).fetchone()

        # Type changed (or the endpoint recovered): close the open incident
        if open_incident is not None and open_incident["incident_type"] != new_type:
            seconds = seconds_between(open_incident["started_at"], checked_at)
            db.execute("UPDATE incidents SET ended_at = ?, duration_seconds = ? WHERE id = ?",
                       (checked_at, seconds, open_incident["id"]))
            open_incident = None

        # Problem and nothing open yet: start a new incident
        if new_type is not None and open_incident is None:
            if error:
                reason = error
            elif code is not None:
                reason = f"HTTP {code}"
            else:
                reason = status
            db.execute(
                """INSERT INTO incidents (endpoint_id, started_at, reason, incident_type)
                   VALUES (?, ?, ?, ?)""",
                (endpoint_id, checked_at, reason, new_type),
            )


def get_endpoints():
    """Every monitored endpoint as a plain dict."""
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM endpoints ORDER BY id")]


def delete_old_checks():
    """Delete check rows older than KEEP_DAYS. Incidents are kept."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.KEEP_DAYS)).isoformat()
    with connect() as db:
        db.execute("DELETE FROM checks WHERE checked_at < ?", (cutoff,))
