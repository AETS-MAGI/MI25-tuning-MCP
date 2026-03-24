#!/usr/bin/env python3
"""MCP unit test by directly calling Python tool functions."""

from __future__ import annotations

import json
import sys
import tempfile
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


def _integration_sandbox_case() -> None:
    """Run run_inference/update_config/read/summarize on isolated temporary client root."""
    original_root = server.CLIENT_ROOT
    try:
        with tempfile.TemporaryDirectory(prefix="mi25-mcp-test-") as tmp:
            root = Path(tmp)
            target = root / "target" / "release"
            target.mkdir(parents=True, exist_ok=True)
            logs_dir = root / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            # Fake client binary that accepts stdin and exits successfully.
            fake_bin = target / "multi_llm_client"
            fake_bin.write_text(
                "#!/usr/bin/env bash\n"
                "cat >/dev/null\n"
                "echo 'fake client ok'\n",
                encoding="utf-8",
            )
            fake_bin.chmod(0o755)

            config_path = root / "config.json"
            original_cfg = {
                "model_name": "dummy-model",
                "log_dir": "logs",
                "preset": "default",
                "stream": False,
                "inline_stream": False,
            }
            config_path.write_text(json.dumps(original_cfg, indent=2), encoding="utf-8")

            # Pre-seed one log entry to validate read/summarize chain.
            seed_entry = {
                "total_ms": 120.0,
                "ttft_ms": 30.0,
                "approx_tok_per_sec": 22.2,
                "response_chars": 64,
                "effective": {"preset": "gfx900_safe"},
            }
            (logs_dir / "seed.jsonl").write_text(
                json.dumps(seed_entry, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            server.CLIENT_ROOT = root

            # update_config positive path (+ .bak)
            res_update = server.update_config({"preset": "gfx900_safe"})
            _assert_shape("sandbox_update_config", res_update)
            if res_update.get("isError"):
                _fail("sandbox_update_config should succeed")
            bak_path = root / "config.json.bak"
            if not bak_path.exists():
                _fail("sandbox_update_config should create .bak")

            # run_inference positive path with temp config swap + restore
            res_infer = server.run_inference(
                prompt="hello from unit test",
                preset="gfx900_safe",
                timeout_secs=5,
                max_output_chars=300,
            )
            _assert_shape("sandbox_run_inference", res_infer)
            if res_infer.get("isError"):
                _fail(f"sandbox_run_inference failed: {res_infer}")

            restored_cfg = json.loads(config_path.read_text(encoding="utf-8"))
            if restored_cfg.get("preset") != "gfx900_safe":
                # update_config changed this earlier; run_inference must restore to that state.
                _fail("config restore check failed after run_inference")
            if (root / "config.json.run_bak").exists():
                _fail("config.json.run_bak should be removed after successful restore")

            # read/summarize chain
            res_read = server.read_perf_log(n=1, preset_filter="gfx900_safe")
            _assert_shape("sandbox_read_perf_log", res_read)
            if res_read.get("isError"):
                _fail("sandbox_read_perf_log should not fail")

            res_sum = server.summarize_perf_log(n=1, preset_filter="gfx900_safe")
            _assert_shape("sandbox_summarize_perf_log", res_sum)
            if res_sum.get("isError"):
                _fail("sandbox_summarize_perf_log should not fail")

            # timeout failure path
            fake_bin.write_text(
                "#!/usr/bin/env bash\n"
                "sleep 2\n"
                "cat >/dev/null\n"
                "echo 'late output'\n",
                encoding="utf-8",
            )
            fake_bin.chmod(0o755)
            res_timeout = server.run_inference(
                prompt="timeout test",
                preset="gfx900_safe",
                timeout_secs=1,
            )
            _assert_shape("sandbox_run_inference_timeout", res_timeout)
            if not res_timeout.get("isError"):
                _fail("sandbox_run_inference_timeout should fail with timeout")
            if _error_code(res_timeout) != "timeout":
                _fail(f"expected timeout error code, got {_error_code(res_timeout)}")

            # empty-log behavior (no failure)
            for f in logs_dir.glob("*.jsonl"):
                f.unlink()
            res_empty = server.read_perf_log(n=5)
            _assert_shape("sandbox_read_perf_log_empty", res_empty)
            if res_empty.get("isError"):
                _fail("read_perf_log on empty logs should be non-error empty state")

            print("[unit] sandbox integration: ok")
    finally:
        server.CLIENT_ROOT = original_root


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
        _run_case(
            "run_client_bench_invalid_mode",
            lambda: server.run_client_bench(mode="__invalid_mode__"),
            expected_error_code="invalid_argument",
        )
        _run_case(
            "run_client_bench_compare_not_found",
            lambda: server.run_client_bench_compare(
                baseline_phase_summary="worklog/no-baseline.tsv",
                side_phase_summary="worklog/no-side.tsv",
            ),
            expected_error_code="not_found",
        )
        _run_case(
            "run_client_bench_report_not_found",
            lambda: server.run_client_bench_report(
                input_tsv="worklog/no-bench.tsv",
                report_format="markdown",
            ),
            expected_error_code="not_found",
        )

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
        _integration_sandbox_case()

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
