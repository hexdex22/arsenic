# GPS Live Data Display

A small asyncio app that reads everything a GPS chip reports over its
NMEA 0183 serial interface and **continuously displays all of it** — in a
live web dashboard, in the terminal, or both.

It shows every field consumer GPS chips emit:

- **Position** — latitude/longitude (decimal and DMS), altitude, geoid separation
- **Fix** — status, fix quality (GPS/DGPS/RTK/…), 2D/3D mode, satellites used
  and their PRNs, PDOP/HDOP/VDOP, DGPS age and station
- **Motion** — speed (knots and km/h), true and magnetic course, magnetic variation
- **Time** — UTC time and date straight from the satellites
- **Satellites in view** — per-satellite PRN, elevation, azimuth and SNR,
  grouped by constellation (GPS, GLONASS, Galileo, BeiDou, QZSS)
- **Raw NMEA feed** — the exact sentences arriving from the chip, live

No third-party packages required — pure Python ≥ 3.8 standard library.
(`pyserial` is used automatically *if* installed, to set the baud rate.)

## Run it with a real GPS chip

Plug in the receiver (USB GPS dongle, u-blox/MTK module on a Raspberry Pi
UART, etc.) and point the app at its serial device:

```bash
python -m gps_display_app --device /dev/ttyUSB0 --baud 9600
```

Then open **http://localhost:8000/** — the dashboard updates continuously
via a server-sent-event stream.

Common devices: `/dev/ttyUSB0` (USB dongles), `/dev/ttyACM0` (u-blox USB),
`/dev/serial0` or `/dev/ttyAMA0` (Raspberry Pi UART header).

If `pyserial` is not installed, configure the port first and the app will
read it as a plain file:

```bash
stty -F /dev/ttyUSB0 9600 raw
python -m gps_display_app --device /dev/ttyUSB0
```

## Run it without hardware

```bash
python -m gps_display_app --simulate
```

A built-in simulator produces a realistic, checksummed NMEA stream
(a receiver circling Tokyo Station) so you can try the full display.

You can also replay a recorded NMEA log:

```bash
python -m gps_display_app --file drive.nmea
```

## Terminal display

```bash
python -m gps_display_app --device /dev/ttyUSB0 --mode console
```

`--mode both` runs the web dashboard and the terminal view together.

## Options

```
--device PATH    serial device of the GPS chip (e.g. /dev/ttyUSB0)
--baud N         serial baud rate (default 9600)
--file PATH      replay a recorded NMEA log instead
--simulate       use the built-in simulator
--mode M         web | console | both (default web)
--host H         web bind address (default 0.0.0.0)
--port N         web port (default 8000)
--refresh HZ     display refresh rate (default 2)
```

## Phone app

`phone/` contains a companion app for phones that reads the **phone's own
GPS chip** through the browser geolocation API and continuously displays
everything it reports: position (decimal + DMS), accuracy radius, altitude
and altitude accuracy, speed, heading, fix timestamp and age, plus a
rolling fix log, a map link, and a keep-screen-on toggle.

It is a PWA — served over HTTPS it can be installed from the browser menu
("Add to Home Screen" / "Install app") and then opens full-screen like a
native app, working offline. Hosting options:

- Enable **GitHub Pages** for this repo and open
  `.../gps_display_app/phone/` on the phone, or
- copy the three files in `phone/` to any static HTTPS host.

Geolocation requires a secure context, so plain `http://` (other than
localhost) won't work. Browsers expose position/motion data only — per-
satellite SNR needs a native app and is shown by the main dashboard when
you use a real GPS chip over serial.

## Native Android app (Kotlin)

`android/` contains a native Kotlin app that shows everything the phone's
GPS chip reports — including per-satellite constellation/id/C\/N0/elevation/
azimuth and the raw NMEA stream, which browsers don't expose. A GitHub
Actions workflow builds the installable APK on every push; see
[`android/README.md`](android/README.md).

## Endpoints

- `/` — live dashboard
- `/events` — server-sent-event stream of the full GPS state (JSON)
- `/state.json` — one-shot JSON snapshot, handy for scripting
