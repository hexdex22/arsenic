"""Live web dashboard for the GPS state, using only the standard library.

Serves:
    /            the dashboard page (embedded below)
    /events      Server-Sent Events stream of the full GPS state as JSON
    /state.json  one-shot snapshot of the same JSON

The page connects to /events and re-renders on every update, so the
display is continuous for as long as the chip keeps talking.
"""

from __future__ import annotations

import asyncio
import json

from .nmea import GPSState

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GPS Live Data</title>
<style>
  :root {
    --surface-1: #fcfcfb;
    --page: #f9f9f7;
    --ink-1: #0b0b0b;
    --ink-2: #52514e;
    --muted: #898781;
    --grid: #e1e0d9;
    --border: rgba(11,11,11,0.10);
    --series-1: #2a78d6;  /* GPS */
    --series-2: #1baf7a;  /* GLONASS */
    --series-3: #eda100;  /* Galileo */
    --series-5: #4a3aa7;  /* BeiDou */
    --series-7: #e87ba4;  /* QZSS / other */
    --good: #006300;
    --critical: #d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface-1: #1a1a19;
      --page: #0d0d0d;
      --ink-1: #ffffff;
      --ink-2: #c3c2b7;
      --muted: #898781;
      --grid: #2c2c2a;
      --border: rgba(255,255,255,0.10);
      --series-1: #3987e5;
      --series-2: #199e70;
      --series-3: #c98500;
      --series-5: #9085e9;
      --series-7: #d55181;
      --good: #0ca30c;
      --critical: #d03b3b;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px;
    background: var(--page); color: var(--ink-1);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 14px;
  }
  h1 { font-size: 18px; margin: 0 0 4px; font-weight: 650; }
  .sub { color: var(--muted); margin: 0 0 16px; font-size: 12px; }
  .sub .dot { color: var(--good); }
  .sub .dot.stale { color: var(--critical); }
  .grid {
    display: grid; gap: 12px;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  }
  .card {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 16px;
  }
  .card h2 {
    font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--muted); margin: 0 0 10px;
  }
  .rows { display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; }
  .rows dt { color: var(--ink-2); }
  .rows dd {
    margin: 0; text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .hero { font-size: 26px; font-weight: 650; margin: 0 0 2px; }
  .hero-sub { color: var(--ink-2); font-size: 13px; margin: 0 0 12px; }
  .wide { grid-column: 1 / -1; }
  .legend { display: flex; gap: 14px; flex-wrap: wrap; margin: 0 0 10px; }
  .legend span { color: var(--ink-2); font-size: 12px; }
  .legend i {
    display: inline-block; width: 10px; height: 10px;
    border-radius: 3px; margin-right: 5px; vertical-align: -1px;
  }
  .snr {
    display: flex; align-items: flex-end; gap: 2px;
    height: 130px; border-bottom: 1px solid var(--grid);
    overflow-x: auto; padding-top: 14px;
  }
  .snr .bar-wrap {
    flex: 1 0 26px; max-width: 44px; height: 100%;
    display: flex; flex-direction: column; justify-content: flex-end;
    align-items: center; position: relative;
  }
  .snr .bar {
    width: 70%; border-radius: 4px 4px 0 0; min-height: 2px;
  }
  .snr .val {
    font-size: 10px; color: var(--muted); margin-bottom: 2px;
    font-variant-numeric: tabular-nums;
  }
  .snr-labels { display: flex; gap: 2px; margin-top: 4px; }
  .snr-labels span {
    flex: 1 0 26px; max-width: 44px; text-align: center;
    font-size: 10px; color: var(--muted);
    font-variant-numeric: tabular-nums;
  }
  .raw {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11.5px; line-height: 1.55; color: var(--ink-2);
    white-space: pre; overflow-x: auto; margin: 0;
  }
  .raw .latest { color: var(--ink-1); font-weight: 600; }
</style>
</head>
<body>
<h1>GPS Live Data</h1>
<p class="sub">
  <span class="dot" id="dot">●</span>
  <span id="conn">connecting…</span> ·
  <span id="stats"></span>
</p>

<div class="grid">
  <div class="card">
    <h2>Position</h2>
    <p class="hero" id="latlon">—</p>
    <p class="hero-sub" id="latlon-dms"></p>
    <dl class="rows">
      <dt>Altitude (MSL)</dt><dd id="alt">—</dd>
      <dt>Geoid separation</dt><dd id="geoid">—</dd>
    </dl>
  </div>

  <div class="card">
    <h2>Fix</h2>
    <dl class="rows">
      <dt>Status</dt><dd id="status">—</dd>
      <dt>Quality</dt><dd id="quality">—</dd>
      <dt>Mode</dt><dd id="fixtype">—</dd>
      <dt>Satellites used</dt><dd id="used">—</dd>
      <dt>PDOP / HDOP / VDOP</dt><dd id="dop">—</dd>
      <dt>DGPS age / station</dt><dd id="dgps">—</dd>
    </dl>
  </div>

  <div class="card">
    <h2>Motion</h2>
    <dl class="rows">
      <dt>Speed</dt><dd id="speed">—</dd>
      <dt>Course (true)</dt><dd id="course">—</dd>
      <dt>Course (magnetic)</dt><dd id="course-mag">—</dd>
      <dt>Magnetic variation</dt><dd id="magvar">—</dd>
    </dl>
  </div>

  <div class="card">
    <h2>Time (UTC from satellites)</h2>
    <p class="hero" id="utc-time">—</p>
    <dl class="rows">
      <dt>Date</dt><dd id="utc-date">—</dd>
    </dl>
  </div>

  <div class="card wide">
    <h2>Satellites in view — signal-to-noise ratio (dB-Hz)</h2>
    <div class="legend" id="legend"></div>
    <div class="snr" id="snr"></div>
    <div class="snr-labels" id="snr-labels"></div>
  </div>

  <div class="card wide">
    <h2>Raw NMEA feed</h2>
    <pre class="raw" id="raw">waiting for data…</pre>
  </div>
</div>

<script>
const SYSTEM_COLORS = {
  "GPS": "var(--series-1)",
  "GLONASS": "var(--series-2)",
  "Galileo": "var(--series-3)",
  "BeiDou": "var(--series-5)",
  "QZSS": "var(--series-7)",
  "GNSS": "var(--series-1)",
};
const $ = id => document.getElementById(id);
const fmt = (v, unit = "", digits = null) =>
  v === null || v === undefined
    ? "—"
    : (digits === null ? v : v.toFixed(digits)) + unit;

function toDMS(value, pos, neg) {
  const hemi = value >= 0 ? pos : neg;
  const abs = Math.abs(value);
  const deg = Math.floor(abs);
  const minFloat = (abs - deg) * 60;
  const min = Math.floor(minFloat);
  const sec = (minFloat - min) * 60;
  return `${deg}\\u00b0${min}'${sec.toFixed(2)}" ${hemi}`;
}

function render(s) {
  const p = s.position, f = s.fix, m = s.motion, t = s.time;

  if (p.latitude !== null && p.longitude !== null) {
    $("latlon").textContent =
      p.latitude.toFixed(6) + ", " + p.longitude.toFixed(6);
    $("latlon-dms").textContent =
      toDMS(p.latitude, "N", "S") + "  " + toDMS(p.longitude, "E", "W");
  }
  $("alt").textContent = fmt(p.altitude_m, " m", 1);
  $("geoid").textContent = fmt(p.geoid_separation_m, " m", 1);

  $("status").textContent = f.status ?? "—";
  $("quality").textContent = f.quality ?? "—";
  $("fixtype").textContent = f.type ?? "—";
  $("used").textContent =
    f.satellites_used === null
      ? "—"
      : f.satellites_used +
        (f.active_prns.length ? " (PRN " + f.active_prns.join(", ") + ")" : "");
  $("dop").textContent =
    [f.pdop, f.hdop, f.vdop].map(v => v ?? "—").join(" / ");
  $("dgps").textContent =
    f.dgps_age_s === null && !f.dgps_station
      ? "—"
      : (f.dgps_age_s ?? "—") + " s / " + (f.dgps_station || "—");

  $("speed").textContent =
    m.speed_knots === null
      ? "—"
      : m.speed_knots.toFixed(1) + " kn (" +
        (m.speed_kmh ?? m.speed_knots * 1.852).toFixed(1) + " km/h)";
  $("course").textContent = fmt(m.course_deg, "\\u00b0", 1);
  $("course-mag").textContent = fmt(m.course_magnetic_deg, "\\u00b0", 1);
  $("magvar").textContent = fmt(m.magnetic_variation_deg, "\\u00b0", 1);

  $("utc-time").textContent = t.utc_time ?? "—";
  $("utc-date").textContent = t.utc_date ?? "—";

  const sats = [];
  for (const [system, list] of Object.entries(s.satellites_in_view)) {
    for (const sat of list) sats.push(sat);
  }
  sats.sort((a, b) =>
    a.system === b.system ? (a.prn ?? 0) - (b.prn ?? 0)
                          : a.system.localeCompare(b.system));
  const bars = $("snr"), labels = $("snr-labels");
  bars.innerHTML = ""; labels.innerHTML = "";
  const systems = new Set();
  for (const sat of sats) {
    systems.add(sat.system);
    const snr = sat.snr ?? 0;
    const wrap = document.createElement("div");
    wrap.className = "bar-wrap";
    wrap.title = `${sat.system} PRN ${sat.prn}\\nSNR ${sat.snr ?? "—"} dB-Hz` +
      `\\nelevation ${sat.elevation ?? "—"}\\u00b0, azimuth ${sat.azimuth ?? "—"}\\u00b0`;
    const val = document.createElement("div");
    val.className = "val";
    val.textContent = sat.snr ?? "";
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.height = Math.min(100, (snr / 55) * 100) + "%";
    bar.style.background = SYSTEM_COLORS[sat.system] || "var(--series-7)";
    wrap.appendChild(val);
    wrap.appendChild(bar);
    bars.appendChild(wrap);
    const label = document.createElement("span");
    label.textContent = sat.prn;
    labels.appendChild(label);
  }
  const legend = $("legend");
  legend.innerHTML = "";
  for (const system of [...systems].sort()) {
    const item = document.createElement("span");
    const chip = document.createElement("i");
    chip.style.background = SYSTEM_COLORS[system] || "var(--series-7)";
    item.appendChild(chip);
    item.appendChild(document.createTextNode(system + " (PRN labels below bars)"));
    legend.appendChild(item);
  }

  const raw = s.raw_log.slice(-14);
  $("raw").innerHTML = raw
    .map((line, i) => {
      const safe = line.replace(/&/g, "&amp;").replace(/</g, "&lt;");
      return i === raw.length - 1
        ? '<span class="latest">' + safe + "</span>"
        : safe;
    })
    .join("\\n");

  $("stats").textContent =
    s.stats.sentences_received + " sentences received, " +
    s.stats.sentences_rejected + " rejected (bad checksum)" +
    (s.stats.age_s !== null ? " \\u00b7 last data " + s.stats.age_s + "s ago" : "");
  $("dot").classList.toggle("stale", s.stats.age_s !== null && s.stats.age_s > 5);
}

const events = new EventSource("/events");
events.onopen = () => { $("conn").textContent = "live"; };
events.onerror = () => { $("conn").textContent = "reconnecting\\u2026"; };
events.onmessage = e => render(JSON.parse(e.data));
</script>
</body>
</html>
"""


class WebDisplay:
    """Minimal asyncio HTTP server: dashboard page + SSE state stream."""

    def __init__(self, state: GPSState, host: str, port: int, hz: float = 2.0):
        self.state = state
        self.host = host
        self.port = port
        self.interval = 1.0 / hz

    async def run(self) -> None:
        server = await asyncio.start_server(self._handle, self.host, self.port)
        shown = self.host if self.host != "0.0.0.0" else "localhost"
        print(f"GPS dashboard: http://{shown}:{self.port}/  (Ctrl+C to stop)")
        async with server:
            await server.serve_forever()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = await asyncio.wait_for(reader.readline(), timeout=10)
            parts = request.decode("latin-1").split()
            path = parts[1] if len(parts) >= 2 else "/"
            # Drain the request headers
            while True:
                header = await asyncio.wait_for(reader.readline(), timeout=10)
                if header in (b"\r\n", b"\n", b""):
                    break

            if path.startswith("/events"):
                await self._serve_events(writer)
            elif path.startswith("/state.json"):
                body = json.dumps(self.state.to_dict()).encode()
                await self._respond(writer, body, "application/json")
            elif path in ("/", "/index.html"):
                await self._respond(writer, PAGE.encode(), "text/html; charset=utf-8")
            else:
                await self._respond(writer, b"not found", "text/plain", "404 Not Found")
        except (asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _respond(
        self,
        writer: asyncio.StreamWriter,
        body: bytes,
        content_type: str,
        status: str = "200 OK",
    ) -> None:
        writer.write(
            (
                f"HTTP/1.1 {status}\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Cache-Control: no-store\r\n"
                "Connection: close\r\n\r\n"
            ).encode()
            + body
        )
        await writer.drain()

    async def _serve_events(self, writer: asyncio.StreamWriter) -> None:
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-store\r\n"
            b"Connection: keep-alive\r\n\r\n"
        )
        await writer.drain()
        while True:
            payload = json.dumps(self.state.to_dict())
            writer.write(f"data: {payload}\n\n".encode())
            await writer.drain()
            await asyncio.sleep(self.interval)
