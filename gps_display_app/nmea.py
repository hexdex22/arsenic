"""NMEA 0183 sentence parsing and aggregate GPS state.

Supports the sentences emitted by virtually every consumer GPS chip
(u-blox, MTK/MediaTek, SiRF, Quectel, ...):

    GGA - fix data (position, altitude, fix quality, satellites used, HDOP)
    RMC - recommended minimum (position, speed, course, date, magnetic variation)
    GSA - active satellites and dilution of precision (PDOP/HDOP/VDOP, 2D/3D)
    GSV - satellites in view (PRN, elevation, azimuth, SNR)
    VTG - track made good and ground speed
    GLL - geographic position, latitude/longitude
    ZDA - date and time

Talker prefixes (GP=GPS, GL=GLONASS, GA=Galileo, GB/BD=BeiDou, GN=combined)
are all accepted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

FIX_QUALITIES = {
    "0": "No fix",
    "1": "GPS fix",
    "2": "DGPS fix",
    "3": "PPS fix",
    "4": "RTK fixed",
    "5": "RTK float",
    "6": "Dead reckoning",
    "7": "Manual",
    "8": "Simulation",
}

FIX_TYPES = {"1": "No fix", "2": "2D", "3": "3D"}

TALKERS = {
    "GP": "GPS",
    "GL": "GLONASS",
    "GA": "Galileo",
    "GB": "BeiDou",
    "BD": "BeiDou",
    "GQ": "QZSS",
    "GN": "GNSS",
}


def checksum(payload: str) -> int:
    """XOR checksum over the characters between '$' and '*'."""
    value = 0
    for char in payload:
        value ^= ord(char)
    return value


def make_sentence(payload: str) -> str:
    """Wrap a payload into a full NMEA sentence with checksum."""
    return f"${payload}*{checksum(payload):02X}"


def _float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_latitude(value: str, hemisphere: str) -> Optional[float]:
    """ddmm.mmmm + N/S -> signed decimal degrees."""
    if not value or len(value) < 3:
        return None
    try:
        degrees = int(value[:2])
        minutes = float(value[2:])
    except ValueError:
        return None
    result = degrees + minutes / 60.0
    return -result if hemisphere == "S" else result


def parse_longitude(value: str, hemisphere: str) -> Optional[float]:
    """dddmm.mmmm + E/W -> signed decimal degrees."""
    if not value or len(value) < 4:
        return None
    try:
        degrees = int(value[:3])
        minutes = float(value[3:])
    except ValueError:
        return None
    result = degrees + minutes / 60.0
    return -result if hemisphere == "W" else result


def parse_utc_time(value: str) -> Optional[str]:
    """hhmmss.sss -> 'hh:mm:ss.sss'."""
    if not value or len(value) < 6:
        return None
    return f"{value[:2]}:{value[2:4]}:{value[4:]}"


def parse_date(value: str) -> Optional[str]:
    """ddmmyy -> 'yyyy-mm-dd'."""
    if not value or len(value) != 6:
        return None
    return f"20{value[4:6]}-{value[2:4]}-{value[0:2]}"


@dataclass
class Satellite:
    prn: Optional[int]
    elevation: Optional[int]
    azimuth: Optional[int]
    snr: Optional[int]
    system: str

    def to_dict(self) -> dict:
        return {
            "prn": self.prn,
            "elevation": self.elevation,
            "azimuth": self.azimuth,
            "snr": self.snr,
            "system": self.system,
        }


@dataclass
class GPSState:
    """Aggregate of everything the GPS chip has reported so far."""

    # Position (GGA / RMC / GLL)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    geoid_separation_m: Optional[float] = None

    # Fix (GGA / GSA / RMC)
    fix_quality: Optional[str] = None
    fix_type: Optional[str] = None
    status: Optional[str] = None  # A=active, V=void
    satellites_used: Optional[int] = None
    active_prns: List[int] = field(default_factory=list)
    pdop: Optional[float] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    dgps_age_s: Optional[float] = None
    dgps_station: Optional[str] = None

    # Motion (RMC / VTG)
    speed_knots: Optional[float] = None
    speed_kmh: Optional[float] = None
    course_deg: Optional[float] = None
    course_magnetic_deg: Optional[float] = None
    magnetic_variation_deg: Optional[float] = None

    # Time (GGA / RMC / ZDA)
    utc_time: Optional[str] = None
    utc_date: Optional[str] = None

    # Satellites in view (GSV), keyed by constellation
    satellites_in_view: Dict[str, List[Satellite]] = field(default_factory=dict)
    # GSV messages arrive in multi-part groups; build here, publish on last part
    _gsv_partial: Dict[str, List[Satellite]] = field(default_factory=dict)

    # Bookkeeping
    sentences_received: int = 0
    sentences_rejected: int = 0
    last_sentence: Optional[str] = None
    last_update: Optional[float] = None
    raw_log: List[str] = field(default_factory=list)

    MAX_RAW_LOG = 30

    def feed(self, line: str) -> bool:
        """Parse one NMEA line into the state. Returns True if accepted."""
        line = line.strip()
        if not line.startswith("$"):
            return False

        body, star, given_checksum = line[1:].partition("*")
        if star:
            given_checksum = given_checksum.strip()
            try:
                if checksum(body) != int(given_checksum, 16):
                    self.sentences_rejected += 1
                    return False
            except ValueError:
                self.sentences_rejected += 1
                return False

        fields = body.split(",")
        sentence_id = fields[0]
        if len(sentence_id) < 5:
            self.sentences_rejected += 1
            return False
        talker, kind = sentence_id[:2], sentence_id[2:]

        handler = getattr(self, f"_handle_{kind.lower()}", None)
        if handler is None:
            # Unknown sentence type: count and log it, but don't reject —
            # the raw feed still shows everything the chip says.
            self._record(line)
            return True

        handler(talker, fields[1:])
        self._record(line)
        return True

    def _record(self, line: str) -> None:
        self.sentences_received += 1
        self.last_sentence = line
        self.last_update = time.time()
        self.raw_log.append(line)
        if len(self.raw_log) > self.MAX_RAW_LOG:
            del self.raw_log[: -self.MAX_RAW_LOG]

    # --- Sentence handlers -------------------------------------------------

    def _handle_gga(self, talker: str, f: List[str]) -> None:
        f += [""] * (14 - len(f))
        self.utc_time = parse_utc_time(f[0]) or self.utc_time
        self.latitude = parse_latitude(f[1], f[2]) or self.latitude
        self.longitude = parse_longitude(f[3], f[4]) or self.longitude
        if f[5]:
            self.fix_quality = FIX_QUALITIES.get(f[5], f[5])
        self.satellites_used = _int(f[6]) if f[6] else self.satellites_used
        self.hdop = _float(f[7]) if f[7] else self.hdop
        self.altitude_m = _float(f[8]) if f[8] else self.altitude_m
        self.geoid_separation_m = (
            _float(f[10]) if f[10] else self.geoid_separation_m
        )
        self.dgps_age_s = _float(f[12]) if f[12] else self.dgps_age_s
        self.dgps_station = f[13] or self.dgps_station

    def _handle_rmc(self, talker: str, f: List[str]) -> None:
        f += [""] * (11 - len(f))
        self.utc_time = parse_utc_time(f[0]) or self.utc_time
        if f[1]:
            self.status = "Active" if f[1] == "A" else "Void"
        self.latitude = parse_latitude(f[2], f[3]) or self.latitude
        self.longitude = parse_longitude(f[4], f[5]) or self.longitude
        if f[6]:
            self.speed_knots = _float(f[6])
            if self.speed_knots is not None:
                self.speed_kmh = round(self.speed_knots * 1.852, 3)
        if f[7]:
            self.course_deg = _float(f[7])
        self.utc_date = parse_date(f[8]) or self.utc_date
        if f[9]:
            variation = _float(f[9])
            if variation is not None:
                self.magnetic_variation_deg = (
                    -variation if f[10] == "W" else variation
                )

    def _handle_gsa(self, talker: str, f: List[str]) -> None:
        f += [""] * (17 - len(f))
        if f[1]:
            self.fix_type = FIX_TYPES.get(f[1], f[1])
        prns = [_int(p) for p in f[2:14] if p]
        self.active_prns = [p for p in prns if p is not None]
        self.pdop = _float(f[14]) if f[14] else self.pdop
        self.hdop = _float(f[15]) if f[15] else self.hdop
        self.vdop = _float(f[16]) if f[16] else self.vdop

    def _handle_gsv(self, talker: str, f: List[str]) -> None:
        if len(f) < 3:
            return
        total = _int(f[0]) or 1
        number = _int(f[1]) or 1
        system = TALKERS.get(talker, talker)
        if number == 1:
            self._gsv_partial[system] = []
        block = self._gsv_partial.setdefault(system, [])
        sat_fields = f[3:]
        for i in range(0, len(sat_fields) - 3, 4):
            prn = _int(sat_fields[i])
            if prn is None:
                continue
            block.append(
                Satellite(
                    prn=prn,
                    elevation=_int(sat_fields[i + 1]),
                    azimuth=_int(sat_fields[i + 2]),
                    snr=_int(sat_fields[i + 3]),
                    system=system,
                )
            )
        if number >= total:
            self.satellites_in_view[system] = block
            self._gsv_partial.pop(system, None)

    def _handle_vtg(self, talker: str, f: List[str]) -> None:
        f += [""] * (8 - len(f))
        if f[0]:
            self.course_deg = _float(f[0])
        if f[2]:
            self.course_magnetic_deg = _float(f[2])
        if f[4]:
            self.speed_knots = _float(f[4])
        if f[6]:
            self.speed_kmh = _float(f[6])

    def _handle_gll(self, talker: str, f: List[str]) -> None:
        f += [""] * (6 - len(f))
        self.latitude = parse_latitude(f[0], f[1]) or self.latitude
        self.longitude = parse_longitude(f[2], f[3]) or self.longitude
        self.utc_time = parse_utc_time(f[4]) or self.utc_time
        if f[5]:
            self.status = "Active" if f[5] == "A" else "Void"

    def _handle_zda(self, talker: str, f: List[str]) -> None:
        f += [""] * (4 - len(f))
        self.utc_time = parse_utc_time(f[0]) or self.utc_time
        if f[1] and f[2] and f[3]:
            self.utc_date = f"{f[3]}-{f[2]:0>2}-{f[1]:0>2}"

    # --- Serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "position": {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "altitude_m": self.altitude_m,
                "geoid_separation_m": self.geoid_separation_m,
            },
            "fix": {
                "quality": self.fix_quality,
                "type": self.fix_type,
                "status": self.status,
                "satellites_used": self.satellites_used,
                "active_prns": self.active_prns,
                "pdop": self.pdop,
                "hdop": self.hdop,
                "vdop": self.vdop,
                "dgps_age_s": self.dgps_age_s,
                "dgps_station": self.dgps_station,
            },
            "motion": {
                "speed_knots": self.speed_knots,
                "speed_kmh": self.speed_kmh,
                "course_deg": self.course_deg,
                "course_magnetic_deg": self.course_magnetic_deg,
                "magnetic_variation_deg": self.magnetic_variation_deg,
            },
            "time": {
                "utc_time": self.utc_time,
                "utc_date": self.utc_date,
            },
            "satellites_in_view": {
                system: [sat.to_dict() for sat in sats]
                for system, sats in self.satellites_in_view.items()
            },
            "stats": {
                "sentences_received": self.sentences_received,
                "sentences_rejected": self.sentences_rejected,
                "last_update": self.last_update,
                "age_s": (
                    round(time.time() - self.last_update, 1)
                    if self.last_update
                    else None
                ),
            },
            "raw_log": list(self.raw_log),
        }
