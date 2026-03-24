# MI25-tuning-MCP Tool Spec

最終更新: 2026-03-24  
正本: `../SPEC.md`, `../../Agents-note/Rust製クライアント/MCP対応案/agreement.md`

## 1. 共通仕様

全ツールは以下の返却形式を使う。

```json
{
  "content": [{"type": "text", "text": "..."}],
  "structuredContent": {},
  "isError": false
}
```

- `isError=true`: 実行失敗（入力不正/allowlist違反/timeout/実行失敗など）
- `isError=false`: 正常系。または観測系での「取得不可（unavailable）」を表す非失敗応答

## 2. セーフティ制約

- `update_config` は allowlist 部分マージのみ
- `set_config_raw` は既定で無効（`MI25_ENABLE_SET_CONFIG_RAW=1` 時のみ有効）
- `write_file` は `Agents-note/` 配下のみ
- `read_text` / `read_file` / `list_dir` はプロジェクトルート配下のみ
- subprocess は固定テンプレートのみ、timeout と出力長制限を適用

## 3. ツール一覧

### 3.1 基本

- `ping()`
  - 返却: `project_root`, `mcp_root`, `client_root`, `notes_root`, `cargo`, `audit_log_path`
- `get_gpu_metrics(timeout_secs=15)`
  - `rocm-smi` を JSON で取得
  - 未導入/失敗時: `isError=false`, `structuredContent.status="unavailable"`

### 3.2 設定

- `get_config()`
  - `multi_llm-client/config.json` を返す
- `update_config(overrides: object)`
  - allowlist のみ更新し `.json.bak` を作成
- `set_config_raw(config_json: string)` (admin)
  - 全体上書き API
  - 既定で `disabled_by_policy`

allowlist keys:

- `preset`
- `max_tokens`
- `num_ctx`
- `num_batch`
- `num_thread`
- `temperature`
- `stream`
- `inline_stream`
- `request_timeout_secs`
- `connect_timeout_secs`
- `keep_alive`
- `model_name`

### 3.3 推論・ログ

- `run_inference(prompt, preset=null, model=null, timeout_secs=90, max_output_chars=4000)`
  - 一時 `config.json` 差し替え -> 実行 -> 復元
  - `preset=null` のときは `config.json` の現在値を利用
  - `stdout`, `stderr`, `latest_log_entry`, `log_path` を返す
- `run_client_bench(mode, preset=null, prompt=null, repeat=1, threads_csv=null, keep_alive_values_csv=null, predict_values_csv=null, out_path=null, timeout_secs=300, max_output_chars=6000)`
  - `multi_llm-client --bench ...` を固定テンプレートで実行
  - `bench_out_path` と `phase_summary_path`（`*_phase_summary.tsv`）を返す
  - `mode` は `preset-sweep|thread-sweep|keepalive-sweep|predict-sweep|all`
- `run_client_bench_compare(baseline_phase_summary, side_phase_summary, compare_out=null, timeout_secs=180, max_output_chars=6000)`
  - `multi_llm-client --bench-compare ... --compare-side ...` を実行
  - 比較 TSV パスと先頭プレビューを返す
- `read_perf_log(n=10, preset_filter=null, max_output_chars=6000)`
  - JSONL の末尾読み取り
- `read_inference_logs(n=20, preset_filter=null, max_output_chars=6000)`
  - `read_perf_log` の alias（Phase 2）
- `summarize_perf_log(n=20, preset_filter=null)`
  - `avg_ttft_ms`, `avg_tok_per_sec`, `error_rate`, `preset_counts` などを返す

### 3.4 ファイル・保守

- `list_presets()`
- `list_dir(path=".", max_entries=200)`
- `read_text(path, max_chars=6000)`
- `read_file(path, max_chars=6000)` (互換 alias)
- `write_file(path, content, append=false)`
- `run_client_check(timeout_secs=300, max_output_chars=6000)`
  - `~/.cargo/bin/cargo` 優先の `cargo check`

## 4. エラーコード

代表的な `error.code`:

- `invalid_argument`
- `invalid_path`
- `allowlist_violation`
- `invalid_preset`
- `not_found`
- `not_a_file`
- `not_a_directory`
- `read_failed`
- `write_failed`
- `backup_failed`
- `exec_not_found`
- `inference_failed`
- `bench_failed`
- `bench_compare_failed`
- `check_failed`
- `timeout`
- `disabled_by_policy`
- `runtime_error`

## 5. 監査ログ（JSONL）

既定パス: `MI25-tuning-MCP/logs/tool-calls.jsonl`  
上書き: `MI25_MCP_AUDIT_LOG`

各行は概ね以下の形:

```json
{
  "ts": "2026-03-22T00:00:00+00:00",
  "tool": "run_inference",
  "elapsed_ms": 1234,
  "args": {},
  "isError": false,
  "status": "ok",
  "content_preview": "..."
}
```

監査ログ書き込み失敗はツール本体の失敗にはしない（ベストエフォート）。

## 6. Bridge / Phase 3

- 統合設定ファイル: `mcp-config.phase3.json`
- bridge 用ヘルパー: `tools/bridge_agent_chat.sh`
- LLM 統合テスト: `tests/llm_bridge_integration_test.py`

`mcp-config.phase3.json` には以下を含む:

- `agent.max_tool_roundtrips`
- `agent.allowed_tools`
- `mi25_tuning` + `rocm_ops` + `rocm_ops_b` の同時接続
