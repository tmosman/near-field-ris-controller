#!/usr/bin/env bash
# Export Mermaid diagrams to SVG + PNG.
#
# Backends (first match wins):
#   1. mmdc          — npm install -g @mermaid-js/mermaid-cli
#   2. npx mmdc      — needs Node.js + npm (nodejs.org)
#   3. docker mmdc   — docker pull ghcr.io/mermaid-js/mermaid-cli/mermaid-cli
#   4. kroki.io      — curl only (default fallback, needs network)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIAG="$ROOT/docs/diagrams"

if [[ ! -d "$DIAG" ]]; then
  echo "No docs/diagrams/ directory under $ROOT" >&2
  exit 1
fi

shopt -s nullglob
files=("$DIAG"/*.mmd)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No .mmd files in $DIAG" >&2
  exit 1
fi

BACKEND=""
MMDC_CMD=()

pick_backend() {
  if command -v mmdc >/dev/null 2>&1; then
    BACKEND="mmdc"
    MMDC_CMD=(mmdc)
    return
  fi
  if command -v npx >/dev/null 2>&1; then
    BACKEND="npx"
    MMDC_CMD=(npx --yes @mermaid-js/mermaid-cli)
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    BACKEND="docker"
    return
  fi
  if command -v curl >/dev/null 2>&1; then
    BACKEND="kroki"
    return
  fi
  echo "No export backend found. Install one of:" >&2
  echo "  • Node.js + npm: https://nodejs.org  then  npm install -g @mermaid-js/mermaid-cli" >&2
  echo "  • curl (uses kroki.io — this script should work if curl is installed)" >&2
  exit 1
}

export_via_mmdc() {
  local src="$1" base="$2"
  echo "→ $base.svg"
  "${MMDC_CMD[@]}" -i "$src" -o "$DIAG/$base.svg" -b transparent
  echo "→ $base.png"
  "${MMDC_CMD[@]}" -i "$src" -o "$DIAG/$base.png" -w 2400 -b transparent
}

export_via_docker() {
  local src="$1" base="$2"
  local name
  name="$(basename "$src")"
  echo "→ $base.svg (docker)"
  docker run --rm -u "$(id -u):$(id -g)" -v "$DIAG:/data" \
    ghcr.io/mermaid-js/mermaid-cli/mermaid-cli \
    -i "/data/$name" -o "/data/$base.svg" -b transparent
  echo "→ $base.png (docker)"
  docker run --rm -u "$(id -u):$(id -g)" -v "$DIAG:/data" \
    ghcr.io/mermaid-js/mermaid-cli/mermaid-cli \
    -i "/data/$name" -o "/data/$base.png" -w 2400 -b transparent
}

export_via_kroki() {
  local src="$1" base="$2"
  echo "→ $base.svg (kroki.io)"
  curl -fsS -X POST "https://kroki.io/mermaid/svg" \
    -H "Content-Type: text/plain" \
    --data-binary @"$src" \
    -o "$DIAG/$base.svg"
  echo "→ $base.png (kroki.io)"
  curl -fsS -X POST "https://kroki.io/mermaid/png" \
    -H "Content-Type: text/plain" \
    --data-binary @"$src" \
    -o "$DIAG/$base.png"
}

pick_backend
echo "Using backend: $BACKEND"

for src in "${files[@]}"; do
  base="$(basename "$src" .mmd)"
  case "$BACKEND" in
    mmdc|npx) export_via_mmdc "$src" "$base" ;;
    docker)   export_via_docker "$src" "$base" ;;
    kroki)    export_via_kroki "$src" "$base" ;;
  esac
done

echo "Done. Files in $DIAG"
