# RIS Controller

Server-centric control stack for a Teensy-driven RIS hardware platform. A remote **RIS GUI** sends commands to the **RIS server**, which manages codebooks and talks to the Teensy over USB serial.

```
RIS GUI (browser)  --HTTP/WS-->  RIS Server (Python)  --serial-->  Teensy  -->  RIS motherboard
                                      │
                                      └── Direct CLI tools (upload / apply / probe)
```

**Repository:** [github.com/tmosman/near-field-ris-controller](https://github.com/tmosman/near-field-ris-controller)

## Components

| Path | Purpose |
|------|---------|
| `firmware/ris_controller/` | Slim Teensy firmware (no embedded codebook) |
| `server/` | Starlette server — codebook library, Teensy bridge, REST + WebSocket |
| `gui/` | Web UI — codebook selection, beam grid, pattern visualization |
| `tools/` | Extract/pack `.cbk`, direct serial upload & apply |
| `shared/` | Binary codebook format |
| `client/` | Python `RisClient` for experiment scripts |
| `examples/` | Example automation scripts |
| `codebooks/` | Server-side codebook library (`.cbk` files) |

The full imaging codebook is `codebooks/Imaging_M260P260M520P0_STEP2cm.cbk` (730 masks, 1280 bytes/mask). Smaller test codebooks: `codebooks/Firmware_script_plus_codewords.cbk` (22 masks). Extract `../Mask_Upload_Test_V3.txt` to `codebooks/Mask_Upload_Test_V3.cbk` (21 masks) — see below.

## Setup

```bash
cd ris_controller
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Command reference

All commands assume the venv is active and you are in the repo root.

### 1. Create / extract codewords (`.cbk` codebook)

Codewords are stored as **1280-byte masks** (64×64 RIS panel). Build a `.cbk` from a legacy text source, raw binaries, or an Arduino sketch.

#### Source text format (`//Mask` + `0b…` bytes)

Used by legacy `Imaging_*.ino` sketches and standalone `.txt` exports (e.g. `Mask_Upload_Test_V3.txt`):

```
//Mask 1
{0b00000000,0b00000000,...,0b10101010
},

//Mask 2
{0b00000000,...
},
```

Each mask block must contain **1280** `0b........` byte literals. The extractor accepts **`.ino` or `.txt`** files with this layout.

#### Extract from `.ino` or `.txt`

`tools/extract_from_ino.py` parses `//Mask …` sections and writes a `.cbk` file:

```bash
# Legacy Arduino sketch → .cbk (default output: same path with .cbk extension)
python tools/extract_from_ino.py \
  ../Imaging_Empty/Imaging_Empty.ino

# Standalone codeword text file (same format as .ino bitList)
python tools/extract_from_ino.py \
  ../Mask_Upload_Test_V3.txt \
  --name Mask_Upload_Test_V3 \
  -o codebooks/Mask_Upload_Test_V3.cbk

# Full imaging codebook (730 masks)
python tools/extract_from_ino.py \
  ~/Downloads/Imaging_M260P260M520P0_STEP2cm/Imaging_M260P260M520P0_STEP2cm.ino \
  --name Imaging_M260P260M520P0_STEP2cm \
  -o codebooks/Imaging_M260P260M520P0_STEP2cm.cbk
```

Example output:

```
Extracted 21 masks from Mask_Upload_Test_V3.txt -> codebooks/Mask_Upload_Test_V3.cbk (mask_bytes=1280, crc=52276224)
```

#### Beam index vs `//Mask` label

Array indices in the `.cbk` are **0-based** and follow file order:

| Source label | Codebook index | `teensy_apply --index` |
|--------------|----------------|-------------------------|
| `//Mask 1`   | 0              | `0`                     |
| `//Mask 2`   | 1              | `1`                     |
| `//Mask N`   | N − 1          | `N − 1`                 |

Legacy `Imaging_Empty.ino` used **index 0** as an all-off dummy and **index 1** for the first real beam. If your `.txt` starts at `//Mask 1` with no dummy, either apply with `--index 0` for the first mask, or prepend a dummy block (below).

#### Optional: legacy index 1 = first beam

If you want **index 1** to select the first labeled mask (like `Imaging_Empty.ino` with dummy index 0), prepend an all-off `//Mask 0` block before `//Mask 1` in your source text — 1280 lines of `0b00000000`, then extract. Alternatively use a codebook that already includes dummy index 0 (e.g. `Firmware_script_plus_codewords.cbk`).

#### Create new codewords

- **Edit the text format:** add a new `//Mask N` block with 1280 `0b........` lines, then re-run `extract_from_ino.py`.
- **Pack from binary files:** one file per mask, each exactly 1280 bytes:

```bash
python tools/pack_codebook.py \
  --name MyCodebook \
  --mask-dir ./masks/ \
  -o codebooks/MyCodebook.cbk
```

**Generate a synthetic demo codebook** (729 masks, for GUI/server testing):

```bash
python tools/make_demo_codebook.py
```

### 2. Flash Teensy firmware (one-time)

1. Open `firmware/ris_controller/ris_controller.ino` in Arduino IDE (Teensyduino, **Teensy 4.1**).
2. Upload. Boot lines should include:
   ```
   OK RAM_STORE
   WARN NO_CODEBOOK_LOADED
   OK RIS_FW=3
   OK BOOT
   ```
3. **Do not use SerialFlash** — GPIO pin 6 is the RIS shift clock.

Codebooks live in **RAM only** and are lost on reboot or when the USB serial port is reopened. Re-upload after power cycle.

### 3. Direct Teensy control (no server)

Use these when debugging hardware or when the server is not running. **Only one process** may open the serial port (close Serial Monitor and `run_server.py` first).

**Find the correct port:**

```bash
python tools/teensy_find_port.py
```

**Health check:**

```bash
python tools/teensy_probe.py --port /dev/ttyACM0
python tools/teensy_apply.py --ping --port /dev/ttyACM0
python tools/teensy_apply.py --status --port /dev/ttyACM0
```

Expected `STATUS` when loaded:

```
OK store=ram masks=22 mask_bytes=1280 name=Firmware_script_plus_codewords crc=f064f1f4 backend=ram
```

**Upload codebook** (921600 baud):

```bash
python tools/teensy_upload_cbk.py \
  codebooks/Firmware_script_plus_codewords.cbk \
  --port /dev/ttyACM0
```

**Upload and apply in one session** (recommended — opening serial clears RAM codebook on boot):

```bash
# Firmware_script_plus_codewords: index 1 = first real beam (index 0 is dummy)
python tools/teensy_upload_cbk.py \
  codebooks/Firmware_script_plus_codewords.cbk \
  --port /dev/ttyACM0 \
  --apply 1

# Mask_Upload_Test_V3: index 0 = //Mask 1 (no dummy in source file)
python tools/teensy_upload_cbk.py \
  codebooks/Mask_Upload_Test_V3.cbk \
  --port /dev/ttyACM0 \
  --apply 0
```

**Apply beam index** (codebook must already be on Teensy):

```bash
# Preferred command form
python tools/teensy_apply.py --index 1 --port /dev/ttyACM0

# Legacy Imaging_Empty.ino style (plain integer, same as Serial.parseInt)
python tools/teensy_apply.py --legacy --index 1 --port /dev/ttyACM0

# Clear shift registers (all-off)
python tools/teensy_apply.py --clear --port /dev/ttyACM0
```

**Beam index notes:**

| Index | Meaning |
|-------|---------|
| `0` | Dummy all-off mask (~0 A) when present at start of codebook |
| `1…N` | Real codewords in books with dummy index 0 (e.g. `Firmware_script_plus_codewords`) |
| `0…N−1` | Direct mapping when source has no dummy (`Mask_Upload_Test_V3`: index 0 = `//Mask 1`) |
| `1…728` | Usable imaging indices for the 730-mask book (index 0 is dummy) |

### 4. Run the server (with Teensy)

```bash
export RIS_TEENSY_PORT=/dev/ttyACM0   # macOS: /dev/cu.usbmodem*
export RIS_TEENSY_BAUD=921600
python run_server.py
```

Open **http://localhost:8080** for the GUI.

**Mock mode** (no USB device — GUI/API development only):

```bash
export RIS_TEENSY_MOCK=1
python run_server.py
```

**Remote access:** bind on all interfaces (default `0.0.0.0`) and open `http://<lab-pc-ip>:8080` from another machine.

### 5. Set beam index via server API

**Select codebook** (uploads to Teensy only if CRC differs, unless forced):

```bash
curl -s -X POST http://localhost:8080/api/session/select-codebook \
  -H 'Content-Type: application/json' \
  -d '{"codebook_id":"Firmware_script_plus_codewords","force_upload":false}'
```

**Apply beam index:**

```bash
curl -s -X POST http://localhost:8080/api/beam/apply \
  -H 'Content-Type: application/json' \
  -d '{"index":1}'
```

**Check status** (Teensy connection, active codebook, last applied index):

```bash
curl -s http://localhost:8080/api/status | python3 -m json.tool
```

**Force re-upload** after Teensy reboot:

```bash
curl -s -X POST http://localhost:8080/api/session/select-codebook \
  -H 'Content-Type: application/json' \
  -d '{"codebook_id":"Firmware_script_plus_codewords","force_upload":true}'

curl -s -X POST http://localhost:8080/api/beam/apply \
  -H 'Content-Type: application/json' \
  -d '{"index":1}'
```

### 6. Experiment scripts (Python client)

Prefer the HTTP client over opening serial directly — the server owns the Teensy port:

```python
from client.ris_client import RisClient

client = RisClient("http://lab-pc:8080")
client.ensure_codebook("Imaging_M260P260M520P0_STEP2cm")  # uploads only if needed
client.apply_beam(1)
```

**Beam sweep:**

```bash
export RIS_SERVER_URL=http://localhost:8080
python examples/run_beam_sweep.py \
  --codebook Imaging_M260P260M520P0_STEP2cm \
  --start 1 --end 10 \
  --dwell-ms 100
```

**Fast UDP apply** (fire-and-forget, server must be running):

```python
from client.ris_fast_client import RisFastClient

with RisFastClient("127.0.0.1", 5005) as fast:
    fast.apply_beam(42)
```

Benchmark: `python examples/bench_apply_latency.py`

## Typical lab workflow

```bash
# After Teensy power-on or reboot:
export RIS_TEENSY_PORT=/dev/ttyACM0
python run_server.py

# In another terminal — select book + apply beam 1:
curl -X POST http://localhost:8080/api/session/select-codebook \
  -H 'Content-Type: application/json' \
  -d '{"codebook_id":"Firmware_script_plus_codewords","force_upload":true}'

curl -X POST http://localhost:8080/api/beam/apply \
  -H 'Content-Type: application/json' \
  -d '{"index":1}'
```

Or without the server:

```bash
python tools/teensy_upload_cbk.py codebooks/Firmware_script_plus_codewords.cbk \
  --port /dev/ttyACM0 --apply 1

# From Mask_Upload_Test_V3.txt (after extract):
python tools/teensy_upload_cbk.py codebooks/Mask_Upload_Test_V3.cbk \
  --port /dev/ttyACM0 --apply 0   # //Mask 1
```

## API reference

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
| POST | `/api/beam/apply-fast` | Apply without waiting for hardware |
| WS | `/ws/events` | `beam_applied`, `codebook_selected`, … |

## Teensy serial protocol

Baud **921600** (ris_controller firmware). Legacy `Imaging_Empty.ino` used **115200**.

| Command | Response |
|---------|----------|
| `PING` | `PONG` |
| `STATUS` | `OK store=ram masks=N mask_bytes=1280 name=… crc=… backend=ram` |
| `CODEBOOK_BEGIN name N B crc` | `READY` → binary payload → `OK VERIFIED` |
| `APPLY 1` | `OK APPLY_QUEUED` → `OK APPLIED 1` |
| `1` (legacy) | same as `APPLY 1` |
| `CLEAR` | `OK CLEARED` |
| `ABORT` | `OK ABORTED` |

Upload sequence:

```
CODEBOOK_BEGIN Firmware_script_plus_codewords 22 1280 f064f1f4
READY
<binary payload>
OK VERIFIED
```

## Codebook format (`.cbk`)

```
[96-byte header][mask0][mask1]...[maskN-1]
```

Header: magic `RISCBK01`, `num_masks`, `mask_bytes`, `name`, `payload_crc32`.

Optional sidecar metadata: `codebooks/MyCodebook.cbk.meta.json`

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

## Visualization (64×64 RIS phase map)

The GUI decodes each mask into a **64×64** array (`0` = 0°, `1` = 180°), matching the MATLAB tile layout (20 tiles × 16×16, first 64 columns of the 64×80 stitched grid).

- **Current beam:** `last_applied_index` in `/api/status` or GUI status panel
- **Codeword count:** `usable_masks` in metadata (729 for imaging + index 0 dummy)
- **Phase map:** `GET /api/codebooks/{id}/mask/{index}/ris-map`

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

UDP packet format: `b"RI" + index.to_bytes(2, "big")`

## Architecture notes

- **Server owns codebook library** — generation, storage, selection, upload orchestration.
- **GUI is a thin client** — visualizes masks and sends high-level commands.
- **Teensy stores one active codebook in RAM** — re-upload after reboot; no flash persistence (pin 6 conflict).
- **Fast path** — when CRC matches, only `APPLY <index>` is sent (~milliseconds).

## Documentation

- **[Beam control flow](docs/beam_control_flow.md)** — diagrams from xApp/GUI through codeword lookup on Teensy.
- Export SVG/PNG: `./scripts/export_diagrams.sh` (works with `curl` only — no npm required).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `FAIL: Teensy not responding` | Close Serial Monitor / server; run `teensy_find_port.py` |
| `0 A` on panel after apply | Use index ≥ 1; re-upload codebook; confirm firmware v3 (`OK RIS_FW=3`) |
| Codebook missing after apply | Normal — USB open reboots Teensy; use `--apply N` on upload or re-select via server |
| `OK APPLY_QUEUED` but tool times out | Update to latest `tools/teensy_serial_util.py` (buffered line reader) |
| Port busy | Only one of: server, `teensy_*` tools, or Serial Monitor |
