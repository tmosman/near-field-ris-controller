"""Shared serial line reading for Teensy CLI tools."""

from __future__ import annotations

import time


def _get_buf(ser) -> bytearray:
    buf = getattr(ser, "_ris_line_buf", None)
    if buf is None:
        buf = bytearray()
        ser._ris_line_buf = buf  # type: ignore[attr-defined]
    return buf


def read_line(ser, timeout_s: float) -> str:
    """Read one line; keeps bytes after the first newline for the next call."""
    buf = _get_buf(ser)
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        if b"\n" in buf:
            raw, rest = buf.split(b"\n", 1)
            ser._ris_line_buf = rest  # type: ignore[attr-defined]
            return raw.decode("utf-8", errors="replace").strip()

        waiting = ser.in_waiting
        if waiting:
            buf.extend(ser.read(waiting))
            continue

        time.sleep(0.01)

    if buf:
        line = buf.decode("utf-8", errors="replace").strip()
        ser._ris_line_buf = bytearray()  # type: ignore[attr-defined]
        return line
    return ""


def drain(ser, max_wait_s: float = 0.2) -> None:
    deadline = time.time() + max_wait_s
    ser._ris_line_buf = bytearray()  # type: ignore[attr-defined]
    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            ser.read(waiting)
            deadline = time.time() + max_wait_s
            continue
        time.sleep(0.02)


def wait_for_apply_responses(ser, timeout_s: float = 60.0) -> tuple[bool, list[str]]:
    """Read until OK APPLY_QUEUED and OK APPLIED (or ERR). Returns (success, lines)."""
    lines: list[str] = []
    got_queued = False
    got_applied = False
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        remaining = max(0.05, deadline - time.time())
        line = read_line(ser, timeout_s=min(1.0, remaining))
        if not line:
            continue
        lines.append(line)
        if line == "OK APPLY_QUEUED":
            got_queued = True
        elif line.startswith("OK APPLIED "):
            got_applied = True
            break
        elif line.startswith("ERR"):
            break

    return got_queued and got_applied, lines
