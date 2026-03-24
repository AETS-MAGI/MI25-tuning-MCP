#!/usr/bin/env python3
"""MCP bench flow integration: bench -> phase_summary -> compare."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _assert_inner_shape(name: str, payload: dict[str, Any]) -> None:
    for key in ("content", "structuredContent", "isError"):
        if key not in payload:
            raise AssertionError(f"{name}: missing key {key}")


def _unwrap_tool_payload(call_result: Any) -> dict[str, Any]:
    sc = getattr(call_result, "structuredContent", None)
    if isinstance(sc, dict) and all(k in sc for k in ("content", "structuredContent", "isError")):
        return sc

    maybe = call_result.model_dump() if hasattr(call_result, "model_dump") else {}
    if isinstance(maybe, dict) and all(k in maybe for k in ("content", "structuredContent", "isError")):
        return maybe

    raise AssertionError("unable to unwrap tool payload")


def _assert_ok(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    _assert_inner_shape(name, payload)
    if payload.get("isError"):
        raise AssertionError(f"{name}: expected isError=false, got: {payload.get('structuredContent')}")
    sc = payload.get("structuredContent")
    if not isinstance(sc, dict):
        raise AssertionError(f"{name}: structuredContent must be object")
    return sc


async def _run() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mi25_tuning_mcp.server"],
        cwd=str(PROJECT_ROOT / "MI25-tuning-MCP"),
    )

    ts = int(time.time())
    base_out = f"worklog/mcp_bench_baseline_smoke_{ts}.tsv"
    side_out = f"worklog/mcp_bench_side_smoke_{ts}.tsv"
    compare_out = f"worklog/mcp_bench_compare_smoke_{ts}.tsv"

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # 1) baseline bench run
            baseline_result = await session.call_tool(
                "run_client_bench",
                {
                    "mode": "predict-sweep",
                    "preset": "gfx900_anchor_baseline",
                    "predict_values_csv": "64",
                    "repeat": 1,
                    "prompt": "bench flow smoke",
                    "out_path": base_out,
                    "timeout_secs": 600,
                },
            )
            baseline_payload = _unwrap_tool_payload(baseline_result)
            baseline_sc = _assert_ok("run_client_bench baseline", baseline_payload)
            base_phase = baseline_sc.get("phase_summary_path")
            if not isinstance(base_phase, str) or not Path(base_phase).exists():
                raise AssertionError(f"baseline phase_summary_path missing or not found: {base_phase}")
            print(f"[bench-flow] baseline phase summary: {base_phase}")

            # 2) side bench run
            side_result = await session.call_tool(
                "run_client_bench",
                {
                    "mode": "predict-sweep",
                    "preset": "gfx900_anchor_side1024",
                    "predict_values_csv": "64",
                    "repeat": 1,
                    "prompt": "bench flow smoke",
                    "out_path": side_out,
                    "timeout_secs": 600,
                },
            )
            side_payload = _unwrap_tool_payload(side_result)
            side_sc = _assert_ok("run_client_bench side", side_payload)
            side_phase = side_sc.get("phase_summary_path")
            if not isinstance(side_phase, str) or not Path(side_phase).exists():
                raise AssertionError(f"side phase_summary_path missing or not found: {side_phase}")
            print(f"[bench-flow] side phase summary: {side_phase}")

            # 3) compare
            compare_result = await session.call_tool(
                "run_client_bench_compare",
                {
                    "baseline_phase_summary": base_phase,
                    "side_phase_summary": side_phase,
                    "compare_out": compare_out,
                    "timeout_secs": 180,
                },
            )
            compare_payload = _unwrap_tool_payload(compare_result)
            compare_sc = _assert_ok("run_client_bench_compare", compare_payload)
            compare_path = compare_sc.get("compare_out")
            if not isinstance(compare_path, str) or not Path(compare_path).exists():
                raise AssertionError(f"compare_out missing or not found: {compare_path}")
            print(f"[bench-flow] compare summary: {compare_path}")

            print("[bench-flow] done")


def main() -> int:
    try:
        anyio.run(_run)
        return 0
    except Exception as e:
        print(f"[bench-flow] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
