"""RIS codebook binary format (.cbk)."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"RISCBK01"
HEADER_FMT = "<8sII64sII24s"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
NAME_FIELD_BYTES = 64


@dataclass
class CodebookHeader:
    name: str
    num_masks: int
    mask_bytes: int
    payload_crc32: int

    @property
    def payload_size(self) -> int:
        return self.num_masks * self.mask_bytes


def crc32_bytes(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def pack_header(name: str, num_masks: int, mask_bytes: int, payload_crc32: int) -> bytes:
    name_bytes = name.encode("utf-8")[: NAME_FIELD_BYTES - 1]
    name_padded = name_bytes.ljust(NAME_FIELD_BYTES, b"\x00")
    reserved = b"\x00" * 24
    return struct.pack(
        HEADER_FMT,
        MAGIC,
        num_masks,
        mask_bytes,
        name_padded,
        payload_crc32,
        0,
        reserved,
    )


def parse_header(data: bytes) -> CodebookHeader:
    if len(data) < HEADER_SIZE:
        raise ValueError("Header too short")
    magic, num_masks, mask_bytes, name_raw, payload_crc32, _, _ = struct.unpack(
        HEADER_FMT, data[:HEADER_SIZE]
    )
    if magic != MAGIC:
        raise ValueError(f"Invalid magic: {magic!r}")
    name = name_raw.split(b"\x00", 1)[0].decode("utf-8")
    return CodebookHeader(
        name=name,
        num_masks=num_masks,
        mask_bytes=mask_bytes,
        payload_crc32=payload_crc32,
    )


def read_codebook(path: Path) -> tuple[CodebookHeader, bytes]:
    raw = path.read_bytes()
    header = parse_header(raw)
    payload = raw[HEADER_SIZE : HEADER_SIZE + header.payload_size]
    if len(payload) != header.payload_size:
        raise ValueError("Truncated payload")
    if crc32_bytes(payload) != header.payload_crc32:
        raise ValueError("Payload CRC mismatch")
    return header, payload


def write_codebook(path: Path, name: str, masks: list[bytes]) -> CodebookHeader:
    if not masks:
        raise ValueError("At least one mask required")
    mask_bytes = len(masks[0])
    if any(len(m) != mask_bytes for m in masks):
        raise ValueError("All masks must have the same byte length")
    payload = b"".join(masks)
    header = CodebookHeader(
        name=name,
        num_masks=len(masks),
        mask_bytes=mask_bytes,
        payload_crc32=crc32_bytes(payload),
    )
    path.write_bytes(pack_header(header.name, header.num_masks, header.mask_bytes, header.payload_crc32) + payload)
    return header


def extract_mask(payload: bytes, header: CodebookHeader, index: int) -> bytes:
    if index < 0 or index >= header.num_masks:
        raise IndexError(f"Mask index {index} out of range 0..{header.num_masks - 1}")
    start = index * header.mask_bytes
    end = start + header.mask_bytes
    return payload[start:end]


def mask_to_bitplanes(mask: bytes, tiles: int = 20) -> list[list[int]]:
    """Decode mask bytes into per-tile bit lists (MSB-first within each byte)."""
    bytes_per_tile = len(mask) // tiles
    planes: list[list[int]] = []
    for tile in range(tiles):
        bits: list[int] = []
        offset = tile * bytes_per_tile
        for byte_index in range(bytes_per_tile):
            value = mask[offset + byte_index]
            for bit in range(8):
                bits.append((value >> (7 - bit)) & 1)
        planes.append(bits)
    return planes


def grid_side(num_masks: int) -> int | None:
    root = int(num_masks**0.5)
    if root * root == num_masks:
        return root
    return None
