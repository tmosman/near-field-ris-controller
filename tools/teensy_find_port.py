#!/usr/bin/env python3
"""Find which ttyACM port responds to ris_controller PING."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read_line(ser, timeout_s: float) -> str:
    deadline = time.time() + timeout_s
    buf = bytearray()
    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            buf.extend(ser.read(waiting))
            if b"\n" in buf:
                line, _ = buf.split(b"\n", 1)
                return line.decode("utf-8", errors="replace").strip()
        time.sleep(0.02)
    if buf:
        return buf.decode("utf-8", errors="replace").strip()
    return ""


def _collect_boot_lines(ser, max_wait_s: float = 5.0) -> list[str]:
    lines: list[str] = []
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        line = _read_line(ser, timeout_s=0.4)
        if not line:
            if lines:
                break
            continue
        lines.append(line)
        if line == "OK BOOT":
            break
    return lines


def try_port(port: str, baud: int, wait_s: float) -> tuple[bool, str, str, list[str]]:
    import serial

    try:
        ser = serial.Serial(port, baud, timeout=0.3, write_timeout=2.0, exclusive=True)
    except serial.SerialException as exc:
        return False, "", f"open failed: {exc}", []

    try:
        ser.dtr = False
        ser.rts = False
        time.sleep(wait_s)

        boot_lines = _collect_boot_lines(ser, max_wait_s=2.0)

        pong = ""
        for attempt in range(8):
            while ser.in_waiting:
                ser.read(ser.in_waiting)
            ser.write(b"PING\n")
            ser.flush()
            time.sleep(0.08)
            pong = _read_line(ser, timeout_s=2.0)
            if pong == "PONG":
                break
            time.sleep(0.25)

        if pong != "PONG":
            detail = "no response" if not pong else f"got {pong!r}"
            return False, pong, detail, boot_lines

        ser.write(b"STATUS\n")
        ser.flush()
        time.sleep(0.08)
        status = _read_line(ser, timeout_s=3.0)
        return True, pong, status, boot_lines
    finally:
        ser.close()


def list_candidate_ports(explicit: list[str] | None) -> list[str]:
    if explicit:
        return explicit
    ports: list[str] = []
    for pattern in ("ttyACM*", "ttyUSB*"):
        ports.extend(str(p) for p in sorted(Path("/dev").glob(pattern)))
    return ports


def port_holder_hint(port: str) -> str | None:
    try:
        out = subprocess.run(
            ["fuser", "-v", port],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        text = (out.stdout + out.stderr).strip()
        return text or None
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan serial ports for ris_controller Teensy")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--wait", type=float, default=4.0, help="Seconds after open for Teensy boot")
    parser.add_argument("--port", action="append", help="Only test this port (repeatable)")
    args = parser.parse_args()

    ports = list_candidate_ports(args.port)
    if not ports:
        print("No /dev/ttyACM* or /dev/ttyUSB* devices found.")
        print("Unplug/replug the Teensy USB cable, then run: dmesg | tail -20")
        return 1

    print("Close Arduino Serial Monitor and stop run_server.py before scanning.\n")
    print(f"Testing {len(ports)} port(s) @ {args.baud} baud (wait {args.wait}s)…\n")

    found = False
    for port in ports:
        print(f"--- {port} ---")
        holder = port_holder_hint(port)
        if holder:
            print(f"  (port in use: {holder})")

        ok, ping, extra, boot = try_port(port, args.baud, args.wait)
        if boot:
            print("  boot:")
            for line in boot:
                print(f"    {line}")

        if ok:
            found = True
            print(f"  PING -> {ping!r}")
            print(f"  STATUS -> {extra!r}")
            print("  ** USE THIS PORT **")
        else:
            print(f"  no PONG ({extra})")
            if ping and ping != "PONG":
                print(f"  raw: {ping!r}")
        print()

    if found:
        print("Set before starting server:")
        print("  export RIS_TEENSY_PORT=<port above>")
        return 0

    print("No ris_controller Teensy found.")
    print()
    print("Troubleshooting:")
    print("  1. Stop server:  pkill -f run_server.py   (or Ctrl+C)")
    print("  2. Close Arduino Serial Monitor")
    print("  3. Press the Teensy PROGRAM button once, wait 2s, re-run this script")
    print("  4. Unplug USB, replug, run:  dmesg | tail -15")
    print("  5. In Arduino IDE: Tools -> Port — confirm device name (Teensy 4.1)")
    print("  6. Serial Monitor @ 921600: type PING — should see PONG")
    print("  7. If PONG in Monitor but not here: fuser -v /dev/ttyACM0")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
