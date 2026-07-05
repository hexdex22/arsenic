"""Async NMEA line sources: a real GPS chip on a serial port, a recorded
NMEA file, or a built-in simulator (for running without hardware).

Each source is an async iterator that yields NMEA sentences as strings,
forever (the file source loops).
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import AsyncIterator

from .nmea import make_sentence


async def serial_lines(device: str, baudrate: int = 9600) -> AsyncIterator[str]:
    """Read NMEA lines from a GPS chip on a serial device.

    Uses pyserial when it is installed (so the baud rate can be set from
    here); otherwise opens the device as a plain file, in which case the
    port must already be configured, e.g.:

        stty -F /dev/ttyUSB0 9600 raw
    """
    try:
        import serial  # type: ignore
    except ImportError:
        serial = None

    loop = asyncio.get_running_loop()

    if serial is not None:
        port = serial.Serial(device, baudrate=baudrate, timeout=1)
        read = lambda: port.readline()
        close = port.close
    else:
        stream = open(device, "rb", buffering=0)
        read = stream.readline
        close = stream.close

    try:
        while True:
            raw = await loop.run_in_executor(None, read)
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").strip()
            if line:
                yield line
    finally:
        close()


async def file_lines(path: str, interval: float = 0.1) -> AsyncIterator[str]:
    """Replay a recorded NMEA log file, looping forever."""
    while True:
        with open(path, "r", encoding="ascii", errors="replace") as stream:
            for line in stream:
                line = line.strip()
                if line:
                    yield line
                    await asyncio.sleep(interval)


async def simulator_lines(
    latitude: float = 35.681236,
    longitude: float = 139.767125,
    interval: float = 1.0,
) -> AsyncIterator[str]:
    """Generate a realistic, checksummed NMEA stream: a receiver moving in
    a slow circle, with drifting satellite SNRs. Default start point is
    Tokyo Station.
    """
    rng = random.Random(42)
    sats = [
        # [prn, elevation, azimuth, snr]
        [prn, rng.randint(5, 85), rng.randint(0, 359), rng.randint(18, 45)]
        for prn in rng.sample(range(1, 33), 9)
    ]
    step = 0
    sim_seconds = 0.0

    while True:
        angle = step * 0.02
        lat = latitude + 0.001 * math.sin(angle)
        lon = longitude + 0.001 * math.cos(angle)
        speed_knots = 2.5 + 0.5 * math.sin(step * 0.1)
        course = (math.degrees(angle) + 90.0) % 360.0
        altitude = 12.0 + 2.0 * math.sin(step * 0.05)
        hdop, vdop = 0.9, 1.3
        pdop = round(math.hypot(hdop, vdop), 1)

        sim_seconds += interval
        total = int(sim_seconds)
        hh, mm, ss = total // 3600 % 24, total // 60 % 60, total % 60
        timestamp = f"{hh:02d}{mm:02d}{ss:02d}.00"
        datestamp = "050726"

        lat_deg = int(abs(lat))
        lat_min = (abs(lat) - lat_deg) * 60
        lon_deg = int(abs(lon))
        lon_min = (abs(lon) - lon_deg) * 60
        lat_nmea = f"{lat_deg:02d}{lat_min:07.4f}"
        lat_hemi = "N" if lat >= 0 else "S"
        lon_nmea = f"{lon_deg:03d}{lon_min:07.4f}"
        lon_hemi = "E" if lon >= 0 else "W"

        for sat in sats:
            sat[3] = max(10, min(50, sat[3] + rng.randint(-2, 2)))
            sat[2] = (sat[2] + 1) % 360

        used = [sat[0] for sat in sats[:7]]
        prn_fields = ",".join(str(p) for p in used) + "," * (12 - len(used))

        sentences = [
            f"GPGGA,{timestamp},{lat_nmea},{lat_hemi},{lon_nmea},{lon_hemi},"
            f"1,{len(used):02d},{hdop},{altitude:.1f},M,39.5,M,,",
            f"GPRMC,{timestamp},A,{lat_nmea},{lat_hemi},{lon_nmea},{lon_hemi},"
            f"{speed_knots:.1f},{course:.1f},{datestamp},7.5,W",
            f"GPGSA,A,3,{prn_fields},{pdop},{hdop},{vdop}",
            f"GPVTG,{course:.1f},T,{(course - 7.5) % 360:.1f},M,"
            f"{speed_knots:.1f},N,{speed_knots * 1.852:.1f},K",
            f"GPGLL,{lat_nmea},{lat_hemi},{lon_nmea},{lon_hemi},{timestamp},A",
            f"GPZDA,{timestamp},05,07,2026,00,00",
        ]

        # GSV: satellites in view, four per sentence
        total_msgs = math.ceil(len(sats) / 4)
        for msg_num in range(1, total_msgs + 1):
            chunk = sats[(msg_num - 1) * 4 : msg_num * 4]
            body = ",".join(
                f"{prn:02d},{el:02d},{az:03d},{snr:02d}"
                for prn, el, az, snr in chunk
            )
            sentences.append(f"GPGSV,{total_msgs},{msg_num},{len(sats):02d},{body}")

        for payload in sentences:
            yield make_sentence(payload)

        step += 1
        await asyncio.sleep(interval)
