#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_PATH="${MI25_AGENT_CONFIG:-$ROOT_DIR/mcp-config.phase3.json}"
BRIDGE_SCRIPT="${MI25_BRIDGE_SCRIPT:-/home/limonene/ROCm-project/ROCm-ollama-mcp/ollama-mcp-bridge/bridge.py}"
PROMPT="${1:-Check MI25 runtime and summarize status in one sentence.}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "[agent-chat] config not found: $CONFIG_PATH" >&2
  exit 1
fi
if [[ ! -f "$BRIDGE_SCRIPT" ]]; then
  echo "[agent-chat] bridge script not found: $BRIDGE_SCRIPT" >&2
  exit 1
fi

python3 - "$CONFIG_PATH" "$BRIDGE_SCRIPT" "$PROMPT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
bridge_script = Path(sys.argv[2])
prompt = sys.argv[3]

cfg = json.loads(config_path.read_text(encoding="utf-8"))
agent = cfg.get("agent", {})
ollama = cfg.get("ollama", {})

max_rounds = int(agent.get("max_tool_roundtrips", cfg.get("bridge", {}).get("max_rounds", 4)))
allowed_tools = agent.get("allowed_tools", [])
model = ollama.get("model", "gpt-oss:latest")

system_prompt = (
    "You are an MI25 operations assistant. "
    "Use tools before conclusions. "
    f"Allowed tools: {', '.join(allowed_tools)}. "
    f"Do not exceed {max_rounds} tool rounds."
)

cmd = [
    "python3",
    str(bridge_script),
    "--config",
    str(config_path),
    "chat",
    "--model",
    model,
    "--max-rounds",
    str(max_rounds),
    "--system",
    system_prompt,
    "--prompt",
    prompt,
]

print("[agent-chat] running:", " ".join(cmd))
proc = subprocess.run(cmd, capture_output=True, text=True)
if proc.returncode != 0:
    sys.stderr.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    raise SystemExit(proc.returncode)

print(proc.stdout)
if proc.stderr.strip():
    sys.stderr.write(proc.stderr)
PY
