#!/usr/bin/env python3
"""Upload a .cbk codebook to Teensy over serial (no server required)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.codebook_format import read_codebook  # noqa: E402
from tools.teensy_serial_util import read_line, wait_for_apply_responses  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload .cbk to Teensy")
    parser.add_argument("cbk", type=Path, help="Path to .cbk file")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--chunk", type=int, default=4096)
    parser.add_argument("--wait", type=float, default=3.5, help="Boot wait after open (s)")
    parser.add_argument(
        "--apply",
        type=int,
        metavar="INDEX",
        help="Apply beam index after upload (same session; RAM codebook lost if port closes)",
    )
    args = parser.parse_args()

    if not args.cbk.is_file():
        print(f"ERROR: file not found: {args.cbk}")
        return 1

    header, payload = read_codebook(args.cbk)
    print(
        f"Codebook: {header.name} masks={header.num_masks} "
        f"bytes/mask={header.mask_bytes} payload={len(payload)} crc={header.payload_crc32:08x}"
    )

    import serial

    print(f"Opening {args.port} @ {args.baud} …")
    ser = serial.Serial(args.port, args.baud, timeout=0.3, write_timeout=10.0)
    ser.dtr = False
    time.sleep(args.wait)
    ser.reset_input_buffer()

    print("PING …")
    ser.write(b"PING\n")
    ser.flush()
    time.sleep(0.1)
    pong = read_line(ser, 3.0)
    print(f"  -> {pong!r}")
    if pong != "PONG":
        print("FAIL: Teensy not responding. Close Serial Monitor / server, check port.")
        ser.close()
        return 1

    command = (
        f"CODEBOOK_BEGIN {header.name} {header.num_masks} "
        f"{header.mask_bytes} {header.payload_crc32:08x}\n"
    )
    print(f"Sending: {command.strip()}")
    ser.write(command.encode("utf-8"))
    ser.flush()
    time.sleep(0.1)
    ready = read_line(ser, 10.0)
    print(f"  -> {ready!r}")
    if ready != "READY":
        print("FAIL: expected READY")
        ser.close()
        return 1

    print(f"Uploading {len(payload)} bytes …")
    offset = 0
    while offset < len(payload):
        chunk = payload[offset : offset + args.chunk]
        ser.write(chunk)
        ser.flush()
        offset += len(chunk)
        if offset % (args.chunk * 4) == 0 or offset == len(payload):
            print(f"  {offset}/{len(payload)}")

    verified = read_line(ser, 30.0)
    print(f"  -> {verified!r}")
    if verified != "OK VERIFIED":
        print("FAIL: upload not verified")
        ser.close()
        return 1

    ser.write(b"STATUS\n")
    ser.flush()
    time.sleep(0.1)
    status = read_line(ser, 5.0)
    print(f"STATUS -> {status!r}")

    if args.apply is not None:
        cmd = f"APPLY {args.apply}\n"
        print(f"Sending: {cmd.strip()}")
        ser.write(cmd.encode("utf-8"))
        ser.flush()
        ok, lines = wait_for_apply_responses(ser, timeout_s=60.0)
        for line in lines:
            print(f"  -> {line!r}")
        if not ok:
            ser.close()
            return 1

    ser.close()
    print("OK: codebook uploaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
