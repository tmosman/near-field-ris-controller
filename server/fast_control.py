"""Ultra-low-latency beam control (UDP + fire-and-forget serial).

HTTP REST is fine for setup/GUI (~few ms). For experiment timing use this path:
  client --UDP 4 bytes--> server --serial--> Teensy queue --> ~30ms hardware shift

Command *acceptance* can be sub-millisecond; RIS phase update is still tens of ms.
"""

from __future__ import annotations

import socket
import struct
import threading

from .codebook_manager import CodebookManager
from .config import UDP_CONTROL_HOST, UDP_CONTROL_PORT

# Packet: b"RI" + uint16 big-endian beam index
UDP_MAGIC = b"RI"
UDP_PACKET_LEN = 4


class UdpBeamListener:
    def __init__(self, teensy, manager: CodebookManager) -> None:
        self._teensy = teensy
        self._manager = manager
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._sock: socket.socket | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ris-udp-control", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((UDP_CONTROL_HOST, UDP_CONTROL_PORT))
        sock.settimeout(0.25)
        self._sock = sock
        while not self._stop.is_set():
            try:
                data, _addr = sock.recvfrom(32)
            except TimeoutError:
                continue
            except OSError:
                break
            if len(data) != UDP_PACKET_LEN or data[:2] != UDP_MAGIC:
                continue
            (index,) = struct.unpack("!H", data[2:4])
            max_index = self._manager.active_max_index
            if max_index is None or index >= max_index:
                continue
            try:
                self._teensy.send_index_fire_and_forget(index)
            except Exception:
                pass


def pack_udp_apply(index: int) -> bytes:
    if index < 0 or index > 0xFFFF:
        raise ValueError("index must fit in uint16")
    return UDP_MAGIC + struct.pack("!H", index)
