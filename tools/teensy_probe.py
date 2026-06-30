#!/usr/bin/env python3
"""Probe Teensy serial connectivity (run with server stopped)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _open_serial(port: str, baud: int, *, reset_on_open: bool):
    import serial

    # exclusive=True fails fast if Arduino Serial Monitor holds the port.
    s = serial.Serial(port, baud, timeout=0.3, write_timeout=2.0, exclusive=True)
    s.dtr = False
    s.rts = False

    if reset_on_open:
        # Opening ttyACM already rebooted Teensy; wait for setup() to finish.
        time.sleep(3.5)
    else:
        # Port open may still reboot Teensy once; allow boot either way.
        time.sleep(3.5)
    return s


def _drain(s, max_wait_s: float = 0.3) -> None:
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        waiting = s.in_waiting
        if waiting:
            s.read(waiting)
            deadline = time.time() + max_wait_s
            continue
        time.sleep(0.02)


def _read_line(s, timeout_s: float = 3.0) -> str:
    deadline = time.time() + timeout_s
    buf = bytearray()
    while time.time() < deadline:
        chunk = s.read(max(1, s.in_waiting))
        if chunk:
            buf.extend(chunk)
            if b"\n" in buf:
                line, _rest = buf.split(b"\n", 1)
                return line.decode("utf-8", errors="replace").strip()
            deadline = time.time() + timeout_s
            continue
        time.sleep(0.02)
    if buf:
        return buf.decode("utf-8", errors="replace").strip()
    return ""


def _collect_boot_lines(s, max_wait_s: float = 4.0) -> list[str]:
    lines: list[str] = []
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        line = _read_line(s, timeout_s=0.5)
        if not line:
            if lines:
                break
            continue
        lines.append(line)
        if line in {"OK BOOT", "OK RIS_FW=3", "OK RAM_STORE", "WARN NO_CODEBOOK_LOADED"}:
            break
    return lines


def _command(s, command: str, *, timeout_s: float = 3.0) -> str:
    _drain(s, max_wait_s=0.15)
    s.write((command + "\n").encode("utf-8"))
    s.flush()
    time.sleep(0.05)
    return _read_line(s, timeout_s=timeout_s)


def probe(port: str, baud: int, *, reset: bool, debug: bool) -> int:
    import serial

    print(f"Probing {port} @ {baud} …")
    print("1) Open port (close Arduino Serial Monitor first) …")

    try:
        s = _open_serial(port, baud, reset_on_open=reset)
    except serial.SerialException as exc:
        print(f"ERROR: could not open {port}: {exc}")
        if "busy" in str(exc).lower() or "permission" in str(exc).lower():
            print("       Close Arduino Serial Monitor / other apps using this port.")
        return 2

    print("2) Boot lines:")
    boot_lines = _collect_boot_lines(s)
    if boot_lines:
        for line in boot_lines:
            print(f"   {line}")
    else:
        print("   (none — Teensy may have booted before we connected; continuing)")

    print("3) PING …")
    pong = ""
    for attempt in range(6):
        pong = _command(s, "PING", timeout_s=2.0)
        if debug:
            print(f"   attempt {attempt + 1}: in_waiting={s.in_waiting} line={pong!r}")
        if pong == "PONG":
            break
        if not debug:
            if pong:
                print(f"   attempt {attempt + 1}: {pong!r}")
            else:
                print(f"   attempt {attempt + 1}: (no response)")
        time.sleep(0.2)
    if not debug:
        print(f"   -> {pong!r}")

    print("4) STATUS …")
    status = _command(s, "STATUS", timeout_s=3.0)
    print(f"   -> {status!r}")

    s.close()

    if pong == "PONG" and status.startswith("OK store="):
        print("OK: Teensy responding")
        return 0

    if pong == "PONG":
        print("OK: PING works (STATUS line unexpected — paste output above)")
        return 0

    print("FAIL: no PONG")
    print("Hints:")
    print("  - Close Arduino Serial Monitor, then run: python tools/teensy_find_port.py")
    print("  - In Arduino IDE: Tools → Port — use THAT exact device for RIS_TEENSY_PORT")
    print("  - ACM0 vs ACM1: wrong port gives silence; Arduino working means firmware is OK")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Teensy USB serial")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Legacy flag (boot wait is always applied after open)",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose read diagnostics")
    args = parser.parse_args()
    try:
        return probe(args.port, args.baud, reset=not args.no_reset, debug=args.debug)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
