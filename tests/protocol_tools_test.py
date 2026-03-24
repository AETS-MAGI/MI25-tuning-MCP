#!/usr/bin/env python3
"""MCP protocol test using stdio transport (tools/list + tools/call)."""

from __future__ import annotations

import sys
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
    """
    FastMCP returns CallToolResult where structuredContent may embed the tool payload.
    We normalize to the inner {content, structuredContent, isError} shape.
    """
    sc = getattr(call_result, "structuredContent", None)
    if isinstance(sc, dict) and all(k in sc for k in ("content", "structuredContent", "isError")):
        return sc

    # Fallback when server returns raw shape directly.
    maybe = call_result.model_dump() if hasattr(call_result, "model_dump") else {}
    if isinstance(maybe, dict) and all(k in maybe for k in ("content", "structuredContent", "isError")):
        return maybe

    raise AssertionError("unable to unwrap tool payload")


async def _run() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mi25_tuning_mcp.server"],
        cwd=str(PROJECT_ROOT / "MI25-tuning-MCP"),
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            print(f"[protocol] initialized: protocolVersion={init.protocolVersion}")

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            required = {
                "ping",
                "get_gpu_metrics",
                "get_config",
                "update_config",
                "run_inference",
                "run_client_bench",
                "run_client_bench_compare",
                "read_perf_log",
                "summarize_perf_log",
            }
            missing = sorted(required - names)
            if missing:
                raise AssertionError(f"missing tools: {missing}")
            print(f"[protocol] tools/list: ok ({len(names)} tools)")

            ping_result = await session.call_tool("ping", {})
            ping_payload = _unwrap_tool_payload(ping_result)
            _assert_inner_shape("ping", ping_payload)
            if ping_payload.get("isError"):
                raise AssertionError("ping returned isError=true")
            print("[protocol] tools/call ping: ok")

            read_result = await session.call_tool(
                "read_text",
                {"path": "MI25-tuning-MCP/README.md", "max_chars": 120},
            )
            read_payload = _unwrap_tool_payload(read_result)
            _assert_inner_shape("read_text", read_payload)
            print(f"[protocol] tools/call read_text: ok (isError={read_payload.get('isError')})")

            invalid_result = await session.call_tool(
                "update_config",
                {"overrides": {"__invalid_key__": 1}},
            )
            invalid_payload = _unwrap_tool_payload(invalid_result)
            _assert_inner_shape("update_config invalid", invalid_payload)
            if not invalid_payload.get("isError"):
                raise AssertionError("update_config invalid must be isError=true")
            err = invalid_payload.get("structuredContent", {}).get("error", {})
            if err.get("code") != "allowlist_violation":
                raise AssertionError(f"unexpected error code: {err}")
            print("[protocol] tools/call update_config invalid: ok")

            raw_result = await session.call_tool("set_config_raw", {"config_json": "{}"})
            raw_payload = _unwrap_tool_payload(raw_result)
            _assert_inner_shape("set_config_raw", raw_payload)
            err = raw_payload.get("structuredContent", {}).get("error", {})
            if err.get("code") != "disabled_by_policy":
                raise AssertionError(f"expected disabled_by_policy, got: {err}")
            print("[protocol] tools/call set_config_raw policy guard: ok")

            bench_invalid = await session.call_tool(
                "run_client_bench",
                {"mode": "__invalid_mode__"},
            )
            bench_invalid_payload = _unwrap_tool_payload(bench_invalid)
            _assert_inner_shape("run_client_bench invalid", bench_invalid_payload)
            if not bench_invalid_payload.get("isError"):
                raise AssertionError("run_client_bench invalid must be isError=true")
            bench_err = bench_invalid_payload.get("structuredContent", {}).get("error", {})
            if bench_err.get("code") != "invalid_argument":
                raise AssertionError(f"unexpected bench error code: {bench_err}")
            print("[protocol] tools/call run_client_bench invalid: ok")

            compare_invalid = await session.call_tool(
                "run_client_bench_compare",
                {
                    "baseline_phase_summary": "worklog/no-baseline.tsv",
                    "side_phase_summary": "worklog/no-side.tsv",
                },
            )
            compare_invalid_payload = _unwrap_tool_payload(compare_invalid)
            _assert_inner_shape("run_client_bench_compare invalid", compare_invalid_payload)
            if not compare_invalid_payload.get("isError"):
                raise AssertionError("run_client_bench_compare invalid must be isError=true")
            compare_err = compare_invalid_payload.get("structuredContent", {}).get("error", {})
            if compare_err.get("code") not in {"not_found", "invalid_path"}:
                raise AssertionError(f"unexpected compare error code: {compare_err}")
            print("[protocol] tools/call run_client_bench_compare invalid: ok")


def main() -> int:
    try:
        anyio.run(_run)
        print("[protocol] done")
        return 0
    except Exception as e:
        print(f"[protocol] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
