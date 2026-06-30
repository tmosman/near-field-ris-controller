"""Decode Teensy mask bytes into a 64×64 RIS phase map (0° / 180°).

Mirrors the MATLAB chain in mm_Wave_NearField_Illum_V1.m:
  codeword_array → process_tile_v3 → packed bytes → Teensy shift registers
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TILE_ROWS = 16
TILE_COLS = 16
TILE_COUNT = 20
TILES_PER_ROW = 5
BYTES_PER_TILE = 64
BITS_PER_TILE = BYTES_PER_TILE * 8
MASK_ROWS = 64
MASK_BIT_COLS = 160
RIS_ROWS = 64
RIS_COLS = 64
STITCH_COLS = 80


@dataclass
class CodebookMetadata:
    ris_rows: int = RIS_ROWS
    ris_cols: int = RIS_COLS
    codeword_grid_rows: int | None = None
    codeword_grid_cols: int | None = None
    dummy_index: int = 0
    index_order: str = "phi_major_theta_minor"
    step_cm: float | None = None

    @property
    def usable_masks(self) -> int | None:
        if self.codeword_grid_rows and self.codeword_grid_cols:
            return self.codeword_grid_rows * self.codeword_grid_cols
        return None

    def to_dict(self) -> dict:
        return {
            "ris_rows": self.ris_rows,
            "ris_cols": self.ris_cols,
            "codeword_grid_rows": self.codeword_grid_rows,
            "codeword_grid_cols": self.codeword_grid_cols,
            "dummy_index": self.dummy_index,
            "index_order": self.index_order,
            "step_cm": self.step_cm,
            "usable_masks": self.usable_masks,
        }


def default_metadata_for_codebook(codebook_id: str, num_masks: int) -> CodebookMetadata:
    usable = num_masks - 1 if num_masks > 1 else num_masks
    side = int(usable**0.5) if usable > 0 and int(usable**0.5) ** 2 == usable else None

    meta = CodebookMetadata(
        codeword_grid_rows=side,
        codeword_grid_cols=side,
        dummy_index=0,
    )

    if "STEP2cm" in codebook_id or "step2cm" in codebook_id.lower():
        meta.step_cm = 2.0

    return meta


def load_metadata(codebook_path: Path, num_masks: int) -> CodebookMetadata:
    meta_path = codebook_path.with_suffix(codebook_path.suffix + ".meta.json")
    if meta_path.exists():
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return CodebookMetadata(
            ris_rows=data.get("ris_rows", RIS_ROWS),
            ris_cols=data.get("ris_cols", RIS_COLS),
            codeword_grid_rows=data.get("codeword_grid_rows"),
            codeword_grid_cols=data.get("codeword_grid_cols"),
            dummy_index=data.get("dummy_index", 0),
            index_order=data.get("index_order", "phi_major_theta_minor"),
            step_cm=data.get("step_cm"),
        )
    return default_metadata_for_codebook(codebook_path.stem, num_masks)


def index_to_codeword_grid(index: int, meta: CodebookMetadata) -> tuple[int | None, int | None]:
    if meta.codeword_grid_cols is None or index == meta.dummy_index:
        return None, None
    k = index - 1 if index > meta.dummy_index else index
    cols = meta.codeword_grid_cols
    return k // cols, k % cols


def _unpack_tile_bytes(tile_bytes: bytes) -> np.ndarray:
    """512 bits per tile, MSB-first within each byte (matches Teensy firmware)."""
    if len(tile_bytes) != BYTES_PER_TILE:
        raise ValueError(f"Expected {BYTES_PER_TILE} bytes per tile, got {len(tile_bytes)}")

    bits = np.zeros(BITS_PER_TILE, dtype=np.uint8)
    pos = 0
    for byte in tile_bytes:
        for bit in range(8):
            bits[pos] = (byte >> (7 - bit)) & 1
            pos += 1
    return bits


def _decode_tile_bits(tile_bits: np.ndarray) -> np.ndarray:
    """Inverse of process_tile_v3 interleave + supercell scan."""
    if tile_bits.size != BITS_PER_TILE:
        raise ValueError(f"Expected {BITS_PER_TILE} tile bits, got {tile_bits.size}")

    # MATLAB: final_bits(2:2:end) = correct_order
    phase_bits = tile_bits[1::2]
    if phase_bits.size != TILE_ROWS * TILE_COLS:
        raise ValueError(f"Expected {TILE_ROWS * TILE_COLS} phase bits, got {phase_bits.size}")

    tile = np.zeros((TILE_ROWS, TILE_COLS), dtype=np.uint8)
    p = 0
    for col in range(0, TILE_COLS, 2):
        for row in range(0, TILE_ROWS, 2):
            tile[row, col] = phase_bits[p]
            tile[row + 1, col] = phase_bits[p + 1]
            tile[row + 1, col + 1] = phase_bits[p + 3]
            tile[row, col + 1] = phase_bits[p + 2]
            p += 4
    return tile


def _split_mask_bytes(mask: bytes) -> list[bytes]:
    if len(mask) % TILE_COUNT != 0:
        raise ValueError(f"Mask length {len(mask)} is not divisible by {TILE_COUNT} tiles")
    chunk = len(mask) // TILE_COUNT
    return [mask[i * chunk : (i + 1) * chunk] for i in range(TILE_COUNT)]


def _stitch_tiles(tiles: list[np.ndarray]) -> np.ndarray:
    """Assemble 20×16×16 tiles into a 64×80 array (MATLAB tile indexing)."""
    grid = np.zeros((MASK_ROWS, STITCH_COLS), dtype=np.uint8)
    for tile_idx, tile in enumerate(tiles):
        row_start = (tile_idx // TILES_PER_ROW) * TILE_ROWS
        col_start = (tile_idx % TILES_PER_ROW) * TILE_COLS
        grid[row_start : row_start + TILE_ROWS, col_start : col_start + TILE_COLS] = tile
    return grid


def decode_mask_to_ris(mask: bytes, ris_rows: int = RIS_ROWS, ris_cols: int = RIS_COLS) -> np.ndarray:
    """Return 64×64 phase map: 0 → 0°, 1 → 180°."""
    tile_chunks = _split_mask_bytes(mask)
    tiles = [_decode_tile_bits(_unpack_tile_bytes(chunk)) for chunk in tile_chunks]
    stitched = _stitch_tiles(tiles)
    return stitched[:ris_rows, :ris_cols].copy()


def decode_mask_to_ris_list(mask: bytes, ris_rows: int = RIS_ROWS, ris_cols: int = RIS_COLS) -> list[list[int]]:
    array = decode_mask_to_ris(mask, ris_rows=ris_rows, ris_cols=ris_cols)
    return array.astype(int).tolist()


def summarize_mask(
    mask: bytes,
    index: int,
    meta: CodebookMetadata,
) -> dict:
    phases = decode_mask_to_ris(mask, ris_rows=meta.ris_rows, ris_cols=meta.ris_cols)
    grid_row, grid_col = index_to_codeword_grid(index, meta)
    active_180 = int(phases.sum())
    total = meta.ris_rows * meta.ris_cols

    return {
        "index": index,
        "ris_rows": meta.ris_rows,
        "ris_cols": meta.ris_cols,
        "phases": phases.astype(int).tolist(),
        "active_180deg_count": active_180,
        "active_0deg_count": total - active_180,
        "codeword_grid_row": grid_row,
        "codeword_grid_col": grid_col,
        "codeword_grid_rows": meta.codeword_grid_rows,
        "codeword_grid_cols": meta.codeword_grid_cols,
        "step_cm": meta.step_cm,
        "is_dummy": index == meta.dummy_index,
    }
