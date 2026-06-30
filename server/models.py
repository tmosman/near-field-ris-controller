from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class CodebookInfo:
    id: str
    name: str
    num_masks: int
    mask_bytes: int
    payload_crc32: str
    path: str
    on_teensy: bool = False


@dataclass
class SystemStatus:
    teensy_connected: bool
    teensy_mock: bool
    teensy_port: str | None
    active_codebook_id: str | None
    active_codebook_name: str | None
    teensy_masks: int
    teensy_mask_bytes: int
    teensy_crc: str | None
    last_applied_index: int | None


@dataclass
class MaskVisualization:
    index: int
    mask_bytes: int
    tiles: int
    bits_per_tile: int
    bitplanes: list[list[int]]
    grid_side: int | None
    grid_row: int | None
    grid_col: int | None


def to_json(obj) -> dict:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj
