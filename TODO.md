# MI25-tuning-MCP TODO

最終更新: 2026-03-22（Codex残務完了反映）
参照合意書: `ROCm-project/Agents-note/Rust製クライアント/MCP対応案/agreement.md`

## 0. 正本参照資産（必須）

以下を設計・実装・チューニング判断の正本参照資産として扱う。

- [x] rocBLAS / Tensile フォークを参照して実装判断に反映する
  - `ROCm-project/ROCm-repos_AETS`
- [x] 研究資産の経路知見をツール仕様に反映する
  - `ROCm-project/vega-hbmx-experiments`
  - `ROCm-project/vega_investigations`
  - `ROCm-project/vega-hbmx-pages`

## 1. 仕様固定チェック（agreement準拠）

- [x] `update_config(overrides)` を主APIにする（allowlist 部分マージ）
- [x] `update_config` 実行前に `.bak` を作成する
- [x] `cargo` は絶対PATH優先で実行する（`~/.cargo/bin/cargo` 優先）
- [x] `run_inference` は `--config` 未対応前提で一時 `config.json` 差し替えを採用する
- [x] ツール返却を `content / structuredContent / isError` へ統一する
- [x] `set_config` の扱いを明確化する（`set_config_raw` として管理者向けに分離）
- [x] `set_config` を Phase 1 スコープから除外する（`set_config_raw` は既定で無効）

## 2. Phase 0（骨組み）

- [x] `src/mi25_tuning_mcp/server.py` を配置
- [x] `pyproject.toml` を配置
- [x] `README.md` を作成
- [x] `mcp-config.json` を作成（ブリッジ接続例）
- [x] `docs/tool-spec.md` を作成
- [x] `tests/smoke.sh` を作成

## 3. Phase 1（最小運用MVP）

必須ツール:

- [x] `ping`
- [x] `get_gpu_metrics`
- [x] `get_config`
- [x] `update_config`
- [x] `run_inference`
- [x] `read_perf_log`
- [x] `summarize_perf_log`

補助ツール（任意）:

- [x] `read_file`
- [x] `write_file`
- [x] `list_presets`

責務分離チェック:

- [x] `rocm_status` / `ollama_health` を本MCPに重複実装しない
- [x] 既存 `ROCm-ollama-mcp` への参照導線を README に明記する

## 4. Phase 2（運用強化）

- [x] `read_inference_logs`（tail/filter）を実装
- [x] `run_client_check`（`~/.cargo/bin/cargo check` 固定）を実装
- [x] MCP tool call 監査ログ（JSONL）を実装
- [x] `list_dir` を実装（agreement §3 Phase 2 明記）
- [x] `read_text` を実装（agreement §3 Phase 2 明記）
- [x] `list_presets` を正式化（docs/tool-spec.md への仕様記載）
- [x] `write_file` の運用制限を明文化（`Agents-note/` 限定）
- [x] エラーコード体系を統一（入力不正/実行失敗/タイムアウト）

## 5. Phase 3（連携強化）

- [x] `multi_llm-client` 側 tool-calling 連携（必要時）
- [x] `max_tool_roundtrips` / `allowed_tools` 適用
- [x] ブリッジ経由でループ収束性テスト
- [x] `ROCm-ollama-mcp` との連携強化（agreement §3 Phase 3 明記）
- [x] `compare_presets` / `tail_log(follow)` の要否再評価

## 6. テスト計画（必須順）

- [x] MCP単体テスト（Python関数直接呼び出し）
- [x] MCPプロトコルテスト（tools/list, tools/call）
- [x] LLM統合テスト（ブリッジ経由）
- [x] 失敗系テスト（timeout, 不正path, allowlist違反, ログ不在）

## 7. DoD チェック

- [x] stdio MCP として起動できる
- [x] Phase 1 必須ツールが動作する
- [x] `config.json` 安全更新（`.bak` 付き）が動作する
- [x] `run_inference -> read_perf_log -> summarize_perf_log` が再現できる
- [x] `get_gpu_metrics` が実機または未導入環境で可観測結果を返す
- [x] 失敗時に `isError` と原因を返す
- [x] MCP単体テスト + MCPプロトコルテストが通る

## 8. 直近3タスク（優先）

- [x] `get_gpu_metrics` 実装（rocm-smi のJSON出力を機械可読で返す）
- [x] `README.md` / `mcp-config.json` 作成済み
- [x] `docs/tool-spec.md` を作成
- [x] 返却フォーマットを `content / structuredContent / isError` に統一
- [x] `set_config` を Phase 1 スコープから除外（server.py の修正）
