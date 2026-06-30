#!/usr/bin/env python3
"""Extract bitList payload from a legacy embedded .ino sketch into .cbk format."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.codebook_format import write_codebook  # noqa: E402

BYTE_PATTERN = re.compile(r"0b[01]{8}")


def parse_ino_masks(ino_path: Path) -> list[bytes]:
    text = ino_path.read_text(encoding="utf-8", errors="ignore")
    mask_blocks = re.split(r"//Mask\s+[^\n]+\n", text)
    if len(mask_blocks) < 2:
        raise ValueError("Could not find //Mask sections in .ino file")

    masks: list[bytes] = []
    for block in mask_blocks[1:]:
        tokens = BYTE_PATTERN.findall(block.split("};", 1)[0])
        if not tokens:
            continue
        values = [int(token, 2) for token in tokens]
        masks.append(bytes(values))

    if not masks:
        raise ValueError("No mask byte arrays found")
    return masks


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract legacy .ino bitList into .cbk")
    parser.add_argument("ino", type=Path, help="Path to legacy Imaging_*.ino")
    parser.add_argument("--name", help="Codebook name (default: ino stem)")
    parser.add_argument("--output", "-o", type=Path, help="Output .cbk path")
    args = parser.parse_args()

    masks = parse_ino_masks(args.ino)
    name = args.name or args.ino.stem
    output = args.output or args.ino.with_suffix(".cbk")

    header = write_codebook(output, name, masks)
    print(
        f"Extracted {len(masks)} masks from {args.ino.name} -> {output} "
        f"(mask_bytes={header.mask_bytes}, crc={header.payload_crc32:08x})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
