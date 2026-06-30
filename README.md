# RIS Controller

Server-centric control stack for a Teensy-driven RIS hardware platform. A remote **RIS GUI** sends commands to the **RIS server**, which manages codebooks and talks to the Teensy over USB serial.

```
RIS GUI (browser)  --HTTP/WS-->  RIS Server (Python)  --serial-->  Teensy  -->  RIS motherboard
```

## Components

| Path | Purpose |
|------|---------|
| `firmware/ris_controller/` | Slim Teensy firmware (no embedded codebook) |
| `server/` | Starlette server — codebook library, Teensy bridge, REST + WebSocket |
| `gui/` | Web UI — codebook selection, beam grid, pattern visualization |
| `tools/` | Pack/extract `.cbk` codebooks |
| `shared/` | Binary codebook format |
| `client/` | Python `RisClient` for experiment scripts |
| `examples/` | Example automation scripts |
| `codebooks/` | Server-side codebook library (`.cbk` files) |

The real imaging codebook is at `codebooks/Imaging_M260P260M520P0_STEP2cm.cbk` (730 masks, 1280 bytes/mask).

## Quick start (development, no hardware)

```bash
cd ris_controller
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Mock Teensy (no USB device required)
export RIS_TEENSY_MOCK=1
python run_server.py
```

Open **http://localhost:8080** for the RIS GUI.

## Production (with Teensy 4.1)

1. Flash `firmware/ris_controller/ris_controller.ino` with Teensyduino (Teensy 4.1).
   - Codebook lives in **RAM** — upload after each reboot. **Do not use SerialFlash** (GPIO pin 6 is the RIS shift clock).
2. Connect Teensy USB to the server machine.
3. Convert a legacy sketch to `.cbk` (one-time):

```bash
python tools/extract_from_ino.py ~/Downloads/Imaging_M260P260M520P0_STEP2cm/Imaging_M260P260M520P0_STEP2cm.ino
```

4. Start the server:

```bash
export RIS_TEENSY_PORT=/dev/ttyACM0   # or /dev/cu.usbmodem* on macOS
export RIS_TEENSY_BAUD=921600
python run_server.py
```

## Workflow

### 1. Register a codebook on the server

- Upload `.cbk` via GUI, or copy into `codebooks/`, or:

```bash
python tools/pack_codebook.py --name MyCodebook --mask-dir ./masks/ -o codebooks/MyCodebook.cbk
```

### 2. Activate codebook on Teensy (from GUI or API)

The server compares CRC with Teensy `STATUS`. If different (or **force re-upload**), it uploads via:

```
CODEBOOK_BEGIN <name> <num_masks> <mask_bytes> <crc32>
<binary payload>
OK VERIFIED
```

### 3. Apply beam index (codeword)

If the Teensy already has the right codebook, only the index is sent:

```
APPLY 42
```

Legacy scripts can still send plain integers (`42\n`).

## API (for RIS GUI / automation)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Teensy + session status |
| GET | `/api/codebooks` | List server codebooks |
| POST | `/api/codebooks/upload` | Upload `.cbk` file |
| GET | `/api/codebooks/{id}` | Codebook metadata |
| GET | `/api/codebooks/{id}/mask/{index}/ris-map` | **64×64** phase map (0°/180°) |
| GET | `/api/codebooks/{id}/meta` | Codebook grid + RIS dimensions |
| POST | `/api/session/select-codebook` | Select + upload if needed |
| POST | `/api/beam/apply` | Apply codeword index |
| WS | `/ws/events` | `beam_applied`, `codebook_selected`, … |

### Example: apply beam without re-uploading codebook

```bash
curl -X POST http://localhost:8080/api/session/select-codebook \
  -H 'Content-Type: application/json' \
  -d '{"codebook_id":"Imaging_M260P260M520P0_STEP2cm","force_upload":false}'

curl -X POST http://localhost:8080/api/beam/apply \
  -H 'Content-Type: application/json' \
  -d '{"index":42}'
```

## Experiment scripts (via `RisClient`)

Use the Python client instead of opening serial directly:

```python
from client.ris_client import RisClient

client = RisClient("http://lab-pc:8080")
client.ensure_codebook("Imaging_M260P260M520P0_STEP2cm")  # uploads only if needed
client.apply_beam(42)
```

Or run the included sweep example:

```bash
export RIS_SERVER_URL=http://localhost:8080
python examples/run_beam_sweep.py --codebook Imaging_M260P260M520P0_STEP2cm --start 1 --end 10
```

## Remote GUI

The GUI can control a server on another machine:

1. Start the server on the lab PC (`RIS_SERVER_HOST=0.0.0.0`).
2. On your laptop, open the GUI and set **API base URL** to `http://<lab-pc-ip>:8080`, then click **Connect**.

Alternatively open `http://<lab-pc-ip>:8080` directly in a browser on any machine on the network.

For a GUI hosted on a different origin, set `RIS_CORS_ORIGINS` on the server (default `*`).

## Visualization (64×64 RIS phase map)

The GUI decodes each mask into a **64×64** array (`0` = 0°, `1` = 180°), matching the MATLAB tile layout (20 tiles × 16×16, first 64 columns of the 64×80 stitched grid).

Optional metadata per codebook: `codebooks/MyCodebook.cbk.meta.json`

```json
{
  "ris_rows": 64,
  "ris_cols": 64,
  "codeword_grid_rows": 27,
  "codeword_grid_cols": 27,
  "dummy_index": 0,
  "step_cm": 2.0
}
```

- **Current beam:** `last_applied_index` in `/api/status` or GUI status panel  
- **Codeword count:** `usable_masks` in metadata (729 for imaging + index 0 dummy)  
- **Phase map:** `GET /api/codebooks/{id}/mask/{index}/ris-map`

## Codebook format (`.cbk`)

```
[96-byte header][mask0][mask1]...[maskN-1]
```

Header: magic `RISCBK01`, `num_masks`, `mask_bytes`, `name`, `payload_crc32`.

## Teensy serial protocol

| Command | Response |
|---------|----------|
| `PING` | `PONG` |
| `STATUS` | `OK store=flash masks=730 mask_bytes=1280 name=... crc=...` |
| `CODEBOOK_BEGIN name N B crc` | `READY` → binary → `OK VERIFIED` |
| `APPLY 42` | `OK APPLY_QUEUED` → `OK APPLIED 42` |
| `42` (legacy) | same as APPLY |
| `CLEAR` | `OK CLEARED` |
| `ABORT` | `OK ABORTED` |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RIS_TEENSY_PORT` | empty | Serial port (`RIS_TEENSY_MOCK=1` if empty) |
| `RIS_TEENSY_MOCK` | `0` | Use in-memory mock Teensy |
| `RIS_TEENSY_BAUD` | `921600` | Serial baud rate |
| `RIS_SERVER_HOST` | `0.0.0.0` | Server bind address |
| `RIS_SERVER_PORT` | `8080` | Server port |
| `RIS_CODEBOOKS_DIR` | `./codebooks` | Codebook library path |
| `RIS_SERVER_URL` | `http://localhost:8080` | Default URL for `RisClient` / examples |
| `RIS_CORS_ORIGINS` | `*` | Allowed browser origins for remote GUI |
| `RIS_UDP_PORT` | `5005` | UDP fast beam control port |
| `RIS_FAST_SKIP_CRC` | `1` | Skip CRC check on `/api/beam/apply-fast` |

## Latency tiers (beam apply)

| Path | Typical command latency | Waits for RIS hardware? |
|------|-------------------------|-------------------------|
| `POST /api/beam/apply` | **2–20 ms** | Yes (~30 ms shift) |
| `POST /api/beam/apply?fast=1` | **0.5–3 ms** | No |
| `POST /api/beam/apply-fast` | **0.3–2 ms** | No |
| **UDP** `RI` + uint16 → port 5005 | **50–500 µs** (localhost) | No |

Hardware shift-register programming is still **~25–50 ms** regardless of API — that is physics, not software.

### Fast experiment client (UDP)

```python
from client.ris_fast_client import RisFastClient

with RisFastClient("127.0.0.1", 5005) as fast:
    fast.apply_beam(42)  # fire-and-forget
```

Packet format: `b"RI" + index.to_bytes(2, "big")`

Benchmark: `python examples/bench_apply_latency.py`

## Architecture notes

- **Server owns codebook library** — generation, storage, selection, upload orchestration.
- **GUI is a thin client** — visualizes masks and sends high-level commands.
- **Teensy stores one active codebook** in QSPI flash (4.1) or RAM (dev fallback).
- **Fast path** — when CRC matches, only `APPLY <index>` is sent (~milliseconds).

## Documentation

- **[Beam control flow](docs/beam_control_flow.md)** — diagrams from xApp/GUI through codeword lookup on Teensy.
- Export SVG/PNG: `./scripts/export_diagrams.sh` (works with `curl` only — no npm required).
