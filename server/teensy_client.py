from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .config import SERIAL_TIMEOUT_S, TEENSY_BAUD, TEENSY_MOCK, TEENSY_PORT, UPLOAD_CHUNK_BYTES
from shared.codebook_format import CodebookHeader


@dataclass
class TeensyStatus:
    connected: bool
    store: str
    masks: int
    mask_bytes: int
    name: str | None
    crc: str | None


class MockTeensyClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connected = True
        self._header: CodebookHeader | None = None
        self._last_applied: int | None = None

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def ping(self) -> bool:
        return self._connected

    def get_status(self) -> TeensyStatus:
        if not self._header:
            return TeensyStatus(True, "ram", 0, 0, None, None)
        return TeensyStatus(
            True,
            "ram",
            self._header.num_masks,
            self._header.mask_bytes,
            self._header.name,
            f"{self._header.payload_crc32:08x}",
        )

    def upload_codebook(self, header: CodebookHeader, payload: bytes) -> None:
        with self._lock:
            if len(payload) != header.payload_size:
                raise ValueError("Payload size mismatch")
            self._header = header
            time.sleep(0.2)

    def apply_index(self, index: int) -> int:
        with self._lock:
            if not self._header:
                raise RuntimeError("No codebook loaded on mock Teensy")
            if index >= self._header.num_masks:
                raise ValueError("Index out of range")
            self._last_applied = index
            return index

    def send_index_fire_and_forget(self, index: int) -> None:
        self.apply_index(index)

    def apply_index_fast(self, index: int) -> int:
        return self.apply_index(index)

    @property
    def last_applied(self) -> int | None:
        return self._last_applied


class TeensyClient:
    def __init__(self, port: str, baud: int = TEENSY_BAUD) -> None:
        self.port = port
        self.baud = baud
        self._lock = threading.Lock()
        self._serial = None
        self._last_applied: int | None = None

    def connect(self) -> None:
        import serial

        with self._lock:
            if self._serial and self._serial.is_open:
                return
            self._open_serial_port()
            try:
                self._recover_serial_session()
            except Exception as exc:
                print(f"Warning: Teensy sync incomplete on connect: {exc}")

    def _open_serial_port(self) -> None:
        """Open Teensy serial, handling USB reset + re-enumeration."""
        import serial

        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
            time.sleep(0.5)

        try:
            # First open triggers Teensy reset via DTR.
            probe = serial.Serial(self.port, self.baud, timeout=SERIAL_TIMEOUT_S)
            probe.close()
        except Exception as exc:
            raise RuntimeError(f"Could not open {self.port}: {exc}") from exc

        # Wait for Teensy to reboot and USB to re-enumerate.
        time.sleep(2.0)

        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=SERIAL_TIMEOUT_S)
        except Exception as exc:
            self._serial = None
            raise RuntimeError(f"Could not reopen {self.port} after reset: {exc}") from exc

        time.sleep(1.5)
        boot_lines = self._collect_boot_lines(max_wait_s=2.0)
        if boot_lines:
            print(f"Teensy boot: {boot_lines[-1]}")
        else:
            print("Warning: no Teensy boot lines seen after connect")

    def _collect_boot_lines(self, max_wait_s: float = 2.0) -> list[str]:
        lines: list[str] = []
        deadline = time.time() + max_wait_s
        while time.time() < deadline:
            try:
                line = self._readline()
            except TimeoutError:
                break
            lines.append(line)
            if line in {
                "OK BOOT",
                "OK RIS_FW=3",
                "OK RAM_STORE",
                "WARN NO_CODEBOOK_LOADED",
            }:
                break
        return lines

    def reconnect(self) -> None:
        with self._lock:
            self._open_serial_port()
            try:
                self._recover_serial_session()
            except Exception as exc:
                print(f"Warning: Teensy sync incomplete after reconnect: {exc}")

    def _recover_serial_session(self) -> None:
        """Clear stale bytes and escape a stuck binary-upload state."""
        self._require_serial()
        assert self._serial is not None
        for _ in range(2):
            self._drain_input(max_wait_s=0.2)
            try:
                self._serial.write(b"ABORT\n")
                self._serial.flush()
            except Exception:
                break
            time.sleep(0.05)
        self._drain_input(max_wait_s=0.3)
        for _ in range(6):
            self._drain_input()
            try:
                self._serial.write(b"PING\n")
                self._serial.flush()
            except Exception:
                break
            try:
                if self._expect_line(accept_exact={"PONG"}, timeout_s=1.0) == "PONG":
                    return
            except (TimeoutError, OSError):
                time.sleep(0.5)
        print("Warning: Teensy did not respond to PING after connect")

    def disconnect(self) -> None:
        with self._lock:
            if self._serial:
                self._serial.close()
                self._serial = None

    def _require_serial(self):
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Teensy serial not connected")

    def _drain_input(self, max_wait_s: float = 0.0) -> None:
        import serial

        self._require_serial()
        assert self._serial is not None
        deadline = time.time() + max_wait_s
        while True:
            try:
                waiting = self._serial.in_waiting
            except (serial.SerialException, OSError):
                time.sleep(0.05)
                waiting = 0
            if waiting:
                try:
                    data = self._serial.read(waiting)
                except (serial.SerialException, OSError):
                    time.sleep(0.05)
                    deadline = time.time() + max(max_wait_s, 0.2)
                    continue
                if data:
                    deadline = time.time() + max_wait_s
                    continue
                time.sleep(0.05)
                continue
            if max_wait_s <= 0 or time.time() >= deadline:
                break
            time.sleep(0.05)

    def _readline(self) -> str:
        import serial

        self._require_serial()
        assert self._serial is not None
        try:
            raw = self._serial.readline()
        except (serial.SerialException, OSError) as exc:
            raise TimeoutError("Teensy serial read failed") from exc
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            raise TimeoutError("Timed out waiting for Teensy response")
        return line

    def _expect_line(
        self,
        *,
        accept_exact: set[str] | None = None,
        accept_prefix: str | None = None,
        timeout_s: float | None = None,
    ) -> str:
        deadline = time.time() + (timeout_s if timeout_s is not None else SERIAL_TIMEOUT_S * 2)
        while time.time() < deadline:
            line = self._readline()
            if accept_exact and line in accept_exact:
                return line
            if accept_prefix and line.startswith(accept_prefix):
                return line
            if line.startswith("ERR"):
                return line
            # Skip stale boot/apply lines left in the USB buffer.
        raise TimeoutError("Timed out waiting for Teensy response")

    def _command_line(self, line: str, *, accept_exact: set[str] | None = None, accept_prefix: str | None = None, timeout_s: float | None = None) -> str:
        with self._lock:
            self._require_serial()
            assert self._serial is not None
            self._drain_input()
            self._serial.write((line + "\n").encode("utf-8"))
            self._serial.flush()
            return self._expect_line(
                accept_exact=accept_exact,
                accept_prefix=accept_prefix,
                timeout_s=timeout_s,
            )

    def ping(self) -> bool:
        try:
            return (
                self._command_line("PING", accept_exact={"PONG"}, timeout_s=1.5) == "PONG"
            )
        except Exception:
            return False

    def get_status(self) -> TeensyStatus:
        for attempt in range(2):
            try:
                line = self._command_line(
                    "STATUS",
                    accept_prefix="OK store=",
                    timeout_s=SERIAL_TIMEOUT_S,
                )
                break
            except Exception:
                if attempt == 0:
                    try:
                        with self._lock:
                            self._recover_serial_session()
                    except Exception:
                        pass
                    continue
                return TeensyStatus(False, "unknown", 0, 0, None, None)
        else:
            return TeensyStatus(False, "unknown", 0, 0, None, None)

        if "store=empty" in line:
            return TeensyStatus(True, "empty", 0, 0, None, None)

        parts = {}
        for token in line.replace("OK ", "").split():
            if "=" in token:
                key, value = token.split("=", 1)
                parts[key] = value

        return TeensyStatus(
            connected=True,
            store=parts.get("store", "unknown"),
            masks=int(parts.get("masks", "0")),
            mask_bytes=int(parts.get("mask_bytes", "0")),
            name=parts.get("name"),
            crc=parts.get("crc"),
        )

    def _ensure_ready(self) -> None:
        if self.ping():
            return
        print("Teensy not responding; attempting reconnect…")
        self.reconnect()
        if not self.ping():
            raise RuntimeError("Teensy not responding on serial (check port, baud 921600, and firmware)")

    def upload_codebook(self, header: CodebookHeader, payload: bytes) -> None:
        if len(payload) != header.payload_size:
            raise ValueError("Payload size mismatch")

        self._ensure_ready()

        command = (
            f"CODEBOOK_BEGIN {header.name} {header.num_masks} "
            f"{header.mask_bytes} {header.payload_crc32:08x}"
        )
        with self._lock:
            self._require_serial()
            assert self._serial is not None
            self._drain_input()
            self._serial.write((command + "\n").encode("utf-8"))
            self._serial.flush()
            ready = self._expect_line(accept_exact={"READY"}, timeout_s=SERIAL_TIMEOUT_S)
            if ready != "READY":
                raise RuntimeError(f"Teensy not ready for upload: {ready}")

            offset = 0
            while offset < len(payload):
                chunk = payload[offset : offset + UPLOAD_CHUNK_BYTES]
                self._serial.write(chunk)
                self._serial.flush()
                offset += len(chunk)
                time.sleep(0.001)

            response = self._expect_line(
                accept_exact={"OK VERIFIED"},
                timeout_s=max(SERIAL_TIMEOUT_S * 6, 30.0),
            )
            if response != "OK VERIFIED":
                raise RuntimeError(f"Codebook upload failed: {response}")

    def apply_index(self, index: int) -> int:
        self._ensure_ready()
        with self._lock:
            self._require_serial()
            assert self._serial is not None
            self._drain_input()
            self._serial.write(f"APPLY {index}\n".encode("utf-8"))
            self._serial.flush()
            queued = self._expect_line(accept_exact={"OK APPLY_QUEUED"})
            if queued != "OK APPLY_QUEUED":
                raise RuntimeError(f"Apply rejected: {queued}")

            applied = self._expect_line(accept_prefix="OK APPLIED ", timeout_s=SERIAL_TIMEOUT_S * 3)
            if not applied.startswith("OK APPLIED "):
                raise RuntimeError(f"Apply failed: {applied}")
            applied_index = int(applied.split()[-1])
            self._last_applied = applied_index
            return applied_index

    def send_index_fire_and_forget(self, index: int) -> None:
        """Queue beam on Teensy without waiting for hardware shift (~30ms) to finish."""
        with self._lock:
            self._require_serial()
            assert self._serial is not None
            self._drain_input()
            self._serial.write(f"{index}\n".encode("ascii"))
            self._serial.flush()
            queued = self._expect_line(accept_exact={"OK APPLY_QUEUED"}, timeout_s=SERIAL_TIMEOUT_S)
            if queued != "OK APPLY_QUEUED":
                raise RuntimeError(f"Apply rejected: {queued}")
            self._last_applied = index

    def apply_index_fast(self, index: int) -> int:
        """Send apply and return after Teensy accepts queue (not after shift completes)."""
        with self._lock:
            self._require_serial()
            assert self._serial is not None
            self._drain_input()
            self._serial.write(f"{index}\n".encode("ascii"))
            self._serial.flush()
            queued = self._expect_line(accept_exact={"OK APPLY_QUEUED"}, timeout_s=SERIAL_TIMEOUT_S)
            if queued != "OK APPLY_QUEUED":
                raise RuntimeError(f"Apply rejected: {queued}")
            self._last_applied = index
            return index

    @property
    def last_applied(self) -> int | None:
        return self._last_applied


def create_teensy_client() -> MockTeensyClient | TeensyClient:
    if TEENSY_MOCK or not TEENSY_PORT:
        return MockTeensyClient()
    return TeensyClient(TEENSY_PORT, TEENSY_BAUD)
