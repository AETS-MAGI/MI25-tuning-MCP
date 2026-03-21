# MI25-tuning-MCP

MI25 / gfx900 向け `multi_llm-client` 運用のための MCP サーバーです。
本リポジトリの設計・運用判断は、以下の合意文書を正本とします。

- 正本: `ROCm-project/Agents-note/Rust製クライアント/MCP対応案/agreement.md`

本 README は、正本の内容を実装観点に落とした実装者向けガイドです。
正本と矛盾する場合は **正本を優先** してください。

---

## 1. 目的と責務

`MI25-tuning-MCP` は **クライアント・実験ワークフロー層** です。

担当すること:

- `multi_llm-client` の設定変更（安全な部分更新）
- 推論実行
- ログ読取・要約
- ノート記録

担当しないこと:

- GPU/ROCm/Ollama のインフラ層全般（原則 `ROCm-ollama-mcp` 側）

---

## 2. 正本参照資産（必須）

設計・チューニング判断では、以下を正本参照資産として扱います。

- rocBLAS / Tensile フォーク（実装系の正本）
  - `ROCm-project/ROCm-repos_AETS`
- 研究資産（経路検証・再現手順・観測知見）
  - `ROCm-project/vega-hbmx-experiments`
  - `ROCm-project/vega_investigations`
  - `ROCm-project/vega-hbmx-pages`

---

## 3. 固定仕様（agreement準拠）

以下は実装で必ず守る固定仕様です。

1. `update_config(overrides)` を主APIにする
- allowlist 部分マージ
- 更新前に `.bak` 作成

2. `cargo` は絶対PATH優先
- 推奨: `~/.cargo/bin/cargo`
- 裸の `cargo` 呼び出しを避ける

3. `run_inference` の設定反映方式
- `multi_llm-client` が `--config` を正式サポートするまでは、
  一時 `config.json` 差し替え -> 実行 -> 復元

4. 返却フォーマット
- 原則 `content` / `structuredContent` / `isError`

5. free-form shell は禁止
- 固定テンプレートコマンド + timeout + 出力長制限

---

## 4. 現在の実装状況

`src/mi25_tuning_mcp/server.py` 現在実装済みツール:

- `ping`
- `list_presets`
- `run_inference`
- `read_perf_log`
- `summarize_perf_log`
- `get_config`
- `update_config`
- `set_config`（互換用途。Agent主APIとしては非推奨）
- `read_file`
- `write_file`

未実装（agreementのMVP/Phase対象）:

- `get_gpu_metrics`
- `run_client_check`
- `read_inference_logs`
- 返却の `content/structuredContent/isError` 完全統一

---

## 5. セットアップ

```bash
cd ROCm-project/MI25-tuning-MCP
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

## 6. 環境変数

- `MI25_CLIENT_ROOT`
  - 既定: `ROCm-project/multi_llm-client`
- `MI25_NOTES_ROOT`
  - 既定: `ROCm-project/Agents-note`

---

## 7. 安全制約

- `update_config`
  - allowlist キーのみ更新
  - `.bak` 自動作成
- `write_file`
  - `Agents-note/` 配下のみ書き込み
- `read_file`
  - プロジェクトルート配下のみ
- `run_inference`
  - timeout 必須
  - 実行後は config を復元
  - 出力長を制限

---

## 8. フェーズ計画（実装順）

Phase 0:

- `README.md`
- `server.py`
- `mcp-config.json`
- `docs/tool-spec.md`
- `tests/smoke.sh`

Phase 1 (MVP):

- `ping`
- `get_gpu_metrics`
- `get_config`
- `update_config`
- `run_inference`
- `read_perf_log`
- `summarize_perf_log`

Phase 2:

- `read_inference_logs`
- `run_client_check`
- 監査ログ JSONL

Phase 3:

- `multi_llm-client` 側 tool-calling 連携
- `max_tool_roundtrips` / `allowed_tools` 適用

---

## 9. 最低検証フロー

1. `ping`
2. `get_config`
3. `update_config`（例: `{"preset": "gfx900_safe"}`）
4. `run_inference`
5. `read_perf_log`
6. `summarize_perf_log`

この6ステップが再現できれば、MVP運用の基礎が成立します。

---

## 10. 参照

- 正本合意: `ROCm-project/Agents-note/Rust製クライアント/MCP対応案/agreement.md`
- TODO: `ROCm-project/MI25-tuning-MCP/TODO.md`
- 関連MCP（インフラ層）: `ROCm-project/ROCm-ollama-mcp`
