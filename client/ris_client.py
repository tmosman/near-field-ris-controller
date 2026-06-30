"""HTTP client for the RIS controller server.

Use this in experiment scripts instead of talking to the Teensy over serial directly.
"""

from __future__ import annotations

import os
from typing import Any

import json
import urllib.error
import urllib.request


class RisClientError(RuntimeError):
    pass


class RisClient:
    def __init__(self, base_url: str | None = None, timeout_s: float = 30.0) -> None:
        self.base_url = (base_url or os.getenv("RIS_SERVER_URL", "http://localhost:8080")).rstrip("/")
        self.timeout_s = timeout_s

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RisClientError(f"{method} {path} failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RisClientError(f"Cannot reach RIS server at {self.base_url}: {exc}") from exc

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/api/status")

    def list_codebooks(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/codebooks")

    def select_codebook(self, codebook_id: str, force_upload: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/session/select-codebook",
            {"codebook_id": codebook_id, "force_upload": force_upload},
        )

    def apply_beam(self, index: int) -> dict[str, Any]:
        return self._request("POST", "/api/beam/apply", {"index": index})

    def get_mask(self, codebook_id: str, index: int) -> dict[str, Any]:
        return self._request("GET", f"/api/codebooks/{codebook_id}/mask/{index}")

    def get_ris_map(self, codebook_id: str, index: int) -> dict[str, Any]:
        return self._request("GET", f"/api/codebooks/{codebook_id}/mask/{index}/ris-map")

    def ensure_codebook(self, codebook_id: str, force_upload: bool = False) -> dict[str, Any]:
        """Select codebook; upload only if Teensy CRC differs (unless forced)."""
        return self.select_codebook(codebook_id, force_upload=force_upload)

    def apply_beam_fast(self, index: int) -> None:
        """Fire-and-forget beam apply via UDP (lowest latency)."""
        from client.ris_fast_client import RisFastClient

        host = os.getenv("RIS_UDP_HOST", "127.0.0.1")
        port = int(os.getenv("RIS_UDP_PORT", "5005"))
        with RisFastClient(host, port) as fast:
            fast.apply_beam(index)

    def apply_beam_if_ready(self, codebook_id: str, index: int, force_upload: bool = False) -> dict[str, Any]:
        """Convenience: ensure codebook then apply index."""
        self.ensure_codebook(codebook_id, force_upload=force_upload)
        return self.apply_beam(index)
