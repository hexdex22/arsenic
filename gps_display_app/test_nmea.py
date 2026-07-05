"""Tests for the NMEA parser. Run with: python -m pytest gps_display_app/"""

from gps_display_app.nmea import GPSState, checksum, make_sentence


def test_checksum_roundtrip():
    sentence = make_sentence("GPGLL,4916.45,N,12311.12,W,225444,A")
    body = sentence[1:].split("*")[0]
    assert sentence.endswith(f"*{checksum(body):02X}")


def test_bad_checksum_rejected():
    state = GPSState()
    assert not state.feed("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00")
    assert state.sentences_rejected == 1
    assert state.latitude is None


def test_gga():
    state = GPSState()
    assert state.feed(
        make_sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,")
    )
    assert state.utc_time == "12:35:19"
    assert round(state.latitude, 4) == 48.1173
    assert round(state.longitude, 4) == 11.5167
    assert state.fix_quality == "GPS fix"
    assert state.satellites_used == 8
    assert state.hdop == 0.9
    assert state.altitude_m == 545.4
    assert state.geoid_separation_m == 46.9


def test_rmc():
    state = GPSState()
    assert state.feed(
        make_sentence("GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W")
    )
    assert state.status == "Active"
    assert state.speed_knots == 22.4
    assert state.speed_kmh == round(22.4 * 1.852, 3)
    assert state.course_deg == 84.4
    assert state.utc_date == "2094-03-23"
    assert state.magnetic_variation_deg == -3.1


def test_gsa():
    state = GPSState()
    assert state.feed(make_sentence("GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1"))
    assert state.fix_type == "3D"
    assert state.active_prns == [4, 5, 9, 12, 24]
    assert (state.pdop, state.hdop, state.vdop) == (2.5, 1.3, 2.1)


def test_gsv_multipart():
    state = GPSState()
    state.feed(make_sentence("GPGSV,2,1,07,02,74,158,42,04,44,088,45,05,15,300,38,09,60,220,41"))
    # not published until the last message of the group arrives
    assert "GPS" not in state.satellites_in_view
    state.feed(make_sentence("GPGSV,2,2,07,12,30,047,39,24,10,120,,25,05,015,20"))
    sats = state.satellites_in_view["GPS"]
    assert len(sats) == 7
    assert sats[0].prn == 2 and sats[0].snr == 42
    assert sats[5].snr is None  # empty SNR field preserved as unknown


def test_gsv_multiple_constellations():
    state = GPSState()
    state.feed(make_sentence("GPGSV,1,1,02,02,74,158,42,04,44,088,45"))
    state.feed(make_sentence("GLGSV,1,1,01,70,30,100,33"))
    assert len(state.satellites_in_view["GPS"]) == 2
    assert state.satellites_in_view["GLONASS"][0].system == "GLONASS"


def test_vtg():
    state = GPSState()
    assert state.feed(make_sentence("GPVTG,054.7,T,034.4,M,005.5,N,010.2,K"))
    assert state.course_deg == 54.7
    assert state.course_magnetic_deg == 34.4
    assert state.speed_knots == 5.5
    assert state.speed_kmh == 10.2


def test_gll_and_zda():
    state = GPSState()
    assert state.feed(make_sentence("GPGLL,4916.45,N,12311.12,W,225444,A"))
    assert round(state.latitude, 4) == 49.2742
    assert round(state.longitude, 4) == -123.1853
    assert state.feed(make_sentence("GPZDA,201530.00,04,07,2026,00,00"))
    assert state.utc_date == "2026-07-04"
    assert state.utc_time == "20:15:30.00"


def test_unknown_sentence_kept_in_raw_log():
    state = GPSState()
    assert state.feed(make_sentence("PMTK001,314,3"))
    assert state.sentences_received == 1
    assert state.raw_log[-1].startswith("$PMTK001")


def test_garbage_ignored():
    state = GPSState()
    assert not state.feed("not nmea at all")
    assert not state.feed("")
    assert state.sentences_received == 0


def test_simulator_stream_parses():
    import asyncio

    from gps_display_app.sources import simulator_lines

    async def collect():
        state = GPSState()
        gen = simulator_lines(interval=0)
        for _ in range(30):
            state.feed(await gen.__anext__())
        return state

    state = asyncio.run(collect())
    assert state.sentences_rejected == 0
    assert state.latitude and state.longitude
    assert state.fix_type == "3D"
    assert state.satellites_in_view["GPS"]
    assert state.speed_kmh
