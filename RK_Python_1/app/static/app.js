// RK_Python_1 dashboard script. No libraries: just fetch() and plain DOM code.

const REFRESH_MS = 10000;

function $(id) {
  return document.getElementById(id);
}

// Escape text before putting it into innerHTML (stops HTML injection)
function escapeHtml(value) {
  const text = String(value ?? "—");
  const replacements = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return text.replace(/[&<>"']/g, (ch) => replacements[ch]);
}

function formatDuration(totalSeconds) {
  if (totalSeconds == null) return "—";
  const s = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  return `${days}d ${hours}h ${minutes}m ${s % 60}s`;
}

function formatTime(isoText) {
  if (!isoText) return "—";
  return new Date(isoText).toLocaleString("en-GB", {
    timeZone: "UTC", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function statusBadge(status) {
  const known = ["UP", "DOWN", "SLOW", "BLOCKED"];
  const cssClass = known.includes(status) ? status : "UNKNOWN";
  return `<span class="status ${cssClass}">${escapeHtml(status || "PENDING")}</span>`;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}

// ---------- drawing ----------

function endpointRow(e) {
  const latency = e.response_ms == null ? "—" : escapeHtml(e.response_ms) + " ms";
  const uptime = e.uptime_pct == null ? "—" : escapeHtml(e.uptime_pct) + "%";
  const downtime = e.down_since ? formatDuration(e.downtime_seconds) : "—";
  const reasonText = e.error || e.diagnostic_detail || "—";

  return `<tr>
    <td><b>${escapeHtml(e.name)}</b><div class="muted endpoint-url">${escapeHtml(e.url)}</div></td>
    <td>${statusBadge(e.status)}</td>
    <td>${escapeHtml(e.http_code)}</td>
    <td>${latency}</td>
    <td>${uptime}</td>
    <td>${downtime}</td>
    <td><div class="reason" title="${escapeHtml(e.error || "")}">${escapeHtml(e.diagnostic_code || "UNVERIFIED")}<br>${escapeHtml(reasonText)}</div></td>
    <td>${formatTime(e.checked_at)}</td>
    <td><button type="button" class="delete-btn" data-id="${Number(e.id)}" data-name="${escapeHtml(e.name)}">Remove</button></td>
  </tr>`;
}

function incidentRow(i) {
  const kind = i.incident_type === "DOWN" ? "Endpoint outage" : "Access issue";
  return `<tr>
    <td>${escapeHtml(i.name)}</td>
    <td>${formatTime(i.started_at)}</td>
    <td>${formatTime(i.ended_at)}</td>
    <td>${formatDuration(i.duration_seconds)}</td>
    <td>${kind} · ${escapeHtml(i.state)}</td>
  </tr>`;
}

function historyRow(h) {
  return `<tr>
    <td>${escapeHtml(h.name)}</td>
    <td>${formatTime(h.checked_at)}</td>
    <td>${statusBadge(h.status)}</td>
    <td>${escapeHtml(h.response_ms)} ms</td>
  </tr>`;
}

// Draws the response-time line chart as an SVG (no chart library needed)
function drawTrend(history) {
  const box = $("chart");

  // history comes newest-first, so take 40 and flip to oldest-first
  const points = history
    .filter((h) => h.response_ms !== null && Number.isFinite(Number(h.response_ms)))
    .slice(0, 40)
    .reverse();

  if (points.length === 0) {
    box.innerHTML = '<div class="chart-empty">Waiting for first monitoring observations…</div>';
    return;
  }

  const width = 760, height = 245;
  const left = 54, right = 18, top = 18, bottom = 38;
  const plotW = width - left - right;
  const plotH = height - top - bottom;

  const biggest = Math.max(1000, ...points.map((p) => Number(p.response_ms)));
  const yMax = Math.ceil(biggest / 1000) * 1000;

  const coords = points.map((p, index) => {
    const fraction = points.length === 1 ? 0.5 : index / (points.length - 1);
    const x = left + fraction * plotW;
    const y = top + plotH - (Number(p.response_ms) / yMax) * plotH;
    return [x, y];
  });

  const line = coords.map((c) => c[0].toFixed(1) + "," + c[1].toFixed(1)).join(" ");
  const area = `${left},${top + plotH} ${line} ${coords[coords.length - 1][0].toFixed(1)},${top + plotH}`;

  let grid = "";
  for (let i = 0; i <= 4; i++) {
    const y = top + (plotH * i) / 4;
    const label = Math.round(yMax * (1 - i / 4)).toLocaleString();
    grid += `<line x1="${left}" x2="${width - right}" y1="${y}" y2="${y}" stroke="#e9ecf8"/>`;
    grid += `<text x="${left - 10}" y="${y + 4}" text-anchor="end" fill="#8893ad" font-size="11">${label}</text>`;
  }

  // time labels: first, middle, last
  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  const timeLabels = labelIndexes.map((i) => {
    const text = new Date(points[i].checked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return `<text x="${coords[i][0]}" y="${height - 9}" text-anchor="middle" fill="#8893ad" font-size="11">${text}</text>`;
  }).join("");

  const dots = coords.map((c, i) =>
    `<circle cx="${c[0]}" cy="${c[1]}" r="2.8" fill="#716bed"><title>${escapeHtml(points[i].name)}: ${Number(points[i].response_ms).toFixed(1)} ms</title></circle>`
  ).join("");

  box.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" aria-label="Latency over the last ${points.length} observations">
    <defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
      <stop stop-color="#7672ef" stop-opacity=".20"/><stop offset="1" stop-color="#7672ef" stop-opacity="0"/>
    </linearGradient></defs>
    ${grid}
    <polygon points="${area}" fill="url(#trendFill)"/>
    <polyline points="${line}" fill="none" stroke="#716bed" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
    ${dots}${timeLabels}
  </svg>`;
}

// ---------- loading data ----------

async function loadDashboard() {
  try {
    const [summary, history, incidents] = await Promise.all([
      getJson("/api/summary"),
      getJson("/api/history?limit=80"),
      getJson("/api/incidents?limit=40"),
    ]);

    $("total").textContent = summary.total;
    $("up").textContent = summary.up;
    $("down").textContent = summary.down;
    $("slow").textContent = summary.slow;
    $("blocked").textContent = summary.blocked;
    $("unknown").textContent = summary.unknown;
    $("avg").textContent = summary.avg_ms == null ? "—" : summary.avg_ms + " ms";

    $("endpoints").innerHTML = summary.endpoints.map(endpointRow).join("");

    $("incidents").innerHTML = incidents.length
      ? incidents.slice(0, 12).map(incidentRow).join("")
      : '<tr><td colspan="5">No availability or access incidents recorded</td></tr>';

    $("history").innerHTML = history.slice(0, 12).map(historyRow).join("");
    drawTrend(history);
    $("load-error").textContent = "";
  } catch (err) {
    $("load-error").textContent = "Dashboard refresh failed: " + err.message;
  }
}

// ---------- buttons and form ----------

// "Remove" buttons are created dynamically, so listen on the table body
$("endpoints").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-id]");
  if (!button) return;

  const id = Number(button.dataset.id);
  const name = button.dataset.name;
  if (!confirm(`Remove "${name}"? This permanently deletes its check history and incidents.`)) return;

  button.disabled = true;
  try {
    const response = await fetch(`/api/endpoints/${id}`, { method: "DELETE" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not remove endpoint");
    await loadDashboard();
  } catch (err) {
    alert("Removal failed: " + err.message);
    button.disabled = false;
  }
});

$("refresh").addEventListener("click", async () => {
  const button = $("refresh");
  button.disabled = true;
  button.textContent = "Checking…";
  try {
    await fetch("/api/check-now", { method: "POST" });
    await loadDashboard();
  } finally {
    button.disabled = false;
    button.textContent = "↻ Check Now";
  }
});

$("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("form-error").textContent = "";

  const data = Object.fromEntries(new FormData(event.target));
  data.slow_ms = Number(data.slow_ms);

  try {
    const response = await fetch("/api/endpoints", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(typeof body.detail === "string" ? body.detail : "Invalid endpoint");
    }
    event.target.reset();
    await loadDashboard();
  } catch (err) {
    $("form-error").textContent = err.message;
  }
});

loadDashboard();
setInterval(loadDashboard, REFRESH_MS);
