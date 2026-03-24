#!/usr/bin/env python3
"""MI25-tuning-MCP: MCP server for MI25/gfx900 Rust client tuning and maintenance."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from functools import wraps
import inspect
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mi25-tuning")

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "ROCm-project":
            return parent
    return here.parents[4]


def _find_mcp_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "MI25-tuning-MCP":
            return parent
    return here.parents[3]


PROJECT_ROOT = _find_project_root()
MCP_ROOT = _find_mcp_root()
CLIENT_ROOT = Path(os.getenv("MI25_CLIENT_ROOT", str(PROJECT_ROOT / "multi_llm-client")))
NOTES_ROOT = Path(os.getenv("MI25_NOTES_ROOT", str(PROJECT_ROOT / "Agents-note")))
AUDIT_LOG_PATH = Path(
    os.getenv(
        "MI25_MCP_AUDIT_LOG",
        str(MCP_ROOT / "logs" / "tool-calls.jsonl"),
    )
)

# Cargo binary: prefer ~/.cargo/bin/cargo over system cargo
_CARGO_CANDIDATES = [
    Path.home() / ".cargo" / "bin" / "cargo",
    Path("/usr/local/bin/cargo"),
    Path("/usr/bin/cargo"),
]


# Allowlist for update_config
CONFIG_ALLOWLIST = {
    "preset",
    "max_tokens",
    "num_ctx",
    "num_batch",
    "num_thread",
    "temperature",
    "stream",
    "inline_stream",
    "request_timeout_secs",
    "connect_timeout_secs",
    "keep_alive",
    "model_name",
}

# Known presets and their parameters (mirrors multi_llm-client defaults)
PRESET_PARAMS: dict[str, dict[str, Any]] = {
    "default": {
        "max_tokens": 256,
        "num_ctx": None,
        "num_batch": None,
    },
    "gfx900_safe": {
        "max_tokens": 128,
        "num_ctx": 4096,
        "num_batch": 256,
    },
    "gfx900_balanced": {
        "max_tokens": 192,
        "num_ctx": 4096,
        "num_batch": 512,
    },
    "gfx900_longctx": {
        "max_tokens": 128,
        "num_ctx": 8192,
        "num_batch": 128,
    },
    "gfx900_tinybench": {
        "max_tokens": 32,
        "num_ctx": 2048,
        "num_batch": 64,
    },
    "gfx900_anchor_baseline": {
        "max_tokens": 128,
        "num_ctx": 8192,
        "num_batch": 512,
    },
    "gfx900_anchor_side1024": {
        "max_tokens": 128,
        "num_ctx": 8192,
        "num_batch": 1024,
    },
}

BENCH_MODE_ALLOWLIST = {
    "preset-sweep",
    "thread-sweep",
    "keepalive-sweep",
    "predict-sweep",
    "all",
}

BENCH_REPORT_FORMAT_ALLOWLIST = {
    "tsv",
    "markdown",
    "md",
    "json",
    "all",
}

# Candidate rocm-smi commands for compatibility across versions.
ROCM_SMI_COMMANDS = [
    ["rocm-smi", "--showuse", "--showmemuse", "--showtemp", "--showpower", "--json"],
    ["rocm-smi", "--showuse", "--showmeminfo", "vram", "--showtemp", "--showpower", "--json"],
    ["rocm-smi", "--showuse", "--showmemuse", "--json"],
]


# ---------------------------------------------------------------------------
# Response helpers (agreement: content / structuredContent / isError)
# ---------------------------------------------------------------------------


def _ok(content: str, structured: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": content}],
        "structuredContent": structured or {"message": content},
        "isError": False,
    }


def _err(message: str, code: str = "runtime_error", structured: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = structured or {}
    payload.setdefault("error", {"code": code, "message": message})
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": payload,
        "isError": True,
    }


def _info_unavailable(message: str, structured: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return non-error unavailable state (for observability tools like get_gpu_metrics)."""
    payload = structured or {}
    payload.setdefault("status", "unavailable")
    payload.setdefault("message", message)
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": payload,
        "isError": False,
    }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _cargo_bin() -> str:
    for p in _CARGO_CANDIDATES:
        if p.exists():
            return str(p)
    return "cargo"


def _config_path() -> Path:
    return CLIENT_ROOT / "config.json"


def _log_dir() -> Path:
    config_path = _config_path()
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            log_dir = cfg.get("log_dir", "logs")
            return CLIENT_ROOT / log_dir
        except Exception:
            pass
    return CLIENT_ROOT / "logs"


def _read_jsonl_entries(path: Path, n: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    entries: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(entries) >= n:
            break
    return list(reversed(entries))


def _latest_log_file() -> Path | None:
    log_dir = _log_dir()
    if not log_dir.exists():
        return None
    jsonl_files = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonl_files[0] if jsonl_files else None


def _latest_log_entry() -> dict[str, Any] | None:
    lf = _latest_log_file()
    if not lf:
        return None
    entries = _read_jsonl_entries(lf, 1)
    return entries[0] if entries else None


def _collect_log_entries(n: int, preset_filter: str | None) -> list[dict[str, Any]]:
    log_dir = _log_dir()
    if not log_dir.exists():
        return []

    out: list[dict[str, Any]] = []
    jsonl_files = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

    for f in jsonl_files:
        for e in _read_jsonl_entries(f, n * 5):
            if preset_filter:
                preset_val = str(e.get("effective", {}).get("preset", "")).lower().replace("-", "_")
                if preset_val != preset_filter.lower().replace("-", "_"):
                    continue
            out.append(e)
            if len(out) >= n:
                return out
    return out


def _safe_path(base: Path, rel: str) -> Path | None:
    try:
        resolved = (base / rel).resolve()
        resolved.relative_to(base.resolve())
        return resolved
    except Exception:
        return None


def _safe_path_any(path: str, bases: list[Path]) -> Path | None:
    p = Path(path)
    candidates: list[Path] = []
    if p.is_absolute():
        candidates.append(p.resolve())
    else:
        candidates.extend((base / p).resolve() for base in bases)

    for resolved in candidates:
        for base in bases:
            try:
                resolved.relative_to(base.resolve())
                return resolved
            except Exception:
                continue
    return None


def _client_binary_cmd() -> list[str]:
    binary_release = CLIENT_ROOT / "target" / "release" / "multi_llm_client"
    binary_debug = CLIENT_ROOT / "target" / "debug" / "multi_llm_client"
    if binary_release.exists():
        return [str(binary_release)]
    if binary_debug.exists():
        return [str(binary_debug)]
    return [_cargo_bin(), "run", "--"]


def _extract_bench_line_path(text: str, marker: str) -> str | None:
    pattern = re.compile(rf"{re.escape(marker)}(?P<path>.+)$", flags=re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    return m.group("path").strip()


def _extract_bench_line_paths(text: str, marker: str) -> list[str]:
    pattern = re.compile(rf"{re.escape(marker)}(?P<path>.+)$", flags=re.MULTILINE)
    return [m.group("path").strip() for m in pattern.finditer(text)]


def _read_head(path: Path, max_lines: int = 6) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[:max_lines])
    except Exception:
        return ""


def _append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def _record_bench_compare_outcome(
    *,
    status: str,
    payload: dict[str, Any],
) -> dict[str, str | None]:
    """Best-effort append for bench-compare outcome logs under client worklog."""
    out: dict[str, str | None] = {
        "success_log_path": None,
        "failure_log_path": None,
    }
    try:
        worklog_dir = CLIENT_ROOT / "worklog"
        ts = datetime.now().astimezone()
        day = ts.strftime("%Y-%m-%d")
        ts_text = ts.strftime("%Y-%m-%d %H:%M:%S %z")

        baseline = str(payload.get("baseline_phase_summary", ""))
        side = str(payload.get("side_phase_summary", ""))
        compare_out = str(payload.get("compare_out", ""))
        elapsed_ms = payload.get("elapsed_ms")
        rc = payload.get("returncode")

        if status == "ok":
            log_path = worklog_dir / f"mcp_bench_compare_auto_summary_{day}.md"
            line = (
                f"- {ts_text} status=ok rc={rc} elapsed_ms={elapsed_ms} "
                f"baseline={baseline} side={side} out={compare_out}\n"
            )
            _append_text(log_path, line)
            out["success_log_path"] = str(log_path)
            return out

        fail_path = worklog_dir / f"mcp_bench_compare_fail_{day}.jsonl"
        event = {
            "ts": ts.isoformat(),
            "status": status,
            "returncode": rc,
            "elapsed_ms": elapsed_ms,
            "baseline_phase_summary": baseline,
            "side_phase_summary": side,
            "compare_out": compare_out,
            "stderr": payload.get("stderr", ""),
            "stdout": payload.get("stdout", ""),
            "command": payload.get("command", []),
        }
        _append_text(fail_path, json.dumps(event, ensure_ascii=False) + "\n")
        out["failure_log_path"] = str(fail_path)
    except Exception:
        # Logging failure should never block primary tool response.
        pass
    return out


def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout_secs: int = 30,
    input_text: str | None = None,
) -> tuple[int, str, str, int]:
    start = time.monotonic()
    p = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout_secs,
        cwd=str(cwd) if cwd else None,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return p.returncode, p.stdout or "", p.stderr or "", elapsed_ms


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[truncated at {max_chars} chars]"


def _audit_compact(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return "<max_depth>"

    if isinstance(value, str):
        return _truncate_text(value, 300)

    if value is None or isinstance(value, bool | int | float):
        return value

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= 20:
                out["__truncated__"] = f"{len(value) - 20} more keys"
                break
            out[str(k)] = _audit_compact(v, depth + 1)
        return out

    if isinstance(value, list | tuple):
        compacted = [_audit_compact(v, depth + 1) for v in list(value)[:20]]
        if len(value) > 20:
            compacted.append(f"...({len(value) - 20} more items)")
        return compacted

    return str(value)


def _bind_audit_args(func: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return {k: _audit_compact(v) for k, v in bound.arguments.items()}
    except Exception:
        return {
            "args": _audit_compact(list(args)),
            "kwargs": _audit_compact(kwargs),
        }


def _record_tool_call(tool_name: str, args_payload: dict[str, Any], result: Any, elapsed_ms: int) -> None:
    event: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "elapsed_ms": elapsed_ms,
        "args": args_payload,
    }

    if isinstance(result, dict):
        event["isError"] = bool(result.get("isError", False))

        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            if "status" in structured:
                event["status"] = structured.get("status")
            err = structured.get("error")
            if isinstance(err, dict):
                event["error"] = {
                    "code": err.get("code"),
                    "message": _truncate_text(str(err.get("message", "")), 300),
                }

        content = result.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                event["content_preview"] = _truncate_text(text, 240)
    else:
        event["isError"] = False
        event["result_preview"] = _truncate_text(str(result), 240)

    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # Audit logging must not break primary tool execution.
        pass


def audited_tool():
    def _decorator(func):
        @wraps(func)
        def _wrapped(*args, **kwargs):
            started = time.monotonic()
            args_payload = _bind_audit_args(func, *args, **kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                _record_tool_call(
                    func.__name__,
                    args_payload,
                    {
                        "isError": True,
                        "structuredContent": {
                            "error": {"code": "uncaught_exception", "message": str(e)},
                        },
                    },
                    elapsed_ms,
                )
                raise

            elapsed_ms = int((time.monotonic() - started) * 1000)
            _record_tool_call(func.__name__, args_payload, result, elapsed_ms)
            return result

        return mcp.tool()(_wrapped)

    return _decorator


def _read_text_impl(path: str, max_chars: int = 6000) -> dict[str, Any]:
    resolved = _safe_path(PROJECT_ROOT, path)
    if resolved is None:
        return _err(
            f"invalid path or traversal detected: {path!r}",
            code="invalid_path",
            structured={"path": path},
        )
    if not resolved.exists():
        return _err(
            f"file not found: {resolved}",
            code="not_found",
            structured={"path": str(resolved)},
        )
    if not resolved.is_file():
        return _err(
            f"not a file: {resolved}",
            code="not_a_file",
            structured={"path": str(resolved)},
        )

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return _err(
            f"failed to read file: {e}",
            code="read_failed",
            structured={"path": str(resolved)},
        )

    truncated = len(text) > max_chars
    shown = _truncate_text(text, max_chars)
    return _ok(
        shown,
        {
            "path": str(resolved),
            "chars": len(text),
            "truncated": truncated,
            "content": shown,
        },
    )


# ---------------------------------------------------------------------------
# Tools: basic
# ---------------------------------------------------------------------------


@audited_tool()
def ping() -> dict[str, Any]:
    """Health check with resolved paths and cargo path."""
    ts = datetime.now(timezone.utc).isoformat()
    return _ok(
        "OK — mi25-tuning-mcp is running.",
        {
            "ts": ts,
            "project_root": str(PROJECT_ROOT),
            "mcp_root": str(MCP_ROOT),
            "client_root": str(CLIENT_ROOT),
            "notes_root": str(NOTES_ROOT),
            "cargo": _cargo_bin(),
            "audit_log_path": str(AUDIT_LOG_PATH),
        },
    )


@audited_tool()
def get_gpu_metrics(timeout_secs: int = 15) -> dict[str, Any]:
    """Return MI25/gfx900 GPU metrics via rocm-smi (machine-readable best effort).

    This tool is observability-first: if rocm-smi is unavailable or fails,
    it returns a non-error unavailable state with diagnostic details.
    """
    if shutil.which("rocm-smi") is None:
        return _info_unavailable(
            "rocm-smi is not installed or not in PATH.",
            {"status": "unavailable", "reason": "rocm_smi_not_found"},
        )

    last_err: str | None = None
    for cmd in ROCM_SMI_COMMANDS:
        try:
            rc, out, err, elapsed_ms = _run_cmd(cmd, timeout_secs=timeout_secs)
        except subprocess.TimeoutExpired:
            return _info_unavailable(
                f"rocm-smi timed out after {timeout_secs}s.",
                {
                    "status": "unavailable",
                    "reason": "timeout",
                    "timeout_secs": timeout_secs,
                    "command": cmd,
                },
            )
        except Exception as e:
            last_err = str(e)
            continue

        if rc != 0:
            last_err = f"rc={rc}, stderr={_truncate_text(err, 400)}"
            continue

        try:
            parsed = json.loads(out) if out.strip() else {}
        except json.JSONDecodeError:
            parsed = {"raw": _truncate_text(out, 4000)}

        return _ok(
            "GPU metrics collected via rocm-smi.",
            {
                "status": "ok",
                "command": cmd,
                "elapsed_ms": elapsed_ms,
                "metrics": parsed,
                "stderr": _truncate_text(err, 400) if err else "",
            },
        )

    return _info_unavailable(
        "rocm-smi execution failed for all known command patterns.",
        {
            "status": "unavailable",
            "reason": "command_failed",
            "last_error": last_err or "unknown",
            "commands_tried": ROCM_SMI_COMMANDS,
        },
    )


# ---------------------------------------------------------------------------
# Tools: presets
# ---------------------------------------------------------------------------


@audited_tool()
def list_presets() -> dict[str, Any]:
    """List all available gfx900 presets and parameter defaults."""
    return _ok(
        json.dumps(PRESET_PARAMS, ensure_ascii=False, indent=2),
        {
            "preset_count": len(PRESET_PARAMS),
            "presets": PRESET_PARAMS,
        },
    )


# ---------------------------------------------------------------------------
# Tools: inference execution
# ---------------------------------------------------------------------------


@audited_tool()
def run_inference(
    prompt: str,
    preset: str | None = None,
    model: str | None = None,
    timeout_secs: int = 90,
    max_output_chars: int = 4000,
) -> dict[str, Any]:
    """Run multi_llm-client one-shot via stdin with temporary config override."""
    if not prompt.strip():
        return _err("prompt must not be empty", code="invalid_argument")
    if not CLIENT_ROOT.exists():
        return _err(f"client_root not found: {CLIENT_ROOT}", code="not_found")
    if preset is not None and preset not in PRESET_PARAMS:
        return _err(
            f"unknown preset: {preset}",
            code="invalid_preset",
            structured={"known_presets": sorted(PRESET_PARAMS.keys())},
        )

    config_path = _config_path()
    if not config_path.exists():
        return _err(f"config.json not found: {config_path}", code="not_found")

    try:
        original_cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        return _err(f"failed to read config.json: {e}", code="read_failed")

    bak_path = config_path.with_suffix(".json.run_bak")
    override_cfg = dict(original_cfg)
    if preset is not None:
        override_cfg["preset"] = preset
    override_cfg["stream"] = False
    override_cfg["inline_stream"] = False
    if model:
        override_cfg["model_name"] = model

    cmd = _client_binary_cmd()

    stdin_input = f"{prompt}\n/bye\n"
    restore_ok = False
    restore_error = ""

    try:
        shutil.copy2(config_path, bak_path)
        config_path.write_text(json.dumps(override_cfg, indent=2, ensure_ascii=False), encoding="utf-8")

        rc, out, err, elapsed_ms = _run_cmd(
            cmd,
            cwd=CLIENT_ROOT,
            timeout_secs=timeout_secs,
            input_text=stdin_input,
        )

        log_file = _latest_log_file()
        latest_entry = _latest_log_entry()
        status = "ok" if rc == 0 else "failed"

        payload = {
            "status": status,
            "returncode": rc,
            "elapsed_ms": elapsed_ms,
            "preset": override_cfg.get("preset"),
            "requested_preset": preset,
            "model": model or override_cfg.get("model_name"),
            "command": cmd,
            "log_path": str(log_file) if log_file else None,
            "latest_log_entry": latest_entry,
            "stdout": _truncate_text(out, max_output_chars),
            "stderr": _truncate_text(err, 800) if err else "",
        }

        if rc != 0:
            return _err(
                f"inference failed (returncode={rc})",
                code="inference_failed",
                structured=payload,
            )

        return _ok("inference completed", payload)

    except subprocess.TimeoutExpired:
        return _err(
            f"inference timed out after {timeout_secs}s",
            code="timeout",
            structured={"timeout_secs": timeout_secs, "command": cmd},
        )
    except FileNotFoundError as e:
        return _err(f"failed to launch command: {e}", code="exec_not_found")
    except Exception as e:
        return _err(f"unexpected run_inference error: {e}", code="runtime_error")
    finally:
        if bak_path.exists():
            try:
                shutil.copy2(bak_path, config_path)
                bak_path.unlink()
                restore_ok = True
            except Exception as e:
                restore_error = str(e)

        if not restore_ok and restore_error:
            # Best effort emergency signal in stderr for operators.
            print(f"[WARN] failed to restore config from {bak_path}: {restore_error}")


# ---------------------------------------------------------------------------
# Tools: benchmark execution
# ---------------------------------------------------------------------------


@audited_tool()
def run_client_bench(
    mode: str,
    preset: str | None = None,
    prompt: str | None = None,
    repeat: int = 1,
    threads_csv: str | None = None,
    keep_alive_values_csv: str | None = None,
    predict_values_csv: str | None = None,
    out_path: str | None = None,
    timeout_secs: int = 300,
    max_output_chars: int = 6000,
) -> dict[str, Any]:
    """Run multi_llm-client built-in benchmark (`--bench`) and return artifact paths."""
    if not CLIENT_ROOT.exists():
        return _err(f"client_root not found: {CLIENT_ROOT}", code="not_found")
    if timeout_secs <= 0:
        return _err("timeout_secs must be > 0", code="invalid_argument")
    if max_output_chars <= 0:
        return _err("max_output_chars must be > 0", code="invalid_argument")
    if repeat <= 0:
        return _err("repeat must be > 0", code="invalid_argument")

    mode_norm = mode.strip().lower()
    if mode_norm not in BENCH_MODE_ALLOWLIST:
        return _err(
            f"invalid bench mode: {mode}",
            code="invalid_argument",
            structured={"allowed_modes": sorted(BENCH_MODE_ALLOWLIST)},
        )

    if preset is not None and preset not in PRESET_PARAMS:
        return _err(
            f"unknown preset: {preset}",
            code="invalid_preset",
            structured={"known_presets": sorted(PRESET_PARAMS.keys())},
        )

    resolved_out: Path | None = None
    if out_path:
        resolved_out = _safe_path_any(out_path, [CLIENT_ROOT, PROJECT_ROOT])
        if resolved_out is None:
            return _err(
                f"invalid out_path (must be under {CLIENT_ROOT} or {PROJECT_ROOT}): {out_path}",
                code="invalid_path",
                structured={"out_path": out_path},
            )

    cmd = _client_binary_cmd() + ["--bench", mode_norm, "--repeat", str(repeat)]
    if preset:
        cmd.extend(["--preset", preset])
    if prompt:
        cmd.extend(["--prompt", prompt])
    if threads_csv:
        cmd.extend(["--threads", threads_csv])
    if keep_alive_values_csv:
        cmd.extend(["--keep-alive-values", keep_alive_values_csv])
    if predict_values_csv:
        cmd.extend(["--predict-values", predict_values_csv])
    if resolved_out:
        cmd.extend(["--out", str(resolved_out)])

    try:
        rc, out, err, elapsed_ms = _run_cmd(cmd, cwd=CLIENT_ROOT, timeout_secs=timeout_secs)
    except subprocess.TimeoutExpired:
        return _err(
            f"run_client_bench timed out after {timeout_secs}s",
            code="timeout",
            structured={"timeout_secs": timeout_secs, "command": cmd},
        )
    except FileNotFoundError as e:
        return _err(f"failed to launch command: {e}", code="exec_not_found")
    except Exception as e:
        return _err(f"run_client_bench failed: {e}", code="runtime_error")

    merged = f"{out}\n{err}"
    reported_out: str | None = None
    for line in merged.splitlines():
        if line.startswith("[bench] mode=") and " out=" in line:
            reported_out = line.split(" out=", 1)[1].strip()
            break
    reported_phase = _extract_bench_line_path(merged, "[bench] phase_summary=")

    bench_out_path = resolved_out
    if bench_out_path is None and reported_out:
        bench_out_path = _safe_path_any(reported_out, [CLIENT_ROOT, PROJECT_ROOT])

    phase_summary_path: Path | None = None
    if reported_phase:
        phase_summary_path = _safe_path_any(reported_phase, [CLIENT_ROOT, PROJECT_ROOT])
    elif bench_out_path is not None:
        phase_summary_path = bench_out_path.with_name(f"{bench_out_path.stem}_phase_summary.tsv")

    bench_out_exists = bool(bench_out_path and bench_out_path.exists())
    phase_summary_exists = bool(phase_summary_path and phase_summary_path.exists())

    marker_failed = "[bench-error]" in merged
    status = "ok"
    if rc != 0 or marker_failed or not bench_out_exists:
        status = "failed"

    payload = {
        "status": status,
        "returncode": rc,
        "elapsed_ms": elapsed_ms,
        "mode": mode_norm,
        "preset": preset,
        "repeat": repeat,
        "command": cmd,
        "bench_out_path": str(bench_out_path) if bench_out_path else None,
        "bench_out_exists": bench_out_exists,
        "phase_summary_path": str(phase_summary_path) if phase_summary_path else None,
        "phase_summary_exists": phase_summary_exists,
        "stdout": _truncate_text(out, max_output_chars),
        "stderr": _truncate_text(err, 1200) if err else "",
    }

    if status != "ok":
        return _err(
            "run_client_bench failed",
            code="bench_failed",
            structured=payload,
        )

    return _ok("run_client_bench completed", payload)


@audited_tool()
def run_client_bench_compare(
    baseline_phase_summary: str,
    side_phase_summary: str,
    compare_out: str | None = None,
    timeout_secs: int = 180,
    max_output_chars: int = 6000,
) -> dict[str, Any]:
    """Run `--bench-compare` on two phase summary TSV files."""
    if not CLIENT_ROOT.exists():
        return _err(f"client_root not found: {CLIENT_ROOT}", code="not_found")
    if timeout_secs <= 0:
        return _err("timeout_secs must be > 0", code="invalid_argument")
    if max_output_chars <= 0:
        return _err("max_output_chars must be > 0", code="invalid_argument")

    baseline_path = _safe_path_any(baseline_phase_summary, [CLIENT_ROOT, PROJECT_ROOT])
    if baseline_path is None:
        return _err(
            "invalid baseline_phase_summary path",
            code="invalid_path",
            structured={"baseline_phase_summary": baseline_phase_summary},
        )
    if not baseline_path.exists():
        return _err(
            f"baseline phase summary not found: {baseline_path}",
            code="not_found",
            structured={"baseline_phase_summary": str(baseline_path)},
        )

    side_path = _safe_path_any(side_phase_summary, [CLIENT_ROOT, PROJECT_ROOT])
    if side_path is None:
        return _err(
            "invalid side_phase_summary path",
            code="invalid_path",
            structured={"side_phase_summary": side_phase_summary},
        )
    if not side_path.exists():
        return _err(
            f"side phase summary not found: {side_path}",
            code="not_found",
            structured={"side_phase_summary": str(side_path)},
        )

    resolved_compare_out: Path | None = None
    if compare_out:
        resolved_compare_out = _safe_path_any(compare_out, [CLIENT_ROOT, PROJECT_ROOT])
        if resolved_compare_out is None:
            return _err(
                "invalid compare_out path",
                code="invalid_path",
                structured={"compare_out": compare_out},
            )

    cmd = _client_binary_cmd() + [
        "--bench-compare",
        str(baseline_path),
        "--compare-side",
        str(side_path),
    ]
    if resolved_compare_out:
        cmd.extend(["--compare-out", str(resolved_compare_out)])

    try:
        rc, out, err, elapsed_ms = _run_cmd(cmd, cwd=CLIENT_ROOT, timeout_secs=timeout_secs)
    except subprocess.TimeoutExpired:
        return _err(
            f"run_client_bench_compare timed out after {timeout_secs}s",
            code="timeout",
            structured={"timeout_secs": timeout_secs, "command": cmd},
        )
    except FileNotFoundError as e:
        return _err(f"failed to launch command: {e}", code="exec_not_found")
    except Exception as e:
        return _err(f"run_client_bench_compare failed: {e}", code="runtime_error")

    merged = f"{out}\n{err}"
    reported_compare = _extract_bench_line_path(merged, "[bench-compare] out=")

    compare_path = resolved_compare_out
    if compare_path is None and reported_compare:
        compare_path = _safe_path_any(reported_compare, [CLIENT_ROOT, PROJECT_ROOT])
    if compare_path is None:
        compare_path = baseline_path.with_name(
            f"{baseline_path.stem}_vs_{side_path.stem}.tsv"
        )

    compare_exists = compare_path.exists()
    compare_preview = _read_head(compare_path) if compare_exists else ""

    marker_failed = "[bench-compare-error]" in merged
    status = "ok"
    if rc != 0 or marker_failed or not compare_exists:
        status = "failed"

    payload = {
        "status": status,
        "returncode": rc,
        "elapsed_ms": elapsed_ms,
        "command": cmd,
        "baseline_phase_summary": str(baseline_path),
        "side_phase_summary": str(side_path),
        "compare_out": str(compare_path),
        "compare_out_exists": compare_exists,
        "compare_preview": _truncate_text(compare_preview, 1200) if compare_preview else "",
        "stdout": _truncate_text(out, max_output_chars),
        "stderr": _truncate_text(err, 1200) if err else "",
    }

    outcome_paths = _record_bench_compare_outcome(status=status, payload=payload)
    if outcome_paths.get("success_log_path"):
        payload["success_log_path"] = outcome_paths["success_log_path"]
    if outcome_paths.get("failure_log_path"):
        payload["failure_log_path"] = outcome_paths["failure_log_path"]

    if status != "ok":
        return _err(
            "run_client_bench_compare failed",
            code="bench_compare_failed",
            structured=payload,
        )

    return _ok("run_client_bench_compare completed", payload)


@audited_tool()
def run_client_bench_report(
    input_tsv: str,
    report_out: str | None = None,
    report_format: str = "tsv",
    timeout_secs: int = 180,
    max_output_chars: int = 6000,
) -> dict[str, Any]:
    """Run `--bench-report` on an existing bench TSV and return generated report paths."""
    if not CLIENT_ROOT.exists():
        return _err(f"client_root not found: {CLIENT_ROOT}", code="not_found")
    if timeout_secs <= 0:
        return _err("timeout_secs must be > 0", code="invalid_argument")
    if max_output_chars <= 0:
        return _err("max_output_chars must be > 0", code="invalid_argument")

    input_path = _safe_path_any(input_tsv, [CLIENT_ROOT, PROJECT_ROOT])
    if input_path is None:
        return _err(
            "invalid input_tsv path",
            code="invalid_path",
            structured={"input_tsv": input_tsv},
        )
    if not input_path.exists():
        return _err(
            f"bench report input not found: {input_path}",
            code="not_found",
            structured={"input_tsv": str(input_path)},
        )

    format_norm = report_format.strip().lower()
    if format_norm not in BENCH_REPORT_FORMAT_ALLOWLIST:
        return _err(
            f"invalid report_format: {report_format}",
            code="invalid_argument",
            structured={
                "report_format": report_format,
                "allowed_report_formats": sorted(BENCH_REPORT_FORMAT_ALLOWLIST),
            },
        )

    resolved_report_out: Path | None = None
    if report_out:
        resolved_report_out = _safe_path_any(report_out, [CLIENT_ROOT, PROJECT_ROOT])
        if resolved_report_out is None:
            return _err(
                "invalid report_out path",
                code="invalid_path",
                structured={"report_out": report_out},
            )

    report_args = [
        "--bench-report",
        str(input_path),
        "--report-format",
        format_norm,
    ]
    cmd = _client_binary_cmd() + report_args
    if resolved_report_out:
        cmd.extend(["--report-out", str(resolved_report_out)])
        report_args.extend(["--report-out", str(resolved_report_out)])

    try:
        rc, out, err, elapsed_ms = _run_cmd(cmd, cwd=CLIENT_ROOT, timeout_secs=timeout_secs)
    except subprocess.TimeoutExpired:
        return _err(
            f"run_client_bench_report timed out after {timeout_secs}s",
            code="timeout",
            structured={"timeout_secs": timeout_secs, "command": cmd},
        )
    except FileNotFoundError as e:
        return _err(f"failed to launch command: {e}", code="exec_not_found")
    except Exception as e:
        return _err(f"run_client_bench_report failed: {e}", code="runtime_error")

    merged = f"{out}\n{err}"
    # If a stale prebuilt binary does not support --report-format yet, retry via cargo run.
    if "unknown argument: --report-format" in merged and cmd and cmd[0] != _cargo_bin():
        cargo_cmd = [_cargo_bin(), "run", "--"] + report_args
        try:
            rc, out, err, elapsed_ms = _run_cmd(cargo_cmd, cwd=CLIENT_ROOT, timeout_secs=timeout_secs)
            cmd = cargo_cmd
            merged = f"{out}\n{err}"
        except subprocess.TimeoutExpired:
            return _err(
                f"run_client_bench_report timed out after {timeout_secs}s",
                code="timeout",
                structured={"timeout_secs": timeout_secs, "command": cargo_cmd},
            )
        except FileNotFoundError as e:
            return _err(f"failed to launch command: {e}", code="exec_not_found")
        except Exception as e:
            return _err(f"run_client_bench_report failed: {e}", code="runtime_error")

    reported_paths = _extract_bench_line_paths(merged, "[bench-report] out=")
    resolved_paths: list[Path] = []
    for p in reported_paths:
        resolved = _safe_path_any(p, [CLIENT_ROOT, PROJECT_ROOT])
        if resolved:
            resolved_paths.append(resolved)

    if not resolved_paths and resolved_report_out is not None:
        resolved_paths.append(resolved_report_out)

    exists_paths: list[str] = []
    missing_paths: list[str] = []
    for p in resolved_paths:
        if p.exists():
            exists_paths.append(str(p))
        else:
            missing_paths.append(str(p))

    marker_failed = "[bench-report-error]" in merged
    status = "ok"
    if rc != 0 or marker_failed or not exists_paths:
        status = "failed"

    payload = {
        "status": status,
        "returncode": rc,
        "elapsed_ms": elapsed_ms,
        "command": cmd,
        "input_tsv": str(input_path),
        "report_format": format_norm,
        "report_out_paths": [str(p) for p in resolved_paths],
        "report_out_exists_paths": exists_paths,
        "report_out_missing_paths": missing_paths,
        "stdout": _truncate_text(out, max_output_chars),
        "stderr": _truncate_text(err, 1200) if err else "",
    }

    if status != "ok":
        return _err(
            "run_client_bench_report failed",
            code="bench_report_failed",
            structured=payload,
        )

    return _ok("run_client_bench_report completed", payload)


# ---------------------------------------------------------------------------
# Tools: log reading
# ---------------------------------------------------------------------------


def _read_perf_log_impl(
    n: int = 10,
    preset_filter: str | None = None,
    max_output_chars: int = 6000,
) -> dict[str, Any]:
    """Internal implementation shared by read_perf_log/read_inference_logs."""
    if n <= 0:
        return _err("n must be > 0", code="invalid_argument")

    entries = _collect_log_entries(n, preset_filter)
    if not entries:
        return _ok(
            f"No log entries found. log_dir={_log_dir()}",
            {
                "status": "empty",
                "log_dir": str(_log_dir()),
                "entries": [],
                "count": 0,
                "preset_filter": preset_filter,
            },
        )

    text = _truncate_text(json.dumps(entries, ensure_ascii=False, indent=2), max_output_chars)
    return _ok(
        text,
        {
            "status": "ok",
            "count": len(entries),
            "preset_filter": preset_filter,
            "log_dir": str(_log_dir()),
            "entries": entries,
        },
    )


@audited_tool()
def read_perf_log(
    n: int = 10,
    preset_filter: str | None = None,
    max_output_chars: int = 6000,
) -> dict[str, Any]:
    """Read recent JSONL performance entries."""
    return _read_perf_log_impl(n=n, preset_filter=preset_filter, max_output_chars=max_output_chars)


@audited_tool()
def read_inference_logs(
    n: int = 20,
    preset_filter: str | None = None,
    max_output_chars: int = 6000,
) -> dict[str, Any]:
    """Phase2 alias for history-tail usage with same semantics as read_perf_log."""
    return _read_perf_log_impl(n=n, preset_filter=preset_filter, max_output_chars=max_output_chars)


@audited_tool()
def summarize_perf_log(
    n: int = 20,
    preset_filter: str | None = None,
) -> dict[str, Any]:
    """Aggregate performance metrics from multi_llm-client JSONL logs."""
    if n <= 0:
        return _err("n must be > 0", code="invalid_argument")

    entries = _collect_log_entries(n, preset_filter)
    if not entries:
        return _ok(
            "No log entries found.",
            {
                "status": "empty",
                "log_dir": str(_log_dir()),
                "sampled_entries": 0,
                "preset_filter": preset_filter,
            },
        )

    total_ms_list: list[float] = []
    ttft_ms_list: list[float] = []
    tok_per_sec_list: list[float] = []
    response_chars_list: list[int] = []
    error_count = 0
    preset_counts: dict[str, int] = {}

    for e in entries:
        if e.get("error"):
            error_count += 1
        if (v := e.get("total_ms")) is not None:
            total_ms_list.append(float(v))
        if (v := e.get("ttft_ms")) is not None:
            ttft_ms_list.append(float(v))
        if (v := e.get("approx_tok_per_sec")) is not None:
            tok_per_sec_list.append(float(v))
        if (v := e.get("response_chars")) is not None:
            response_chars_list.append(int(v))

        preset_val = str(e.get("effective", {}).get("preset", "unknown"))
        preset_counts[preset_val] = preset_counts.get(preset_val, 0) + 1

    def _avg(vals: list[float]) -> float | None:
        return round(sum(vals) / len(vals), 2) if vals else None

    summary: dict[str, Any] = {
        "status": "ok",
        "sampled_entries": len(entries),
        "error_count": error_count,
        "error_rate": round(error_count / len(entries), 3),
        "avg_total_ms": _avg(total_ms_list),
        "avg_ttft_ms": _avg(ttft_ms_list),
        "avg_tok_per_sec": _avg(tok_per_sec_list),
        "min_tok_per_sec": round(min(tok_per_sec_list), 2) if tok_per_sec_list else None,
        "max_tok_per_sec": round(max(tok_per_sec_list), 2) if tok_per_sec_list else None,
        "avg_response_chars": _avg([float(x) for x in response_chars_list]),
        "preset_counts": preset_counts,
        "preset_filter": preset_filter,
    }

    return _ok(json.dumps(summary, ensure_ascii=False, indent=2), summary)


# ---------------------------------------------------------------------------
# Tools: config management
# ---------------------------------------------------------------------------


@audited_tool()
def get_config() -> dict[str, Any]:
    """Read and return current multi_llm-client config.json."""
    path = _config_path()
    if not path.exists():
        return _err(f"config.json not found at {path}", code="not_found")

    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        return _ok(raw, {"path": str(path), "config": parsed})
    except Exception as e:
        return _err(f"failed to read config.json: {e}", code="read_failed", structured={"path": str(path)})


@audited_tool()
def update_config(overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge allowlisted keys into config.json (partial update + .bak)."""
    if not isinstance(overrides, dict):
        return _err("overrides must be an object", code="invalid_argument")
    if not overrides:
        return _err("overrides must not be empty", code="invalid_argument")

    rejected = [k for k in overrides if k not in CONFIG_ALLOWLIST]
    if rejected:
        return _err(
            f"rejected keys (not in allowlist): {rejected}",
            code="allowlist_violation",
            structured={"allowed": sorted(CONFIG_ALLOWLIST), "rejected": rejected},
        )

    path = _config_path()
    if not path.exists():
        return _err(f"config.json not found at {path}", code="not_found")

    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return _err(f"failed to read config.json: {e}", code="read_failed")

    bak_path = path.with_suffix(".json.bak")
    try:
        shutil.copy2(path, bak_path)
    except Exception as e:
        return _err(f"failed to backup config.json: {e}", code="backup_failed")

    before = {k: current.get(k) for k in overrides}
    current.update(overrides)

    try:
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        return _err(f"failed to write config.json: {e}", code="write_failed")

    after = {k: current.get(k) for k in overrides}
    changes = {k: {"before": before[k], "after": after[k]} for k in overrides}
    return _ok(
        f"OK — config.json updated. Backup: {bak_path}",
        {
            "path": str(path),
            "backup": str(bak_path),
            "changes": changes,
        },
    )


@audited_tool()
def set_config_raw(config_json: str) -> dict[str, Any]:
    """Raw full overwrite API (disabled by default by policy).

    Agreement Phase1 excludes full overwrite API for agent usage.
    This method is therefore gated and returns policy error unless
    MI25_ENABLE_SET_CONFIG_RAW=1 is explicitly set.
    """
    if os.getenv("MI25_ENABLE_SET_CONFIG_RAW", "0") != "1":
        return _err(
            "set_config_raw is disabled by policy. Use update_config(overrides) instead.",
            code="disabled_by_policy",
        )

    try:
        parsed = json.loads(config_json)
    except json.JSONDecodeError as e:
        return _err(f"invalid JSON: {e}", code="invalid_argument")

    path = _config_path()
    bak_path = path.with_suffix(".json.bak")

    if path.exists():
        try:
            shutil.copy2(path, bak_path)
        except Exception as e:
            return _err(f"failed to backup config.json: {e}", code="backup_failed")

    try:
        path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        return _err(f"failed to write config.json: {e}", code="write_failed")

    return _ok(
        f"OK — config.json replaced. Backup: {bak_path}",
        {"path": str(path), "backup": str(bak_path)},
    )


# ---------------------------------------------------------------------------
# Tools: file operations
# ---------------------------------------------------------------------------


@audited_tool()
def list_dir(path: str = ".", max_entries: int = 200) -> dict[str, Any]:
    """List directory entries under project root."""
    if max_entries <= 0:
        return _err("max_entries must be > 0", code="invalid_argument")

    resolved = _safe_path(PROJECT_ROOT, path)
    if resolved is None:
        return _err("invalid path or traversal detected", code="invalid_path", structured={"path": path})
    if not resolved.exists():
        return _err(f"path not found: {resolved}", code="not_found")
    if not resolved.is_dir():
        return _err(f"not a directory: {resolved}", code="not_a_directory")

    try:
        items = []
        for p in sorted(resolved.iterdir(), key=lambda x: x.name)[:max_entries]:
            items.append({
                "name": p.name,
                "is_dir": p.is_dir(),
                "is_file": p.is_file(),
            })
    except Exception as e:
        return _err(f"failed to list directory: {e}", code="list_failed", structured={"path": str(resolved)})

    return _ok(
        json.dumps(items, ensure_ascii=False, indent=2),
        {"path": str(resolved), "count": len(items), "entries": items},
    )


@audited_tool()
def read_text(path: str, max_chars: int = 6000) -> dict[str, Any]:
    """Read text file under project root (Phase2 alias for read_file)."""
    return _read_text_impl(path=path, max_chars=max_chars)


@audited_tool()
def read_file(path: str, max_chars: int = 6000) -> dict[str, Any]:
    """Compatibility wrapper for reading text file under project root."""
    return _read_text_impl(path=path, max_chars=max_chars)


@audited_tool()
def write_file(path: str, content: str, append: bool = False) -> dict[str, Any]:
    """Write/append file under Agents-note only."""
    resolved = _safe_path(NOTES_ROOT, path)
    if resolved is None:
        return _err("invalid path or traversal detected", code="invalid_path", structured={"path": path})

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with resolved.open(mode, encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return _err(f"failed to write file: {e}", code="write_failed", structured={"path": str(resolved)})

    return _ok(
        f"OK — {'appended to' if append else 'wrote'} {resolved} ({len(content)} chars)",
        {
            "path": str(resolved),
            "append": append,
            "chars": len(content),
        },
    )


# ---------------------------------------------------------------------------
# Tools: maintenance
# ---------------------------------------------------------------------------


@audited_tool()
def run_client_check(timeout_secs: int = 300, max_output_chars: int = 6000) -> dict[str, Any]:
    """Run cargo check for multi_llm-client with absolute cargo path preference."""
    if timeout_secs <= 0:
        return _err("timeout_secs must be > 0", code="invalid_argument")

    if not CLIENT_ROOT.exists():
        return _err(f"client_root not found: {CLIENT_ROOT}", code="not_found")

    cmd = [_cargo_bin(), "check"]
    try:
        rc, out, err, elapsed_ms = _run_cmd(cmd, cwd=CLIENT_ROOT, timeout_secs=timeout_secs)
    except subprocess.TimeoutExpired:
        return _err(
            f"run_client_check timed out after {timeout_secs}s",
            code="timeout",
            structured={"command": cmd, "timeout_secs": timeout_secs},
        )
    except Exception as e:
        return _err(f"run_client_check failed: {e}", code="runtime_error", structured={"command": cmd})

    payload = {
        "status": "ok" if rc == 0 else "failed",
        "returncode": rc,
        "elapsed_ms": elapsed_ms,
        "command": cmd,
        "stdout": _truncate_text(out, max_output_chars),
        "stderr": _truncate_text(err, 1200) if err else "",
    }

    if rc != 0:
        return _err("cargo check failed", code="check_failed", structured=payload)
    return _ok("cargo check succeeded", payload)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
