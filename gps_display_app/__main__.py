"""Continuously display all data from a GPS chip.

Usage:
    python -m gps_display_app --device /dev/ttyUSB0 --baud 9600
    python -m gps_display_app --simulate
    python -m gps_display_app --file recording.nmea --mode console
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from typing import AsyncIterator

from .console import run_console
from .nmea import GPSState
from .sources import file_lines, serial_lines, simulator_lines
from .web import WebDisplay


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gps_display_app",
        description="Continuously display all data from a GPS chip "
        "(NMEA 0183 over serial).",
    )
    source = parser.add_argument_group("data source")
    source.add_argument(
        "--device",
        help="serial device the GPS chip is attached to, e.g. /dev/ttyUSB0, "
        "/dev/ttyAMA0 or /dev/serial0",
    )
    source.add_argument(
        "--baud", type=int, default=9600,
        help="serial baud rate (default: 9600, the NMEA standard)",
    )
    source.add_argument("--file", help="replay a recorded NMEA log file instead")
    source.add_argument(
        "--simulate", action="store_true",
        help="use the built-in GPS simulator (no hardware needed)",
    )
    display = parser.add_argument_group("display")
    display.add_argument(
        "--mode", choices=["web", "console", "both"], default="web",
        help="how to display the data (default: web)",
    )
    display.add_argument("--host", default="0.0.0.0", help="web server bind host")
    display.add_argument("--port", type=int, default=8000, help="web server port")
    display.add_argument(
        "--refresh", type=float, default=2.0,
        help="display refresh rate in Hz (default: 2)",
    )
    return parser


def pick_source(args: argparse.Namespace) -> AsyncIterator[str]:
    if args.device:
        return serial_lines(args.device, args.baud)
    if args.file:
        return file_lines(args.file)
    if not args.simulate:
        print(
            "No --device or --file given; using the built-in simulator.\n"
            "Attach your GPS chip and pass e.g. --device /dev/ttyUSB0.\n",
            file=sys.stderr,
        )
    return simulator_lines()


async def read_into_state(source: AsyncIterator[str], state: GPSState) -> None:
    async for line in source:
        state.feed(line)


async def main() -> None:
    args = build_parser().parse_args()
    state = GPSState()

    tasks = [asyncio.ensure_future(read_into_state(pick_source(args), state))]
    if args.mode in ("web", "both"):
        tasks.append(
            asyncio.ensure_future(
                WebDisplay(state, args.host, args.port, args.refresh).run()
            )
        )
    if args.mode in ("console", "both"):
        tasks.append(asyncio.ensure_future(run_console(state, args.refresh)))

    try:
        # If any task dies (e.g. the serial device disappears), surface it.
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION
        )
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
