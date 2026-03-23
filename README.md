# MI25-tuning-MCP

MI25 / gfx900 向け `multi_llm-client` 運用のための MCP サーバーです。

---

## 目的と責務

`MI25-tuning-MCP` は **クライアント・実験ワークフロー層** を担います。

| 担当する | 担当しない |
|----------|-----------|
| `multi_llm-client` の設定変更（安全な部分更新） | GPU / ROCm / Ollama のインフラ観測 |
| 推論実行・ログ読取・要約 | → `ROCm-ollama-mcp` が担当 |
| ノート記録 | |

---

## セットアップ

```bash
cd /home/limonene/ROCm-project/MI25-tuning-MCP
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

起動:

```bash
mi25-tuning-mcp
```

---

## ツール一覧

| ツール | 概要 |
|--------|------|
| `ping` | ヘルスチェック・パス確認 |
| `get_gpu_metrics` | rocm-smi 経由で MI25 の VRAM / 温度 / 使用率を取得（未導入でも非エラー返却） |
| `list_presets` | gfx900 プリセット名とデフォルトパラメータ一覧 |
| `get_config` | `config.json` の読み取り |
| `update_config` | allowlist キーを部分マージで更新（`.bak` 自動作成） |
| `run_inference` | Rust クライアントでワンショット推論を実行 |
| `read_perf_log` | JSONL ログの末尾 N 件を取得 |
| `read_inference_logs` | `read_perf_log` の別名（広域履歴参照用） |
| `summarize_perf_log` | TTFT / tok/s / エラー率などを集計 |
| `list_dir` | ディレクトリ一覧（プロジェクトルート配下） |
| `read_text` / `read_file` | テキストファイル読み取り（プロジェクトルート配下） |
| `write_file` | ノートへの書き込み（`Agents-note/` 配下限定） |
| `run_client_check` | `cargo check` を実行してビルドエラーを確認 |
| `set_config_raw` | 設定の全体上書き（`MI25_ENABLE_SET_CONFIG_RAW=1` で有効化、既定は無効） |

---

## 環境変数

| 変数 | 既定値 | 説明 |
|------|--------|------|
| `MI25_CLIENT_ROOT` | `../multi_llm-client` | Rust クライアントのディレクトリ |
| `MI25_NOTES_ROOT` | `../Agents-note` | `write_file` の書き込み先ルート |
| `MI25_MCP_AUDIT_LOG` | `./logs/tool-calls.jsonl` | 監査ログの出力先 |
| `MI25_ENABLE_SET_CONFIG_RAW` | `0` | `set_config_raw` の有効化フラグ |

---

## 安全制約

- **`update_config`**: allowlist 外のキーは拒否。更新前に `.bak` を保存
- **`write_file`**: `Agents-note/` 配下のみ書き込み可
- **`read_file` / `read_text` / `list_dir`**: プロジェクトルート配下のみ参照可
- **`run_inference`**: タイムアウト必須、実行後に `config.json` を必ず復元
- **`set_config_raw`**: 既定無効。明示的な環境変数が必要
- **subprocess**: 固定コマンドテンプレートのみ使用（free-form shell 禁止）
- **全ツール**: 監査ログ JSONL に tool call を記録

---

## Claude Code への接続

`~/.claude/settings.json` の `mcpServers` に追加します:

```json
{
  "mcpServers": {
    "mi25_tuning": {
      "command": "/home/limonene/ROCm-project/MI25-tuning-MCP/.venv/bin/mi25-tuning-mcp",
      "args": [],
      "cwd": "/home/limonene/ROCm-project/MI25-tuning-MCP",
      "env": {
        "MI25_CLIENT_ROOT": "/home/limonene/ROCm-project/multi_llm-client",
        "MI25_NOTES_ROOT": "/home/limonene/ROCm-project/Agents-note"
      }
    }
  }
}
```

または `mcp-config.json` を `ollama-mcp-bridge` 経由で使用することもできます。

---

## Antigravity MCP 設定

Antigravity で使う場合は `~/.gemini/antigravity/mcp_config.json` に `mcpServers` を定義します。
テンプレートをコピーして実パスを展開します:

```bash
export ROCM_PROJECT_ROOT="/home/limonene/ROCm-project"
cp "${ROCM_PROJECT_ROOT}/MI25-tuning-MCP/mcp_config.template.json" \
  "${HOME}/.gemini/antigravity/mcp_config.json"
sed -i "s#<ROCM_PROJECT_ROOT>#${ROCM_PROJECT_ROOT}#g" \
  "${HOME}/.gemini/antigravity/mcp_config.json"
```

- `command` は絶対パスを使用してください
- 反映後は Antigravity の Language Server を再起動（または Window Reload）
- Claude Code と併用する場合はプロジェクトルートの `.mcp.json` と内容を揃えると管理が楽です

---

## 動作確認

インストール後、以下の順で疎通を確認します:

```
ping → get_config → update_config → run_inference → read_perf_log → summarize_perf_log
```

---

## テスト実行

```bash
cd /home/limonene/ROCm-project/MI25-tuning-MCP
source .venv/bin/activate
./tests/smoke.sh

# LLM 統合テストも実行する場合
MI25_RUN_LLM_INTEGRATION=1 ./tests/smoke.sh
```

`smoke.sh` が実行するテスト:

1. コンパイルチェック + ツール形状チェック
2. `tests/unit_direct_test.py` — MCP 単体 / 失敗系 / サンドボックス統合
3. `tests/protocol_tools_test.py` — stdio MCP プロトコル（`tools/list` / `tools/call`）
4. `tests/llm_bridge_integration_test.py` — ブリッジ経由 LLM 統合（`MI25_RUN_LLM_INTEGRATION=1` で有効）

---

## 関連ドキュメント

| ドキュメント | 内容 |
|------------|------|
| [SPEC.md](SPEC.md) | 仕様書（設計決定・安全制約・DoD） |
| [MI25-tuning-MCP_TODO.md](../MI25_TODO/MI25-tuning-MCP_TODO.md) | 実装状況・残課題（MI25_TODO集約） |
| [docs/tool-spec.md](docs/tool-spec.md) | ツール仕様詳細 |
| [vega_optimize.md](vega_optimize.md) | Vega/gfx900 最適化の定性戦略メモ |
| [vega_optimize-statistics.md](vega_optimize-statistics.md) | Vega/gfx900 最適化の定量メモ（実測値） |
| [agreement.md](../Agents-note/Rust製クライアント/MCP対応案/agreement.md) | 正本合意書 |
| [ROCm-ollama-mcp](../ROCm-ollama-mcp) | インフラ層 MCP（GPU / ROCm / Ollama 観測） |
