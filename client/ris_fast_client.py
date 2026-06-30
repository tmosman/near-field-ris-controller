"""Microsecond-scale beam commands via UDP (for time-critical experiments).

Typical localhost latency: ~0.05–0.5 ms to hand off to serial (not including ~30 ms RIS shift).
"""

from __future__ import annotations

import os
import socket
import struct
import time

UDP_MAGIC = b"RI"


class RisFastClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.host = host or os.getenv("RIS_UDP_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("RIS_UDP_PORT", "5005"))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def apply_beam(self, index: int) -> None:
        if index < 0 or index > 0xFFFF:
            raise ValueError("index must fit in uint16")
        packet = UDP_MAGIC + struct.pack("!H", index)
        self._sock.sendto(packet, (self.host, self.port))

    def apply_beam_timed(self, index: int) -> float:
        """Return local send latency in seconds (for benchmarking)."""
        t0 = time.perf_counter()
        self.apply_beam(index)
        return time.perf_counter() - t0

    def close(self) -> None:
        self._sock.close()

    def __enter__(self) -> RisFastClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()
