"""The part that actually calls the endpoints and decides UP / SLOW / DOWN."""
import asyncio
import ipaddress
import socket
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app import config
from app.database import delete_old_checks, get_endpoints, record_check

# Only one round of checks at a time
round_lock = asyncio.Lock()


def validate_url(url):
    """Allow only public HTTPS addresses. Raises ValueError if not allowed."""
    parsed = urlparse(url)

    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Only public HTTPS endpoints on port 443 are supported")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Only public HTTPS endpoints on port 443 are supported")

    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal")):
        raise ValueError("Private hosts are not permitted")

    # Look up the IP addresses and make sure every one is public
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Hostname cannot be resolved") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Endpoint must resolve exclusively to public addresses")

    return url


def classify(code, ms, slow_ms):
    """Turn an HTTP status code and response time into a status word."""
    if code in (401, 403, 407, 429):
        return "BLOCKED"
    if 300 <= code < 400:
        return "UNKNOWN"          # redirects are not followed, so we can't tell
    if code >= 500 or code in (404, 410):
        return "DOWN"
    if code >= 400:
        return "UNKNOWN"          # other 4xx errors don't prove an outage
    if ms >= slow_ms:
        return "SLOW"
    return "UP"


def diagnose(status, code, error):
    """Short explanation of what we saw. Returns (code_word, sentence)."""
    message = (error or "").lower()

    if "certificate_verify_failed" in message or "certificate verify failed" in message \
            or ("ssl" in message and "certificate" in message):
        return "TLS_CERTIFICATE_ERROR", "Certificate verification failed; an office proxy or certificate chain may be involved."
    if "name or service not known" in message or "getaddrinfo failed" in message \
            or "hostname cannot be resolved" in message:
        return "DNS_ERROR", "DNS resolution failed from this monitoring environment."
    if "timeout" in message or "timed out" in message:
        return "TIMEOUT", "The request timed out from this monitoring environment."
    if code in (401, 403, 407, 429):
        return "ACCESS_RESTRICTED", f"HTTP {code}; the server or an intermediary rejected the request."
    if code is not None and code >= 500:
        return "SERVER_ERROR", f"HTTP {code} returned by the responding server or gateway."
    if code in (404, 410):
        return "RESOURCE_NOT_FOUND", f"HTTP {code}; this URL is unavailable, not necessarily the entire website."
    if status == "DOWN":
        return "CONNECTION_ERROR", "The request failed from this monitoring environment."
    if status == "SLOW":
        return "HIGH_LATENCY", "The response exceeded the configured threshold."
    if status == "UP":
        return "SUCCESS", "The requested URL returned a successful response."
    return "UNVERIFIED", "Availability could not be established."


async def check_endpoint(client, endpoint):
    """Check one endpoint once and save the result. Returns the status word."""
    start = time.perf_counter()
    code = None
    error = None

    try:
        # DNS lookup blocks, so run it in a thread to keep the app responsive
        await asyncio.to_thread(validate_url, endpoint["url"])

        response = await client.get(endpoint["url"])
        code = response.status_code
        ms = round((time.perf_counter() - start) * 1000, 1)
        status = classify(code, ms, endpoint["slow_ms"])
        if status in ("BLOCKED", "DOWN", "UNKNOWN"):
            error = f"HTTP {code}"

    except ValueError as exc:
        # Our own URL check failed: can't say the endpoint is down
        ms = round((time.perf_counter() - start) * 1000, 1)
        status = "UNKNOWN"
        error = str(exc)[:300]

    except (httpx.HTTPError, OSError) as exc:
        ms = round((time.perf_counter() - start) * 1000, 1)
        text = str(exc).lower()
        is_tls_problem = isinstance(exc, httpx.ConnectError) and ("certificate" in text or "ssl" in text)
        status = "UNKNOWN" if is_tls_problem else "DOWN"
        error = f"{type(exc).__name__}: {exc}"[:300]

    now = datetime.now(timezone.utc).isoformat()
    try:
        await asyncio.to_thread(record_check, endpoint["id"], now, status, code, ms, error)
    except sqlite3.IntegrityError:
        pass  # the endpoint was removed while we were checking it

    return status


async def run_checks():
    """Check every endpoint at the same time (skipped if a round is running)."""
    if round_lock.locked():
        return
    async with round_lock:
        endpoints = await asyncio.to_thread(get_endpoints)
        if not endpoints:
            return
        # One shared client = connections are reused between endpoints
        async with httpx.AsyncClient(
            timeout=config.REQUEST_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": config.USER_AGENT},
        ) as client:
            await asyncio.gather(*(check_endpoint(client, ep) for ep in endpoints))


async def monitoring_loop():
    """Run forever: check, wait, check again. Use ONE server worker only."""
    rounds = 0
    while True:
        await run_checks()
        rounds += 1
        if rounds % 360 == 0:  # about once an hour at the default interval
            await asyncio.to_thread(delete_old_checks)
        await asyncio.sleep(config.CHECK_INTERVAL)
