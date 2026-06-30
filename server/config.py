from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CODEBOOKS_DIR = Path(os.getenv("RIS_CODEBOOKS_DIR", BASE_DIR / "codebooks"))
GUI_DIR = BASE_DIR / "gui"

TEENSY_PORT = os.getenv("RIS_TEENSY_PORT", "")
TEENSY_BAUD = int(os.getenv("RIS_TEENSY_BAUD", "921600"))
TEENSY_MOCK = os.getenv("RIS_TEENSY_MOCK", "0") == "1"

HOST = os.getenv("RIS_SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("RIS_SERVER_PORT", "8080"))

# Comma-separated origins for remote GUI, e.g. "http://192.168.1.10:3000,http://localhost:3000"
# Use "*" to allow any origin (convenient in lab networks).
CORS_ORIGINS = os.getenv("RIS_CORS_ORIGINS", "*")

SERIAL_TIMEOUT_S = float(os.getenv("RIS_SERIAL_TIMEOUT_S", "5"))
UPLOAD_CHUNK_BYTES = int(os.getenv("RIS_UPLOAD_CHUNK_BYTES", "4096"))

# Low-latency beam control (see server/fast_control.py)
UDP_CONTROL_HOST = os.getenv("RIS_UDP_HOST", "0.0.0.0")
UDP_CONTROL_PORT = int(os.getenv("RIS_UDP_PORT", "5005"))
FAST_SKIP_CRC_CHECK = os.getenv("RIS_FAST_SKIP_CRC", "1") == "1"

CODEBOOKS_DIR.mkdir(parents=True, exist_ok=True)
