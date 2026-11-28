import pytest
from datetime import datetime, timedelta, timezone

from app import config
from app.checker import classify, diagnose, validate_url
from app.database import connect, record_check
from app.main import app, delete_endpoint, summary


# ---------- URL checking ----------

def test_routes_exist():
    paths = {route.path for route in app.routes}
    assert {"/", "/api/summary", "/api/history", "/api/incidents",
            "/api/endpoints", "/api/check-now"} <= paths


@pytest.mark.parametrize("url", [
    "http://localhost:8000",       # not https
    "https://localhost",           # local name
    "https://127.0.0.1",           # private IP
    "https://user:pw@example.com", # credentials in URL
    "https://example.com:8443",    # odd port
    "ftp://example.com",           # wrong scheme
])
def test_bad_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


# ---------- status words ----------

def test_classify():
    assert classify(200, 100, 1500) == "UP"
    assert classify(200, 1800, 1500) == "SLOW"
    assert classify(403, 100, 1500) == "BLOCKED"
    assert classify(429, 100, 1500) == "BLOCKED"
    assert classify(503, 100, 1500) == "DOWN"
    assert classify(404, 100, 1500) == "DOWN"
    assert classify(302, 100, 1500) == "UNKNOWN"
    assert classify(418, 100, 1500) == "UNKNOWN"


def test_diagnose():
    assert diagnose("UNKNOWN", None, "ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED]")[0] == "TLS_CERTIFICATE_ERROR"
    assert diagnose("BLOCKED", 403, "HTTP 403")[0] == "ACCESS_RESTRICTED"
    assert diagnose("DOWN", 503, "HTTP 503")[0] == "SERVER_ERROR"
    assert diagnose("UNKNOWN", None, "Hostname cannot be resolved")[0] == "DNS_ERROR"
    assert diagnose("DOWN", None, "ReadTimeout: timed out")[0] == "TIMEOUT"
    assert diagnose("UP", 200, None)[0] == "SUCCESS"


# ---------- incidents ----------

def test_incident_lifecycle(fresh_db):
    t = datetime(2026, 11, 10, tzinfo=timezone.utc)
    record_check(1, t.isoformat(), "DOWN", 503, 100, "HTTP 503")
    record_check(1, (t + timedelta(seconds=60)).isoformat(), "DOWN", 503, 100, "HTTP 503")
    record_check(1, (t + timedelta(seconds=90)).isoformat(), "BLOCKED", 403, 100, "HTTP 403")
    record_check(1, (t + timedelta(seconds=180)).isoformat(), "UP", 200, 100, None)

    with connect() as db:
        rows = db.execute("SELECT * FROM incidents ORDER BY id").fetchall()

    assert len(rows) == 2
    assert rows[0]["incident_type"] == "DOWN"
    assert rows[0]["duration_seconds"] == 90
    assert rows[1]["incident_type"] == "ACCESS_ISSUE"
    assert rows[1]["duration_seconds"] == 90
    assert all(row["ended_at"] is not None for row in rows)


def test_tls_problem_is_access_issue_not_downtime(fresh_db):
    record_check(1, "2026-11-10T10:00:00+00:00", "UNKNOWN", None, 10, "SSL certificate verify failed")
    with connect() as db:
        incident = db.execute("SELECT * FROM incidents").fetchone()
    assert incident["incident_type"] == "ACCESS_ISSUE"
    assert summary()["endpoints"][0]["down_since"] is None


def test_old_tls_incident_is_relabelled(fresh_db):
    from app.database import init_db
    record_check(1, "2026-11-10T10:00:00+00:00", "UNKNOWN", None, 10, "TLS error")
    with connect() as db:
        db.execute("UPDATE incidents SET incident_type = 'DOWN'")
    init_db()  # the clean-up runs on start-up
    with connect() as db:
        incident = db.execute("SELECT incident_type FROM incidents").fetchone()
    assert incident["incident_type"] == "ACCESS_ISSUE"


# ---------- summary and delete ----------

def test_summary_numbers(fresh_db):
    t = datetime.now(timezone.utc)
    record_check(1, t.isoformat(), "UP", 200, 100, None)
    record_check(1, (t + timedelta(seconds=10)).isoformat(), "DOWN", 503, 50, "HTTP 503")
    data = summary()
    first = data["endpoints"][0]
    assert data["total"] == 3
    assert data["down"] == 1
    assert first["uptime_pct"] == 50.0           # 1 good out of 2 conclusive
    assert first["down_since"] is not None
    assert first["last_success_at"] == t.isoformat()
    assert first["diagnostic_code"] == "SERVER_ERROR"


def test_remove_endpoint_and_its_records(fresh_db):
    record_check(1, "2026-11-10T10:00:00+00:00", "DOWN", 503, 20, "HTTP 503")
    result = delete_endpoint(1)
    assert result["id"] == 1
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM endpoints WHERE id = 1").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM checks WHERE endpoint_id = 1").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM incidents WHERE endpoint_id = 1").fetchone()[0] == 0


def test_old_checks_are_deleted(fresh_db):
    from app.database import delete_old_checks
    old = datetime.now(timezone.utc) - timedelta(days=config.KEEP_DAYS + 1)
    record_check(1, old.isoformat(), "UP", 200, 10, None)
    record_check(1, datetime.now(timezone.utc).isoformat(), "UP", 200, 10, None)
    delete_old_checks()
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM checks").fetchone()[0] == 1


# ---------- web ----------

def test_dashboard_files_are_served(fresh_db):
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        for path in ["/", "/static/style.css", "/static/app.js",
                     "/static/rk-python-icon.webp", "/static/rk-python-logo.webp",
                     "/static/favicon.png"]:
            response = client.get(path)
            assert response.status_code == 200, path
            assert len(response.content) > 100
