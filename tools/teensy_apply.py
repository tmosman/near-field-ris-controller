#!/usr/bin/env python3
"""Apply a beam index on Teensy over serial (no server required)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.teensy_serial_util import drain, read_line, wait_for_apply_responses  # noqa: E402


def command(ser, line: str, timeout_s: float = 5.0) -> str:
    drain(ser)
    ser.write((line + "\n").encode("utf-8"))
    ser.flush()
    time.sleep(0.05)
    return read_line(ser, timeout_s)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply beam index on Teensy (direct serial)")
    parser.add_argument("--index", "-i", type=int, help="Beam / codeword index to apply")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--wait", type=float, default=0.5, help="Delay after open before commands (s)")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Return after OK APPLY_QUEUED (do not wait for OK APPLIED)",
    )
    parser.add_argument("--legacy", action="store_true", help="Send plain index only (e.g. 42)")
    parser.add_argument("--ping", action="store_true", help="PING only, then exit")
    parser.add_argument("--status", action="store_true", help="STATUS only, then exit")
    parser.add_argument("--clear", action="store_true", help="CLEAR shift registers, then exit")
    args = parser.parse_args()

    if not any([args.ping, args.status, args.clear, args.index is not None]):
        parser.error("provide --index, or one of --ping / --status / --clear")

    import serial

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.3, write_timeout=5.0, exclusive=True)
    except serial.SerialException as exc:
        print(f"ERROR: could not open {args.port}: {exc}")
        print("Close Arduino Serial Monitor and run_server.py first.")
        return 2

    ser.dtr = False
    ser.rts = False
    time.sleep(args.wait)

    try:
        if args.ping:
            line = command(ser, "PING")
            print(line)
            return 0 if line == "PONG" else 1

        if args.status:
            line = command(ser, "STATUS", timeout_s=5.0)
            print(line)
            return 0 if line.startswith("OK store=") else 1

        if args.clear:
            line = command(ser, "CLEAR")
            print(line)
            return 0 if line == "OK CLEARED" else 1

        assert args.index is not None
        cmd = str(args.index) if args.legacy else f"APPLY {args.index}"
        print(f"Sending: {cmd}")

        drain(ser)
        ser.write((cmd + "\n").encode("utf-8"))
        ser.flush()

        ok, lines = wait_for_apply_responses(ser, timeout_s=60.0)
        for line in lines:
            print(line)

        if args.fast:
            return 0 if any(l == "OK APPLY_QUEUED" for l in lines) else 1

        if ok:
            return 0
        if any(l.startswith("ERR") for l in lines):
            return 1
        if any(l == "OK APPLY_QUEUED" for l in lines) and not any(l.startswith("OK APPLIED ") for l in lines):
            print("NOTE: beam may have switched; OK APPLIED was not seen on serial (try again)")
        print("FAIL: no OK APPLIED")
        return 1
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
