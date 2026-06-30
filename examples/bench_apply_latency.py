#!/usr/bin/env python3
"""Benchmark beam apply latency: HTTP vs UDP fast path."""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from client.ris_client import RisClient  # noqa: E402
from client.ris_fast_client import RisFastClient  # noqa: E402


def bench_http(server: str, index: int, n: int, fast: bool) -> list[float]:
    client = RisClient(server)
    times: list[float] = []
    path = f"/api/beam/apply{'?fast=1' if fast else ''}"
    for _ in range(n):
        t0 = time.perf_counter()
        if fast:
            import json
            import urllib.request

            req = urllib.request.Request(
                f"{server.rstrip('/')}{path}",
                data=json.dumps({"index": index}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        else:
            client.apply_beam(index)
        times.append(time.perf_counter() - t0)
    return times


def bench_udp(host: str, port: int, index: int, n: int) -> list[float]:
    with RisFastClient(host, port) as client:
        return [client.apply_beam_timed(index) for _ in range(n)]


def report(label: str, times: list[float]) -> None:
    us = [t * 1e6 for t in times]
    print(
        f"{label}: median={statistics.median(us):.0f} µs  "
        f"p95={sorted(us)[int(0.95 * len(us)) - 1]:.0f} µs  "
        f"min={min(us):.0f} µs"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=1)
    parser.add_argument("-n", type=int, default=50)
    parser.add_argument("--server", default=os.getenv("RIS_SERVER_URL", "http://localhost:8080"))
    parser.add_argument("--udp-host", default=os.getenv("RIS_UDP_HOST", "127.0.0.1"))
    parser.add_argument("--udp-port", type=int, default=int(os.getenv("RIS_UDP_PORT", "5005")))
    args = parser.parse_args()

    report("HTTP apply (waits hardware)", bench_http(args.server, args.index, args.n, fast=False))
    report("HTTP apply?fast=1", bench_http(args.server, args.index, args.n, fast=True))
    report("UDP fire-and-forget", bench_udp(args.udp_host, args.udp_port, args.index, args.n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
