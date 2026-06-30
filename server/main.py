from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.codebook_format import extract_mask, grid_side, mask_to_bitplanes  # noqa: E402
from shared.mask_decode import summarize_mask  # noqa: E402

from .codebook_manager import CodebookManager  # noqa: E402
from .config import CORS_ORIGINS, FAST_SKIP_CRC_CHECK, GUI_DIR, TEENSY_MOCK, TEENSY_PORT, UDP_CONTROL_PORT  # noqa: E402
from .fast_control import UdpBeamListener  # noqa: E402
from .models import CodebookInfo, MaskVisualization, SystemStatus, to_json  # noqa: E402
from .teensy_client import create_teensy_client  # noqa: E402

manager = CodebookManager()
teensy = create_teensy_client()
udp_listener = UdpBeamListener(teensy, manager)
event_clients: set[WebSocket] = set()


async def broadcast(event: str, payload: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in event_clients:
        try:
            await ws.send_json({"event": event, "data": payload})
        except Exception:
            dead.append(ws)
    for ws in dead:
        event_clients.discard(ws)


async def startup() -> None:
    try:
        teensy.connect()
    except Exception as exc:
        print(f"Warning: Teensy connect failed: {exc}")
    udp_listener.start()
    print(f"UDP fast beam control on port {UDP_CONTROL_PORT} (4-byte RI+index packets)")


async def shutdown() -> None:
    udp_listener.stop()
    teensy.disconnect()


async def get_status(_: Request) -> JSONResponse:
    teensy_status = teensy.get_status()
    active_id = manager.active_codebook_id
    active_name = None
    if active_id:
        try:
            active_name = manager.get_header(active_id).name
        except FileNotFoundError:
            active_id = None

    status = SystemStatus(
        teensy_connected=teensy_status.connected,
        teensy_mock=TEENSY_MOCK or not TEENSY_PORT,
        teensy_port=TEENSY_PORT or None,
        active_codebook_id=active_id,
        active_codebook_name=active_name,
        teensy_masks=teensy_status.masks,
        teensy_mask_bytes=teensy_status.mask_bytes,
        teensy_crc=teensy_status.crc,
        last_applied_index=teensy.last_applied,
    )
    return JSONResponse(to_json(status))


async def list_codebooks(_: Request) -> JSONResponse:
    teensy_status = teensy.get_status()
    teensy_crc = (teensy_status.crc or "").lower() if teensy_status.connected else None
    items = manager.list_codebooks()
    for item in items:
        item["on_teensy"] = (
            teensy_crc is not None
            and item["payload_crc32"].lower() == teensy_crc
        )
    return JSONResponse([to_json(CodebookInfo(**item)) for item in items])


async def upload_codebook(request: Request) -> JSONResponse:
    form = await request.form()
    upload = form["file"]
    codebook_id = form.get("codebook_id")
    temp_path = manager.root / f"_upload_{upload.filename}"
    content = await upload.read()
    temp_path.write_bytes(content)
    try:
        info = manager.import_file(temp_path, codebook_id=codebook_id or None)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    await broadcast("codebook_uploaded", info)
    return JSONResponse(to_json(CodebookInfo(**info)))


async def get_codebook_metadata(request: Request) -> JSONResponse:
    codebook_id = request.path_params["codebook_id"]
    return JSONResponse(manager.metadata_for_gui(codebook_id))


async def get_mask(request: Request) -> JSONResponse:
    codebook_id = request.path_params["codebook_id"]
    index = int(request.path_params["index"])
    header = manager.get_header(codebook_id)
    _, payload = manager.raw_payload(codebook_id)
    mask = extract_mask(payload, header, index)
    planes = mask_to_bitplanes(mask, tiles=20)
    side = grid_side(header.num_masks)
    row = col = None
    if side:
        row = index // side
        col = index % side
    viz = MaskVisualization(
        index=index,
        mask_bytes=header.mask_bytes,
        tiles=20,
        bits_per_tile=len(planes[0]) if planes else 0,
        bitplanes=planes,
        grid_side=side,
        grid_row=row,
        grid_col=col,
    )
    return JSONResponse(to_json(viz))


async def select_codebook(request: Request) -> JSONResponse:
    body = await request.json()
    codebook_id = body["codebook_id"]
    force_upload = bool(body.get("force_upload", False))

    header, payload = manager.raw_payload(codebook_id)
    teensy_status = teensy.get_status()
    crc = f"{header.payload_crc32:08x}"
    teensy_crc = (teensy_status.crc or "").lower()
    needs_upload = force_upload or not teensy_status.connected or teensy_crc != crc

    if needs_upload:
        try:
            await asyncio.to_thread(teensy.upload_codebook, header, payload)
        except TimeoutError as exc:
            return JSONResponse(
                {
                    "detail": (
                        f"{exc}. Stop the server, set RIS_TEENSY_PORT to the correct "
                        f"/dev/ttyACM* (see tools/teensy_find_port.py), restart the server, "
                        "or upload directly: python tools/teensy_upload_cbk.py codebooks/….cbk"
                    )
                },
                status_code=504,
            )
        except RuntimeError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=502)

    manager.set_active(codebook_id)
    result = {"codebook_id": codebook_id, "uploaded": needs_upload, "crc": crc}
    await broadcast("codebook_selected", result)
    return JSONResponse(result)


async def apply_beam(request: Request) -> JSONResponse:
    body = await request.json()
    index = int(body["index"])
    fast = request.query_params.get("fast", "0") == "1"
    return await _apply_beam_index(index, wait_hardware=not fast)


async def apply_beam_fast(request: Request) -> JSONResponse:
    """Low-latency apply: skips CRC check, does not wait for hardware shift."""
    raw = await request.body()
    if len(raw) == 2:
        index = int.from_bytes(raw, "big")
    elif raw:
        index = int(raw.decode("ascii").strip())
    else:
        return JSONResponse({"detail": "Send 2-byte big-endian index or ASCII integer"}, status_code=400)
    return await _apply_beam_index(index, wait_hardware=False, skip_crc=True)


async def _apply_beam_index(
    index: int,
    wait_hardware: bool = True,
    skip_crc: bool = False,
) -> JSONResponse:
    active_id = manager.active_codebook_id
    if not active_id:
        return JSONResponse({"detail": "No active codebook selected"}, status_code=400)

    max_index = manager.active_max_index
    if max_index is None or index < 0 or index >= max_index:
        return JSONResponse({"detail": "Beam index out of range"}, status_code=400)

    if not skip_crc and not FAST_SKIP_CRC_CHECK:
        header = manager.get_header(active_id)
        teensy_status = teensy.get_status()
        teensy_crc = (teensy_status.crc or "").lower()
        expected_crc = f"{header.payload_crc32:08x}"
        if teensy_crc != expected_crc:
            return JSONResponse(
                {"detail": "Teensy codebook mismatch. Select codebook again to upload."},
                status_code=409,
            )

    try:
        if wait_hardware:
            applied = await asyncio.to_thread(teensy.apply_index, index)
        else:
            await asyncio.to_thread(teensy.send_index_fire_and_forget, index)
            applied = index
    except TimeoutError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=504)
    except RuntimeError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    payload = {"index": applied, "codebook_id": active_id, "wait_hardware": wait_hardware}
    asyncio.create_task(broadcast("beam_applied", payload))
    return JSONResponse(payload)


async def events_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    event_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        event_clients.discard(websocket)


async def get_mask_ris_map(request: Request) -> JSONResponse:
    codebook_id = request.path_params["codebook_id"]
    index = int(request.path_params["index"])
    header = manager.get_header(codebook_id)
    if index < 0 or index >= header.num_masks:
        return JSONResponse({"detail": "Mask index out of range"}, status_code=400)

    meta = manager.get_codebook_metadata(codebook_id)
    _, payload = manager.raw_payload(codebook_id)
    mask = extract_mask(payload, header, index)
    return JSONResponse(summarize_mask(mask, index, meta))


async def get_codebook_meta(request: Request) -> JSONResponse:
    codebook_id = request.path_params["codebook_id"]
    meta = manager.get_codebook_metadata(codebook_id)
    header = manager.get_header(codebook_id)
    payload = meta.to_dict()
    payload.update(
        {
            "id": codebook_id,
            "name": header.name,
            "num_masks": header.num_masks,
            "mask_bytes": header.mask_bytes,
        }
    )
    return JSONResponse(payload)


async def root(_: Request) -> FileResponse:
    return FileResponse(GUI_DIR / "index.html")


routes = [
    Route("/", endpoint=root),
    Route("/api/status", get_status),
    Route("/api/codebooks", list_codebooks),
    Route("/api/codebooks/upload", upload_codebook, methods=["POST"]),
    Route("/api/codebooks/{codebook_id}", get_codebook_metadata),
    Route("/api/codebooks/{codebook_id}/mask/{index}", get_mask),
    Route("/api/codebooks/{codebook_id}/mask/{index}/ris-map", get_mask_ris_map),
    Route("/api/codebooks/{codebook_id}/meta", get_codebook_meta),
    Route("/api/session/select-codebook", select_codebook, methods=["POST"]),
    Route("/api/beam/apply", apply_beam, methods=["POST"]),
    Route("/api/beam/apply-fast", apply_beam_fast, methods=["POST"]),
    WebSocketRoute("/ws/events", endpoint=events_socket),
    Mount("/gui", app=StaticFiles(directory=str(GUI_DIR), html=True), name="gui"),
]

app = Starlette(routes=routes, on_startup=[startup], on_shutdown=[shutdown])

_cors_origins = ["*"] if CORS_ORIGINS.strip() == "*" else [
    origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
