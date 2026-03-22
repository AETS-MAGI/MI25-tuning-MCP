# Phase 3 Status

最終更新: 2026-03-22

## 1. 実装方針

Phase 3 は agreement の short-term 方針（Rust 本体は当面変更しない）を維持し、
`ROCm-ollama-mcp` bridge 連携で tool-calling を成立させる。

## 2. 完了項目

1. `multi_llm-client` 側 tool-calling 連携（必要時）
- 非侵襲連携として `tools/bridge_agent_chat.sh` を追加。
- Rust 本体の大改造をせず、bridge 経由で tool-calling セッションを実行可能にした。

2. `max_tool_roundtrips` / `allowed_tools` 適用
- `mcp-config.phase3.json` に `agent.max_tool_roundtrips`, `agent.allowed_tools` を追加。
- `tests/llm_bridge_integration_test.py` で実際の tool call が allowlist 内か検証。

3. ブリッジ経由でループ収束性テスト
- `tests/llm_bridge_integration_test.py` で `assistant` の tool-call round 数を測定し、
  `max_tool_roundtrips` 以下で収束することを検証。

4. `ROCm-ollama-mcp` との連携強化
- `mcp-config.phase3.json` で `mi25_tuning` + `rocm_ops` + `rocm_ops_b` を統合。
- 同一チャットで runtime 健康確認と MI25 tuning 側ツールの併用を確認可能。

5. `compare_presets` / `tail_log(follow)` の要否再評価
- 再評価結果: 現時点では見送り（No-Go）。
- 理由:
  - `run_inference` + `read_perf_log` + `summarize_perf_log` で比較ループは成立。
  - `follow` は長時間接続と運用コスト増が大きく、現段ではメリットより負担が大きい。

## 3. 関連ファイル

- `mcp-config.phase3.json`
- `tools/bridge_agent_chat.sh`
- `tests/llm_bridge_integration_test.py`
