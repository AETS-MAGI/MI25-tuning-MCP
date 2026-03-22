#!/usr/bin/env python3
"""Bridge-based LLM integration test (Ollama tool-calling roundtrip)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "mcp-config.phase3.json"
DEFAULT_BRIDGE = Path("/home/limonene/ROCm-project/ROCm-ollama-mcp/ollama-mcp-bridge/bridge.py")


def _extract_json_payload(text: str) -> Any:
    # Bridge output may include log lines before JSON payload.
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        chunk = text[i:].strip()
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    raise ValueError("JSON payload not found in output")


def _run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG
    bridge_script = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BRIDGE

    if not config_path.exists():
        print(f"[llm-integration] SKIP: config not found: {config_path}")
        return 0
    if not bridge_script.exists():
        print(f"[llm-integration] SKIP: bridge script not found: {bridge_script}")
        return 0

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    agent = cfg.get("agent", {})
    ollama = cfg.get("ollama", {})
    max_rounds = int(agent.get("max_tool_roundtrips", cfg.get("bridge", {}).get("max_rounds", 4)))
    allowed_tools = set(agent.get("allowed_tools", []))
    model = ollama.get("model", "gpt-oss:latest")

    required_tools = {"mi25_tuning__ping", "rocm_ops__ollama_health"}
    allowed_for_test = sorted((allowed_tools or required_tools) | required_tools)

    # 1) tools/list over aggregated bridge
    tools_cmd = ["python3", str(bridge_script), "--config", str(config_path), "tools"]
    tools_proc = _run(tools_cmd, timeout=120)
    if tools_proc.returncode != 0:
        print("[llm-integration] FAIL: tools command failed")
        print(tools_proc.stdout)
        print(tools_proc.stderr)
        return 1

    tools_payload = _extract_json_payload(tools_proc.stdout)
    merged_names = {item.get("function", {}).get("name") for item in tools_payload if isinstance(item, dict)}
    missing = sorted(t for t in required_tools if t not in merged_names)
    if missing:
        print(f"[llm-integration] FAIL: required merged tools missing: {missing}")
        return 1
    print(f"[llm-integration] tools/list: ok ({len(merged_names)} merged tools)")

    # 2) tool-calling chat roundtrip
    system_prompt = (
        "Use only these tools: "
        + ", ".join(allowed_for_test)
        + ". You must call mi25_tuning__ping and rocm_ops__ollama_health before final answer. "
          "Do not call any other tools."
    )
    prompt = "Check runtime and MCP status in one short sentence."
    chat_cmd = [
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
    chat_proc = _run(chat_cmd, timeout=240)
    if chat_proc.returncode != 0:
        print("[llm-integration] FAIL: chat command failed")
        print(chat_proc.stdout)
        print(chat_proc.stderr)
        return 1

    chat_payload = _extract_json_payload(chat_proc.stdout)
    if not isinstance(chat_payload, dict) or not chat_payload.get("ok"):
        print("[llm-integration] FAIL: chat payload is not ok=true")
        print(chat_payload)
        return 1

    messages = chat_payload.get("messages", [])
    called_tools: list[str] = []
    assistant_tool_rounds = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            assistant_tool_rounds += 1
            for tc in msg.get("tool_calls", []):
                name = tc.get("function", {}).get("name")
                if isinstance(name, str):
                    called_tools.append(name)

    called_set = set(called_tools)
    missing_called = sorted(required_tools - called_set)
    if missing_called:
        print(f"[llm-integration] FAIL: required tools were not called: {missing_called}")
        return 1

    disallowed = sorted(name for name in called_set if allowed_tools and name not in allowed_tools)
    if disallowed:
        print(f"[llm-integration] FAIL: disallowed tools were called: {disallowed}")
        return 1

    if assistant_tool_rounds > max_rounds:
        print(
            f"[llm-integration] FAIL: tool rounds exceeded max "
            f"(rounds={assistant_tool_rounds}, max={max_rounds})"
        )
        return 1

    final_msg = chat_payload.get("final", {})
    final_content = final_msg.get("content", "") if isinstance(final_msg, dict) else ""
    print(
        "[llm-integration] chat: ok "
        f"(model={model}, rounds={assistant_tool_rounds}, tools={sorted(called_set)})"
    )
    print(f"[llm-integration] final: {final_content}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
