#!/usr/bin/env python3
"""Example: sweep beam indices via the RIS server (no direct serial)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from client.ris_client import RisClient, RisClientError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep RIS beam indices through the server API")
    parser.add_argument(
        "--server",
        default=os.getenv("RIS_SERVER_URL", "http://localhost:8080"),
        help="RIS server base URL",
    )
    parser.add_argument(
        "--codebook",
        default="Imaging_M260P260M520P0_STEP2cm",
        help="Codebook id (filename without .cbk)",
    )
    parser.add_argument("--start", type=int, default=1, help="First beam index")
    parser.add_argument("--end", type=int, default=10, help="Last beam index (inclusive)")
    parser.add_argument("--dwell-ms", type=int, default=100, help="Delay between beams")
    parser.add_argument("--force-upload", action="store_true", help="Re-upload codebook to Teensy")
    args = parser.parse_args()

    client = RisClient(args.server)
    try:
        status = client.status()
        print(f"Server OK | teensy_connected={status['teensy_connected']} | mock={status['teensy_mock']}")

        result = client.ensure_codebook(args.codebook, force_upload=args.force_upload)
        print(f"Codebook '{args.codebook}' ready (uploaded={result['uploaded']})")

        for index in range(args.start, args.end + 1):
            applied = client.apply_beam(index)
            print(f"Applied beam {applied['index']}")
            if args.dwell_ms > 0:
                time.sleep(args.dwell_ms / 1000.0)

    except RisClientError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
