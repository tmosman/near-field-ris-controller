#!/usr/bin/env python3
"""Create a small demo codebook for server/GUI testing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.codebook_format import write_codebook  # noqa: E402


def main() -> int:
    num_masks = 729
    mask_bytes = 1280
    masks = []
    for index in range(num_masks):
        mask = bytearray(mask_bytes)
        for i in range(mask_bytes):
            mask[i] = (index + i) % 256
        masks.append(bytes(mask))

    output = ROOT / "codebooks" / "demo_27x27.cbk"
    output.parent.mkdir(parents=True, exist_ok=True)
    header = write_codebook(output, "demo_27x27", masks)
    print(f"Wrote {output} ({header.num_masks} masks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
