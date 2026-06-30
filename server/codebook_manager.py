from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from shared.codebook_format import (
    HEADER_SIZE,
    CodebookHeader,
    parse_header,
    read_codebook,
)
from shared.mask_decode import CodebookMetadata, load_metadata

from .config import CODEBOOKS_DIR


class CodebookManager:
    def __init__(self, root: Path = CODEBOOKS_DIR) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active_id: str | None = None
        self._active_max_index: int | None = None
        self._state_path = self.root / "server_state.json"
        self._load_state()

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        data = json.loads(self._state_path.read_text(encoding="utf-8"))
        self._active_id = data.get("active_codebook_id")
        if self._active_id:
            try:
                self._active_max_index = self.get_header(self._active_id).num_masks
            except FileNotFoundError:
                self._active_id = None
                self._active_max_index = None

    def _save_state(self) -> None:
        payload = {"active_codebook_id": self._active_id}
        self._state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @property
    def active_codebook_id(self) -> str | None:
        return self._active_id

    @property
    def active_max_index(self) -> int | None:
        return self._active_max_index

    def set_active(self, codebook_id: str) -> None:
        with self._lock:
            self._active_id = codebook_id
            header = self.get_header(codebook_id)
            self._active_max_index = header.num_masks
            self._save_state()

    def list_codebooks(self) -> list[dict]:
        items: list[dict] = []
        for path in sorted(self.root.glob("*.cbk")):
            header, _ = read_codebook(path)
            codebook_id = path.stem
            items.append(
                {
                    "id": codebook_id,
                    "name": header.name,
                    "num_masks": header.num_masks,
                    "mask_bytes": header.mask_bytes,
                    "payload_crc32": f"{header.payload_crc32:08x}",
                    "path": str(path),
                    "on_teensy": False,
                }
            )
        return items

    def get_path(self, codebook_id: str) -> Path:
        path = self.root / f"{codebook_id}.cbk"
        if not path.exists():
            raise FileNotFoundError(f"Codebook not found: {codebook_id}")
        return path

    def get_header(self, codebook_id: str) -> CodebookHeader:
        header, _ = read_codebook(self.get_path(codebook_id))
        return header

    def import_file(self, source: Path, codebook_id: str | None = None) -> dict:
        header, payload = read_codebook(source)
        codebook_id = codebook_id or header.name.replace(" ", "_")
        dest = self.root / f"{codebook_id}.cbk"
        shutil.copy2(source, dest)
        return {
            "id": codebook_id,
            "name": header.name,
            "num_masks": header.num_masks,
            "mask_bytes": header.mask_bytes,
            "payload_crc32": f"{header.payload_crc32:08x}",
            "path": str(dest),
            "on_teensy": False,
        }

    def get_mask_bytes(self, codebook_id: str, index: int) -> bytes:
        _, payload = read_codebook(self.get_path(codebook_id))
        header = parse_header((self.get_path(codebook_id).read_bytes())[:HEADER_SIZE])
        start = index * header.mask_bytes
        end = start + header.mask_bytes
        return payload[start:end]

    def metadata_for_gui(self, codebook_id: str) -> dict:
        header = self.get_header(codebook_id)
        meta = load_metadata(self.get_path(codebook_id), header.num_masks)
        payload = meta.to_dict()
        payload.update(
            {
                "id": codebook_id,
                "name": header.name,
                "num_masks": header.num_masks,
                "mask_bytes": header.mask_bytes,
                "payload_crc32": f"{header.payload_crc32:08x}",
                "grid_side": meta.codeword_grid_cols,
            }
        )
        return payload

    def get_codebook_metadata(self, codebook_id: str) -> CodebookMetadata:
        header = self.get_header(codebook_id)
        return load_metadata(self.get_path(codebook_id), header.num_masks)

    def raw_payload(self, codebook_id: str) -> tuple[CodebookHeader, bytes]:
        return read_codebook(self.get_path(codebook_id))
