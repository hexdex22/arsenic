"""Continuously refreshed terminal display of the GPS state."""

from __future__ import annotations

import asyncio
import sys

from .nmea import GPSState

CLEAR = "\x1b[2J\x1b[H"
DEG = "\N{DEGREE SIGN}"


def _value(v, unit: str = "", digits: int | None = None) -> str:
    if v is None:
        return "---"
    if digits is not None and isinstance(v, float):
        v = f"{v:.{digits}f}"
    return f"{v}{unit}"


def render(state: GPSState) -> str:
    s = state
    lines = []
    lines.append("=" * 72)
    lines.append("  GPS LIVE DATA".ljust(52) + f"{_value(s.utc_date)}  {_value(s.utc_time)} UTC")
    lines.append("=" * 72)
    lines.append(
        f"  Position   {_value(s.latitude, '', 6)}, {_value(s.longitude, '', 6)}"
    )
    lines.append(
        f"  Altitude   {_value(s.altitude_m, ' m', 1)}   "
        f"(geoid separation {_value(s.geoid_separation_m, ' m', 1)})"
    )
    lines.append(
        f"  Fix        {_value(s.status)} | {_value(s.fix_quality)} | "
        f"{_value(s.fix_type)} | sats used: {_value(s.satellites_used)}"
    )
    lines.append(
        f"  DOP        PDOP {_value(s.pdop)}  HDOP {_value(s.hdop)}  VDOP {_value(s.vdop)}"
    )
    lines.append(
        f"  Motion     {_value(s.speed_knots, ' kn', 1)} "
        f"({_value(s.speed_kmh, ' km/h', 1)})  "
        f"course {_value(s.course_deg, DEG, 1)} true / "
        f"{_value(s.course_magnetic_deg, DEG, 1)} mag"
    )
    lines.append(
        f"  Mag var    {_value(s.magnetic_variation_deg, DEG, 1)}   "
        f"DGPS: {_value(s.dgps_age_s, ' s')} / station {_value(s.dgps_station)}"
    )
    lines.append("-" * 72)
    lines.append("  Satellites in view (PRN el/az SNR):")
    for system, sats in sorted(state.satellites_in_view.items()):
        lines.append(f"    {system}:")
        for sat in sats:
            snr = sat.snr or 0
            bar = "#" * (snr // 3)
            lines.append(
                f"      PRN {sat.prn:>3}  "
                f"{_value(sat.elevation, DEG):>5}/"
                f"{_value(sat.azimuth, DEG):>5}  "
                f"{_value(sat.snr):>3} dB-Hz  {bar}"
            )
    if not state.satellites_in_view:
        lines.append("    (none reported yet)")
    lines.append("-" * 72)
    lines.append(
        f"  {s.sentences_received} sentences received, "
        f"{s.sentences_rejected} rejected"
    )
    lines.append(f"  Last: {s.last_sentence or '---'}")
    lines.append("=" * 72)
    return "\n".join(lines)


async def run_console(state: GPSState, hz: float = 2.0) -> None:
    interval = 1.0 / hz
    while True:
        sys.stdout.write(CLEAR + render(state) + "\n")
        sys.stdout.flush()
        await asyncio.sleep(interval)
