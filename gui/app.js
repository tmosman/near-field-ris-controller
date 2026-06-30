const STORAGE_KEY = "ris_api_base";

const state = {
  codebooks: [],
  activeCodebookId: null,
  selectedIndex: 1,
  appliedIndex: null,
  gridSide: null,
  ws: null,
};

const els = {
  serverUrl: document.getElementById("server-url"),
  statusList: document.getElementById("status-list"),
  codebookSelect: document.getElementById("codebook-select"),
  codebookMeta: document.getElementById("codebook-meta"),
  beamIndex: document.getElementById("beam-index"),
  beamStatus: document.getElementById("beam-status"),
  beamGrid: document.getElementById("beam-grid"),
  tileGrid: document.getElementById("tile-grid"),
  maskMeta: document.getElementById("mask-meta"),
  risMeta: document.getElementById("ris-meta"),
  risCanvas: document.getElementById("ris-canvas"),
  wsStatus: document.getElementById("ws-status"),
};

function getQueryServer() {
  const params = new URLSearchParams(location.search);
  return params.get("server") || "";
}

function getApiBase() {
  const stored = localStorage.getItem(STORAGE_KEY) || "";
  const fromInput = els.serverUrl.value.trim();
  return (fromInput || stored || getQueryServer()).replace(/\/$/, "");
}

function apiUrl(path) {
  const base = getApiBase();
  return base ? `${base}${path}` : path;
}

function wsUrl() {
  const base = getApiBase();
  if (base) {
    const url = new URL(base);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/ws/events";
    url.search = "";
    url.hash = "";
    return url.toString();
  }
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws/events`;
}

async function api(path, options = {}) {
  const response = await fetch(apiUrl(path), options);
  if (!response.ok) {
    const detail = await response.text();
    let message = detail || response.statusText;
    try {
      const parsed = JSON.parse(detail);
      if (parsed.detail) message = parsed.detail;
    } catch {
      // keep raw text
    }
    throw new Error(message);
  }
  return response.json();
}

function renderStatus(data) {
  const rows = [
    ["Server", getApiBase() || location.origin],
    ["Teensy", data.teensy_connected ? "connected" : "disconnected"],
    ["Mode", data.teensy_mock ? "mock" : "hardware"],
    ["Port", data.teensy_port || "n/a"],
    ["Active codebook", data.active_codebook_name || "none"],
    ["Codewords on Teensy", String(data.teensy_masks)],
    ["Current beam index", data.last_applied_index ?? "none"],
    ["Teensy CRC", data.teensy_crc || "none"],
  ];
  els.statusList.innerHTML = rows
    .map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`)
    .join("");
  state.activeCodebookId = data.active_codebook_id;
  state.appliedIndex = data.last_applied_index;
}

async function loadStatus() {
  const data = await api("/api/status");
  renderStatus(data);
}

async function loadCodebooks() {
  state.codebooks = await api("/api/codebooks");
  els.codebookSelect.innerHTML = state.codebooks
    .map(
      (cb) =>
        `<option value="${cb.id}">${cb.name} (${cb.num_masks} masks)${
          cb.on_teensy ? " • on Teensy" : ""
        }</option>`
    )
    .join("");

  if (state.codebooks.length > 0) {
    const selected =
      state.activeCodebookId && state.codebooks.some((c) => c.id === state.activeCodebookId)
        ? state.activeCodebookId
        : state.codebooks[0].id;
    els.codebookSelect.value = selected;
    await loadCodebookMeta(selected);
  }
}

async function loadCodebookMeta(codebookId) {
  const meta = await api(`/api/codebooks/${codebookId}`);
  state.gridSide = meta.codeword_grid_cols || meta.grid_side;
  const usable = meta.usable_masks ?? (meta.num_masks > 0 ? meta.num_masks - 1 : 0);
  els.codebookMeta.textContent =
    `${meta.name} | ${meta.num_masks} masks (${usable} codewords + dummy) | ` +
    `${meta.ris_rows}×${meta.ris_cols} RIS | crc=${meta.payload_crc32}`;
  renderBeamGrid(meta.num_masks, state.gridSide);
}

function renderBeamGrid(numMasks, gridSide) {
  const side = gridSide || Math.ceil(Math.sqrt(numMasks));
  els.beamGrid.style.gridTemplateColumns = `repeat(${side}, 18px)`;
  els.beamGrid.innerHTML = "";

  for (let index = 0; index < numMasks; index++) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "beam-cell";
    cell.title = `Index ${index}`;
    cell.textContent = index % 27 === 0 ? String(index) : "";
    if (index === state.selectedIndex) cell.classList.add("active");
    if (index === state.appliedIndex) cell.classList.add("applied");
    cell.addEventListener("click", async () => {
      state.selectedIndex = index;
      els.beamIndex.value = index;
      renderBeamGrid(numMasks, gridSide);
      await previewMask(index);
      await applyBeam();
    });
    els.beamGrid.appendChild(cell);
  }
}

function renderRisMap(risData) {
  const {
    index,
    ris_rows: rows,
    ris_cols: cols,
    phases,
    active_180deg_count: count180,
    active_0deg_count: count0,
    codeword_grid_row: gridRow,
    codeword_grid_col: gridCol,
    is_dummy: isDummy,
  } = risData;

  const gridLabel =
    gridRow !== null && gridCol !== null
      ? `codeword grid (${gridRow}, ${gridCol})`
      : isDummy
        ? "dummy mask"
        : "codeword grid n/a";

  els.risMeta.textContent =
    `Beam ${index} | 64×64 RIS | ${gridLabel} | 0°=${count0} cells, 180°=${count180} cells`;

  const canvas = els.risCanvas;
  const ctx = canvas.getContext("2d");
  const scale = Math.floor(canvas.width / cols);
  const height = scale * rows;
  canvas.height = height;

  const color0 = "#1f6feb";
  const color180 = "#f0883e";

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      ctx.fillStyle = phases[r][c] ? color180 : color0;
      ctx.fillRect(c * scale, r * scale, scale, scale);
    }
  }
}

function renderTileVisualization(maskData) {
  const { index, tiles, bits_per_tile, bitplanes, grid_row, grid_col } = maskData;
  const pos =
    grid_row !== null ? `grid (${grid_row}, ${grid_col})` : "non-square codebook";
  els.maskMeta.textContent = `Index ${index} | ${tiles} tiles × ${bits_per_tile} bits | ${pos}`;

  els.tileGrid.innerHTML = bitplanes
    .map((bits, tileIdx) => {
      const cols = Math.min(16, Math.max(8, Math.round(Math.sqrt(bits.length))));
      const cells = bits
        .map((bit) => `<div class="${bit ? "bit-on" : "bit-off"}"></div>`)
        .join("");
      return `
        <div class="tile-card">
          <h4>Tile ${tileIdx + 1}</h4>
          <div class="bit-grid" style="grid-template-columns: repeat(${cols}, 6px)">${cells}</div>
        </div>`;
    })
    .join("");
}

async function previewMask(index) {
  const codebookId = els.codebookSelect.value;
  const [maskData, risData] = await Promise.all([
    api(`/api/codebooks/${codebookId}/mask/${index}`),
    api(`/api/codebooks/${codebookId}/mask/${index}/ris-map`),
  ]);
  renderRisMap(risData);
  renderTileVisualization(maskData);
}

async function activateCodebook() {
  const codebookId = els.codebookSelect.value;
  els.codebookMeta.textContent = "Uploading / activating…";
  const result = await ensureActiveCodebook(document.getElementById("force-upload").checked);
  els.codebookMeta.textContent = `Activated ${codebookId} (uploaded=${result.uploaded})`;
  await loadStatus();
  await loadCodebooks();
}

async function ensureActiveCodebook(forceUpload = false) {
  const codebookId = els.codebookSelect.value;
  return api("/api/session/select-codebook", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codebook_id: codebookId, force_upload: forceUpload }),
  });
}

async function applyBeam() {
  const index = Number(els.beamIndex.value);
  const forceUpload = document.getElementById("force-upload").checked;
  els.beamStatus.textContent = "Ensuring codebook on Teensy…";
  try {
    await ensureActiveCodebook(forceUpload);
    els.beamStatus.textContent = `Applying index ${index}…`;
    const result = await api("/api/beam/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index }),
    });
    state.appliedIndex = result.index;
    state.selectedIndex = result.index;
    els.beamStatus.innerHTML = `<span class="ok">Applied index ${result.index}</span>`;
    const meta = await api(`/api/codebooks/${els.codebookSelect.value}`);
    renderBeamGrid(meta.num_masks, meta.grid_side);
    await previewMask(result.index);
    await loadStatus();
  } catch (error) {
    els.beamStatus.innerHTML = `<span class="err">${error.message}</span>`;
  }
}

function connectEvents() {
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }

  const ws = new WebSocket(wsUrl());
  state.ws = ws;

  ws.onopen = () => {
    els.wsStatus.textContent = `WS: connected (${getApiBase() || location.host})`;
  };
  ws.onclose = () => {
    els.wsStatus.textContent = "WS: disconnected";
  };
  ws.onmessage = async (event) => {
    const message = JSON.parse(event.data);
    if (message.event === "beam_applied") {
      state.appliedIndex = message.data.index;
      state.selectedIndex = message.data.index;
      els.beamIndex.value = message.data.index;
      await loadStatus();
      const meta = await api(`/api/codebooks/${els.codebookSelect.value}`);
      renderBeamGrid(meta.num_masks, meta.codeword_grid_cols || meta.grid_side);
      await previewMask(message.data.index);
    }
    if (message.event === "codebook_selected" || message.event === "codebook_uploaded") {
      await loadCodebooks();
      await loadStatus();
    }
  };
}

function initServerUrl() {
  const initial = getQueryServer() || localStorage.getItem(STORAGE_KEY) || "";
  els.serverUrl.value = initial;
}

async function saveServerAndReconnect() {
  const value = els.serverUrl.value.trim();
  if (value) {
    localStorage.setItem(STORAGE_KEY, value);
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
  connectEvents();
  await loadStatus();
  await loadCodebooks();
  if (els.codebookSelect.value) {
    await previewMask(Number(els.beamIndex.value));
  }
}

document.getElementById("refresh-status").addEventListener("click", loadStatus);
document.getElementById("save-server").addEventListener("click", () => {
  saveServerAndReconnect().catch((error) => {
    els.beamStatus.innerHTML = `<span class="err">Connect failed: ${error.message}</span>`;
  });
});
document.getElementById("activate-codebook").addEventListener("click", activateCodebook);
document.getElementById("apply-beam").addEventListener("click", applyBeam);
els.codebookSelect.addEventListener("change", async (event) => {
  await loadCodebookMeta(event.target.value);
  await previewMask(Number(els.beamIndex.value));
});
document.getElementById("codebook-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  await api("/api/codebooks/upload", { method: "POST", body });
  await loadCodebooks();
});

async function boot() {
  initServerUrl();
  connectEvents();
  await loadStatus();
  await loadCodebooks();
  if (els.codebookSelect.value) {
    await previewMask(Number(els.beamIndex.value));
  }
}

boot().catch((error) => {
  els.beamStatus.innerHTML = `<span class="err">Boot failed: ${error.message}</span>`;
});
