#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_PY="$ROOT_DIR/src/mi25_tuning_mcp/server.py"

if [[ -z "${MI25_MCP_AUDIT_LOG:-}" ]]; then
  TMP_AUDIT_LOG="$(mktemp -t mi25-mcp-smoke-audit.XXXXXX.jsonl)"
  export MI25_MCP_AUDIT_LOG="$TMP_AUDIT_LOG"
  trap 'rm -f "$TMP_AUDIT_LOG"' EXIT
fi

echo "[smoke] python compile check"
python3 -m py_compile "$SERVER_PY"

if ! python3 -c "import mcp" >/dev/null 2>&1; then
  echo "[smoke] WARN: python package 'mcp' is not installed. runtime smoke is skipped."
  echo "[smoke]       run: pip install -e ."
  exit 0
fi

echo "[smoke] runtime tool shape check"
PYTHONPATH="$ROOT_DIR/src" python3 - <<'PY'
import json
from pathlib import Path

from mi25_tuning_mcp import server


def assert_shape(name, result):
    assert isinstance(result, dict), f"{name}: result must be dict"
    for key in ("content", "structuredContent", "isError"):
        assert key in result, f"{name}: missing key {key}"


checks = [
    ("ping", lambda: server.ping()),
    ("get_gpu_metrics", lambda: server.get_gpu_metrics(timeout_secs=5)),
    ("list_presets", lambda: server.list_presets()),
    ("get_config", lambda: server.get_config()),
    ("read_perf_log", lambda: server.read_perf_log(n=1)),
    ("summarize_perf_log", lambda: server.summarize_perf_log(n=1)),
    ("list_dir", lambda: server.list_dir(path="MI25-tuning-MCP", max_entries=5)),
    ("read_text", lambda: server.read_text(path="MI25-tuning-MCP/README.md", max_chars=200)),
    ("run_client_check", lambda: server.run_client_check(timeout_secs=5, max_output_chars=400)),
    ("run_client_bench invalid", lambda: server.run_client_bench(mode="invalid-mode")),
    (
        "run_client_bench_compare invalid",
        lambda: server.run_client_bench_compare(
            baseline_phase_summary="worklog/does-not-exist-baseline.tsv",
            side_phase_summary="worklog/does-not-exist-side.tsv",
        ),
    ),
]

for name, fn in checks:
    result = fn()
    assert_shape(name, result)
    print(f"[smoke] {name}: ok (isError={result['isError']})")

audit_path = Path(server.AUDIT_LOG_PATH)
if audit_path.exists():
    line = audit_path.read_text(encoding="utf-8").splitlines()[-1]
    obj = json.loads(line)
    print(f"[smoke] audit log ok: tool={obj.get('tool')}")
else:
    print(f"[smoke] WARN: audit log not found at {audit_path}")
PY

echo "[smoke] unit direct test"
PYTHONPATH="$ROOT_DIR/src" python3 "$ROOT_DIR/tests/unit_direct_test.py"

echo "[smoke] protocol tools test"
PYTHONPATH="$ROOT_DIR/src" python3 "$ROOT_DIR/tests/protocol_tools_test.py"

if [[ "${MI25_RUN_LLM_INTEGRATION:-0}" == "1" ]]; then
  echo "[smoke] llm bridge integration test"
  PYTHONPATH="$ROOT_DIR/src" python3 "$ROOT_DIR/tests/llm_bridge_integration_test.py"
else
  echo "[smoke] skip llm bridge integration test (set MI25_RUN_LLM_INTEGRATION=1 to enable)"
fi

if [[ "${MI25_RUN_BENCH_INTEGRATION:-0}" == "1" ]]; then
  echo "[smoke] bench flow integration test"
  PYTHONPATH="$ROOT_DIR/src" python3 "$ROOT_DIR/tests/bench_flow_integration_test.py"
else
  echo "[smoke] skip bench flow integration test (set MI25_RUN_BENCH_INTEGRATION=1 to enable)"
fi

echo "[smoke] done"
