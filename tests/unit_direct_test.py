#!/usr/bin/env python3
"""MCP unit test by directly calling Python tool functions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mi25_tuning_mcp import server


def _fail(message: str) -> None:
    print(f"[unit] FAIL: {message}")
    raise AssertionError(message)


def _assert_shape(name: str, result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        _fail(f"{name}: result is not dict")
    for key in ("content", "structuredContent", "isError"):
        if key not in result:
            _fail(f"{name}: missing key: {key}")


def _error_code(result: dict[str, Any]) -> str | None:
    sc = result.get("structuredContent", {})
    if not isinstance(sc, dict):
        return None
    err = sc.get("error")
    if not isinstance(err, dict):
        return None
    code = err.get("code")
    return str(code) if code is not None else None


def _run_case(name: str, fn, expected_error_code: str | None = None) -> None:
    result = fn()
    _assert_shape(name, result)
    if expected_error_code is None:
        print(f"[unit] {name}: ok (isError={result['isError']})")
        return

    if not result.get("isError"):
        _fail(f"{name}: expected isError=True")
    code = _error_code(result)
    if code != expected_error_code:
        _fail(f"{name}: expected error.code={expected_error_code}, got {code}")
    print(f"[unit] {name}: ok (error.code={code})")


def main() -> int:
    try:
        _run_case("ping", lambda: server.ping())
        _run_case("get_gpu_metrics", lambda: server.get_gpu_metrics(timeout_secs=5))
        _run_case("list_presets", lambda: server.list_presets())
        _run_case("get_config", lambda: server.get_config())
        _run_case("read_perf_log", lambda: server.read_perf_log(n=1))
        _run_case("summarize_perf_log", lambda: server.summarize_perf_log(n=1))
        _run_case("list_dir", lambda: server.list_dir(path="MI25-tuning-MCP", max_entries=5))
        _run_case("read_text", lambda: server.read_text(path="MI25-tuning-MCP/README.md", max_chars=200))
        _run_case("run_client_check", lambda: server.run_client_check(timeout_secs=10, max_output_chars=400))

        # Failure-path checks
        _run_case(
            "update_config_allowlist_violation",
            lambda: server.update_config({"__invalid_key__": 1}),
            expected_error_code="allowlist_violation",
        )
        _run_case(
            "read_text_invalid_path",
            lambda: server.read_text("../outside.txt"),
            expected_error_code="invalid_path",
        )
        _run_case(
            "read_perf_log_invalid_argument",
            lambda: server.read_perf_log(n=0),
            expected_error_code="invalid_argument",
        )
        _run_case(
            "summarize_perf_log_invalid_argument",
            lambda: server.summarize_perf_log(n=0),
            expected_error_code="invalid_argument",
        )
        _run_case(
            "set_config_raw_disabled_by_policy",
            lambda: server.set_config_raw("{}"),
            expected_error_code="disabled_by_policy",
        )

        audit = Path(server.AUDIT_LOG_PATH)
        if not audit.exists():
            _fail(f"audit log not found: {audit}")
        last = audit.read_text(encoding="utf-8").splitlines()[-1]
        json.loads(last)
        print(f"[unit] audit log: ok ({audit})")
        print("[unit] done")
        return 0
    except Exception as e:
        print(f"[unit] ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
