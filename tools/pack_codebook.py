#!/usr/bin/env python3
"""Pack raw mask files or a single binary blob into a .cbk codebook."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.codebook_format import write_codebook  # noqa: E402


def load_masks_from_directory(mask_dir: Path) -> list[bytes]:
    files = sorted(mask_dir.glob("mask_*.bin"))
    if not files:
        files = sorted(mask_dir.glob("*.bin"))
    if not files:
        raise FileNotFoundError(f"No mask .bin files found in {mask_dir}")
    return [path.read_bytes() for path in files]


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack masks into a RIS .cbk codebook")
    parser.add_argument("--name", required=True, help="Codebook name stored in header")
    parser.add_argument("--output", "-o", required=True, type=Path, help="Output .cbk path")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mask-dir", type=Path, help="Directory of mask_*.bin files")
    group.add_argument("--raw-payload", type=Path, help="Concatenated raw mask bytes")
    parser.add_argument("--num-masks", type=int, help="Required with --raw-payload")
    parser.add_argument("--mask-bytes", type=int, default=1280, help="Bytes per mask")
    args = parser.parse_args()

    if args.mask_dir:
        masks = load_masks_from_directory(args.mask_dir)
    else:
        if args.num_masks is None:
            parser.error("--num-masks is required with --raw-payload")
        payload = args.raw_payload.read_bytes()
        expected = args.num_masks * args.mask_bytes
        if len(payload) != expected:
            raise ValueError(f"Expected {expected} bytes, got {len(payload)}")
        masks = [
            payload[i : i + args.mask_bytes]
            for i in range(0, expected, args.mask_bytes)
        ]

    header = write_codebook(args.output, args.name, masks)
    print(
        f"Wrote {args.output} "
        f"(masks={header.num_masks}, mask_bytes={header.mask_bytes}, crc={header.payload_crc32:08x})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
