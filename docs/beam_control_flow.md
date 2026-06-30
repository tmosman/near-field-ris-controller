# Beam control flow (ris_controller)

This document describes how a **beam index** becomes a **RIS phase configuration** in the full `ris_controller` stack. The server owns codebooks; the Teensy stores one active codebook and looks up codewords at runtime.

**Related project:** **RIS TCP Controller** (`ris_server.py`) is a thin TCP proxy for near-RT RIC xApps — see its `docs/beam_control_flow.md`.

---

## How this stack differs from RIS TCP Controller

| | **ris_controller** (this repo) | **RIS TCP Controller** |
|---|--------------------------------|------------------------|
| Entry | HTTP :8080, WebSocket, UDP :5005 | TCP :9999 (`RIS42`) |
| Codebooks | Server library `.cbk`, upload to Teensy | None — assumes Teensy already loaded |
| GUI | Web UI, 64×64 phase maps | None |
| Serial | `APPLY 42` or `42\n`, 921600 baud | `42\n` only, 115200 default |
| Camera | — | Optional ZED `CAP` command |

Both talk to the **same Teensy firmware** (`firmware/ris_controller/`) for codeword lookup and shift-register output.

---

## 1. System overview

Source: [`diagrams/overview.mmd`](diagrams/overview.mmd)

```mermaid
flowchart TB
    subgraph clients["Clients"]
        GUI["RIS GUI<br/>(browser)"]
        HTTP["RisClient / curl<br/>HTTP :8080"]
        UDP["RisFastClient<br/>UDP :5005"]
    end

    subgraph server["ris_controller server (Python)"]
        API["Starlette REST + WebSocket"]
        CB["CodebookManager<br/>codebooks/*.cbk"]
        TC["TeensyClient"]
        UL["UdpBeamListener"]
        API --> CB
        API --> TC
        UL --> TC
    end

    subgraph teensy["Teensy 4.1 — firmware/ris_controller"]
        SER["Serial parser<br/>APPLY 42 or 42"]
        Q["Apply queue"]
        ST["codebook_store<br/>QSPI flash lookup"]
        SH["shift_driver<br/>20 GPIO → registers"]
        SER --> Q --> ST --> SH
    end

    subgraph ris["RIS hardware"]
        HW["64×64 phase panel"]
    end

    GUI -->|"POST select-codebook<br/>POST beam/apply"| API
    HTTP --> API
    UDP -->|"RI + uint16_be"| UL
    CB -->|"CODEBOOK_BEGIN + binary<br/>(if CRC differs)"| TC
    API -->|"APPLY / legacy index"| TC
    TC -->|"USB serial 921600"| SER
    SH --> HW
```

---

## 2. Codebook setup (one-time per session)

Before real-time beam switching, the active `.cbk` must be on the Teensy. The server compares CRC via `STATUS` and uploads only when needed.

Source: [`diagrams/codebook_setup.mmd`](diagrams/codebook_setup.mmd)

```mermaid
sequenceDiagram
    participant GUI as RIS GUI / RisClient
    participant S as Starlette server
    participant M as CodebookManager
    participant CB as codebooks/*.cbk
    participant T as Teensy firmware
    participant F as QSPI flash

    GUI->>S: POST /api/session/select-codebook
    S->>M: raw_payload(codebook_id)
    M->>CB: read header + masks
    CB-->>M: e.g. 730 masks × 1280 B
    S->>T: STATUS
    T-->>S: crc, num_masks, name

    alt CRC mismatch or force_upload
        S->>T: CODEBOOK_BEGIN name 730 1280 crc
        T-->>S: READY
        S->>T: binary payload (chunks)
        T->>F: storeWriteChunk → verify CRC
        T-->>S: OK VERIFIED
    else CRC matches
        Note over S,T: Skip upload — Teensy already has codebook
    end

    S->>M: set_active(codebook_id)
    S-->>GUI: codebook_selected
```

---

## 3. Runtime: index → codeword → RIS

Source: [`diagrams/runtime_sequence.mmd`](diagrams/runtime_sequence.mmd)

```mermaid
sequenceDiagram
    participant C as Client (HTTP or UDP)
    participant S as ris_controller server
    participant Ser as USB serial
    participant P as protocol.cpp
    participant Store as codebook_store.cpp
    participant Shift as shift_driver.cpp
    participant RIS as RIS panel

  rect rgb(240, 248, 255)
    Note over C,S: Fast path — UDP or apply-fast (no hardware wait)
    C->>S: UDP RI+index or POST /api/beam/apply-fast
    S->>Ser: "42\\n" (fire-and-forget)
    Ser->>P: handleApply(42) → enqueue
    P-->>S: OK APPLY_QUEUED
  end

  rect rgb(255, 248, 240)
    Note over C,S: Standard path — waits for shift complete
    C->>S: POST /api/beam/apply {"index":42}
    S->>Ser: APPLY 42
    Ser->>P: handleApply(42) → enqueue
    P-->>S: OK APPLY_QUEUED
  end

    P->>Store: storeReadMask(42, scratch, 1280)
    Store->>Store: offset = base + 42 × 1280
    Store-->>P: codeword (mask #42)

    P->>Shift: shiftOutputFromBuffer(scratch, 1280)
    loop 64 rows × 8 bit planes
        Shift->>RIS: clock 20 data pins + latch
    end
    P-->>S: OK APPLIED 42
    S-->>C: applied index (HTTP only)
```

### Latency tiers

| Path | Typical latency | Waits for hardware shift? |
|------|-----------------|---------------------------|
| `POST /api/beam/apply` | 2–20 ms | Yes (~30 ms) |
| `POST /api/beam/apply-fast` | 0.3–2 ms | No |
| UDP `RI` + uint16 → :5005 | 50–500 µs (localhost) | No |

Hardware programming remains **~25–50 ms** regardless of API.

---

## 4. Codeword lookup on Teensy

Source: [`diagrams/codeword_lookup.mmd`](diagrams/codeword_lookup.mmd)

```mermaid
flowchart LR
    IDX["beam_index = 42"]
    META["Active codebook meta<br/>num_masks, mask_bytes=1280"]
    CALC["flash offset =<br/>data_base + 42 × 1280"]
    MASK["mask[42]<br/>1280-byte codeword"]
    BUF["maskScratch[]"]
    SHIFT["shiftOutputFromBuffer<br/>bit-serialize to 20 GPIO"]
    RIS["64×64 phase pattern<br/>0° / 180° per element"]

    IDX --> CALC
    META --> CALC
    CALC --> MASK --> BUF --> SHIFT --> RIS
```

| Concept | Detail |
|---------|--------|
| **Beam index** | Integer 0 … N−1 (e.g. 729 usable + dummy at 0) |
| **Codeword** | `mask[index]` — 1280-byte bit-packed phase map |
| **Storage** | QSPI flash on Teensy 4.1 (`codebook_store.cpp`) |
| **Apply** | `shift_driver.cpp` clocks bits into motherboard shift registers |

---

## Exporting diagrams for papers / PDFs

Diagram sources live in [`docs/diagrams/`](diagrams/) as `.mmd` files.

```bash
./scripts/export_diagrams.sh
```

The script picks the first available backend:

| Backend | Requires |
|---------|----------|
| **kroki.io** (fallback) | `curl` + network — **no npm needed** |
| `mmdc` | `npm install -g @mermaid-js/mermaid-cli` |
| `npx` | [Node.js](https://nodejs.org) (includes npm) |
| Docker | `docker pull ghcr.io/mermaid-js/mermaid-cli/mermaid-cli` |

- **SVG** — best for LaTeX, Word (if supported), high-quality PDF
- **PNG** — slides, Confluence

**No npm?** Just run `./scripts/export_diagrams.sh` — it uses [kroki.io](https://kroki.io) automatically.

**One-off (manual):** paste a `.mmd` file into [mermaid.live](https://mermaid.live) → Export SVG/PNG.

GitHub renders the Mermaid blocks in this file directly; committed `.svg` files are optional for offline readers.
