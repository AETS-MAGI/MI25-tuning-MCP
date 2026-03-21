#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_PY="$ROOT_DIR/src/mi25_tuning_mcp/server.py"

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

echo "[smoke] done"
