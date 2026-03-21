# MI25-tuning-MCP 仕様書

バージョン: 1.0.0
作成日: 2026-03-22
参照合意書: `/home/limonene/ROCm-project/Agents-note/Rust製クライアント/MCP対応案/agreement.md`

---

## 0. 目的と前提

本仕様書は、`MI25-tuning-MCP` の設計・実装・テスト・運用における判断基準を定める。

### 0.1 正本参照資産

設計・実装・チューニング判断においては、以下を**正本参照資産**として扱う。

| 資産 | パス | 用途 |
|------|------|------|
| rocBLAS / Tensile フォーク | `ROCm-project/ROCm-repos_AETS` | 実装系の正本 |
| 研究資産（経路検証） | `ROCm-project/vega-hbmx-experiments` | 観測知見・再現手順 |
| 研究資産（調査記録） | `ROCm-project/vega_investigations` | 経路動作の実証知見 |
| 研究資産（ページ） | `ROCm-project/vega-hbmx-pages` | 観測知見まとめ |

これらには「どの経路が実際に生きているか」「どの条件でフォールバックするか」「どの観測が有効か」といった実証知見が蓄積されている。MCP ツール仕様・プリセット設計・ログ要約・チューニング判断は、上記資産を起点として行う。

### 0.2 設計前提

本仕様は **「thin client / rich MCP」** を前提とする。Agent が `multi_llm-client` を安全に扱いながら、gfx900/MI25 の観測・設定変更・推論実行・ログ要約を再現可能に行えることを目的とする。

---

## 1. 設計方針

### 1.1 基本原則

- **thin client / rich MCP**: クライアントは薄い橋とし、運用責務は MCP へ寄せる
- **安全性優先**: allowlist / timeout / パス制限 / 出力長制限を標準で有効化する
- **段階的安定化**: まず MCP 単体を安定させ、LLM 統合は後段で行う
- **テスト順序**: 「MCP単体 → プロトコル → LLM統合」の順で進める
- **後段への先送り**: Rust 側の agent loop / tool-calling 連携は MCP 単体が安定してから着手する

### 1.2 ツール設計原則

- ツールは「目的ベース」で小さく作る
- 任意シェルの全面開放はしない
- 失敗時は必ず **機械可読 + 人間可読** で返す
- 出力長制限を標準で有効化する
- 返却の基本形は `content` / `structuredContent` / `isError`

---

## 2. 責務と境界

### 2.1 MCPサーバーの責務分離

| サーバー | 責務 | 対象 |
|----------|------|------|
| `ROCm-ollama-mcp` | 環境・インフラ層 | GPU/ROCm/Ollama の基盤観測とモデル管理 |
| `MI25-tuning-MCP` | クライアント・実験ワークフロー層 | `multi_llm-client` の設定変更、推論実行、ログ読取、要約、ノート化 |

`MI25-tuning-MCP` は `ROCm-ollama-mcp` の代替ではなく、**Rust クライアント運用の上位ワークフロー層**として位置づける。

### 2.2 Rust クライアント（multi_llm-client）の扱い

| 時期 | 方針 |
|------|------|
| 短期 | `multi_llm-client` は変更しない。MCP 側が subprocess として `cargo run` または既存バイナリを呼ぶ |
| 中期 | 非対話入口（`--prompt` / `--oneshot` / `--config` 相当）は追加候補とする |
| 後期 | `agent_enabled` / `max_tool_roundtrips` / `allowed_tools` / `raw_infer()` と `agent_infer()` の分離は、MCP 単体が安定してから着手する |

### 2.3 gfx900/MI25 の観測前提

MI25/gfx900 は、ASM implicit GEMM・DLOPS・Winograd・rocBLAS/Tensile lazy loading・dot4 不在時の代替積和など、**旧世代寄り・フォールバック寄りの経路が重要**なアーキテクチャである。MLIR iGEMM や XDLops は候補から落ちやすく、ASM / DLOPS / 非 dot4 経路が相対的に重要になる。

このため、`MI25-tuning-MCP` の MVP は「速くする道具」より先に「**状況を見える化する道具**」であることを優先する。推論実行と並んで、GPU 使用状況とログ要約の観測系を必ず MVP スコープに含める。

---

## 3. 実装スコープ（Phase 別）

### Phase 0 — 骨組み

**成果物:**

| ファイル | 内容 |
|----------|------|
| `README.md` | 使い方・制約・フェーズ計画 |
| `src/mi25_tuning_mcp/server.py` | stdio MCP 本体（Python） |
| `mcp-config.json` | ブリッジ接続例 |
| `docs/tool-spec.md` | ツール仕様詳細 |
| `tests/smoke.sh` | 基本動作確認スクリプト |

**方針:**

- Python 実装を初期採用とする
- 初期は単一ファイル `server.py` で立ち上げを優先する
- 依存は軽量に保つ

### Phase 1 — 最小運用 MVP

**必須ツール:**

| ツール | 備考 |
|--------|------|
| `ping` | ヘルスチェック |
| `get_gpu_metrics` | MI25 の VRAM / 温度 / 使用率を機械可読で返す |
| `get_config` | config.json の読み取り |
| `update_config` | allowlist 部分マージ・`.bak` 作成 |
| `run_inference` | Rust クライアントによる推論実行 |
| `read_perf_log` | JSONL ログの末尾 N 件取得 |
| `summarize_perf_log` | TTFT / tok/s / エラー率などの集計 |

**補助ツール（任意）:**

| ツール | 備考 |
|--------|------|
| `read_file` | プロジェクトルート配下の読み取り |
| `write_file` | `Agents-note/` 配下への書き込み |
| `list_presets` | プリセット一覧と既定パラメータ |

**採用理由:**

- `run_inference` は Rust クライアントの既存ログを活用できる
- `read_perf_log` / `summarize_perf_log` は TTFT・tok/s・エラー率をすぐ比較できる
- `update_config` は Agent に安全な部分変更 API を提供できる
- `get_gpu_metrics` は MI25/gfx900 の VRAM 制約や負荷変動を判断する材料になる

### Phase 2 — 運用強化

| ツール / 機能 | 内容 |
|---------------|------|
| `read_inference_logs` | tail / filter 付きの広域履歴参照 |
| `run_client_check` | `~/.cargo/bin/cargo check` 固定実行 |
| `list_dir` | ディレクトリ一覧 |
| `read_text` | テキストファイル読み取り |
| 監査ログ | MCP tool call 履歴 JSONL |
| `write_file` 安定化 | 書き込み制限の整備 |
| `list_presets` 正式化 | `docs/tool-spec.md` への仕様記載 |

### Phase 3 — 連携強化

| 項目 | 内容 |
|------|------|
| `multi_llm-client` 側 tool-calling 連携 | 必要時のみ着手 |
| `agent_enabled` / `max_tool_roundtrips` / `allowed_tools` 適用 | クライアント側拡張後に対応 |
| ブリッジ経由の収束性テスト | ループが収束することを検証 |
| `ROCm-ollama-mcp` との連携強化 | インフラ層との協調 |
| `compare_presets` / `tail_log(follow=True)` | 必要性を再評価してから実装 |

Phase 3 は MCP 単体が安定し、Phase 1 / Phase 2 が十分稼働してから着手する。

---

## 4. 設計決定事項

### 4.1 `rocm_status` / `ollama_health` の配置

- `rocm_status` と `ollama_health` は `ROCm-ollama-mcp` 側を正とし、`MI25-tuning-MCP` には重複実装しない
- ただし `get_gpu_metrics` は **MI25 チューニング特化の軽量観測 API** として `MI25-tuning-MCP` に配置する
  - 理由: MI25/gfx900 チューニングの自律ループ（VRAM 確認 → config 変更 → 推論 → ログ確認）に直結するため

### 4.2 `run_tuning_benchmark` の扱い

- 単一ツールへの責務集中を避けるため、`run_tuning_benchmark` は採用しない
- 代わりに `run_inference` + `read_perf_log` + `summarize_perf_log` に分解して提供する
- 複数プロンプト / 複数プリセット比較が必要になった場合のみ、`compare_presets` 系を追加する

### 4.3 テスト戦略

- MCP 単体テストが整備されるまで LLM 統合テストへ進まない
- テスト順序は「**MCP単体 → MCPプロトコル → LLM統合**」の3層とする

### 4.4 `update_config` / `set_config` の仕様

- Agent 用の主 API は `update_config(overrides)` とする
- 更新方式: **allowlist 部分マージ**
- 更新前に必ず `.bak` を作成する
- **全体上書き API（`set_config`）は Phase 1 スコープに含めない**
- 将来、管理者向けに全体上書きが必要な場合は `set_config_raw` として明示分離する

---

## 5. 安全制約

### 5.1 パス制約

| 操作 | 許可範囲 |
|------|----------|
| 読み取り | プロジェクトルート配下 |
| 書き込み | `Agents-note/` 配下 および `multi_llm-client/config.json` のみ |

### 5.2 設定変更

| 制約 | 内容 |
|------|------|
| `update_config` | allowlist に含まれるキーのみ更新する |
| バックアップ | 更新前に必ず `.bak` を保存する |

### 5.3 subprocess 実行

| 制約 | 内容 |
|------|------|
| コマンド | 固定テンプレートのみ許可する（free-form shell は禁止） |
| timeout | 全 subprocess 呼び出しで必須 |
| 出力長 | 上限を設定し、超過分はトリミングする |

### 5.4 返却フォーマット

全ツールの返却は `content` / `structuredContent` / `isError` を基本形とする。

### 5.5 監査

MCP 側で tool call 履歴を JSONL として記録する（Phase 2 で実装）。

---

## 6. 実行環境の固定仕様

### A. `cargo` の実行パス

- `cargo` は裸で呼ばない
- 実行パスの優先順: `~/.cargo/bin/cargo` → `/usr/local/bin/cargo` → `/usr/bin/cargo`
- 目的: `/usr/bin/cargo`（旧版）の誤利用を防止し、`Cargo.lock` v4 問題を回避する

### B. `run_inference` の設定反映方式

- `multi_llm-client` が `--config` を正式サポートするまでは「**一時 `config.json` 差し替え → 実行 → 復元**」を採用する
- 実行後は必ず元の `config.json` を復元する（プロセスが異常終了した場合も含む）
- 将来 `--config` / `--prompt` / `--oneshot` が実装された場合は、そちらへ移行する
- 目的: MCP 側の `preset` / `model` 指定が無効化される事故を防ぐ

### C. 観測系の動作要件

- `get_gpu_metrics`: ツール自体は失敗しない。rocm-smi 未導入や取得不可の場合も「未導入」「取得不可」を機械可読で返す
- `summarize_perf_log`: JSONL 不在時も落とさず、空結果を返す
- `run_inference`: stdout のみを真実源とせず、**ログファイルの生成有無**も返す
- ログの記録項目: TTFT / tok/s に加えて preset / model / error の有無を含める

---

## 7. 完了条件（DoD）

MVP 完了は以下の全項目を満たした時点とする。

| # | 条件 |
|---|------|
| 1 | `MI25-tuning-MCP` が stdio MCP として起動する |
| 2 | Phase 1 必須ツールが動作する |
| 3 | `config.json` の安全更新（`.bak` 付き）が動作する |
| 4 | `run_inference → read_perf_log → summarize_perf_log` が一連で再現できる |
| 5 | `get_gpu_metrics` が実機および未導入環境で可観測な結果を返す |
| 6 | 失敗ケースで原因が `isError` とメッセージで返る |
| 7 | MCP 単体テストと MCP プロトコルテストが通る |

---

## 8. 実装優先順序

1. Phase 0 / Phase 1 を優先実装する
2. `ROCm-ollama-mcp` との責務重複を避ける
3. `get_gpu_metrics` / `update_config` / `run_inference` / `read_perf_log` / `summarize_perf_log` を MVP コアとして実装する
4. 実装後に `MI25-tuning-MCP` ディレクトリへ検証レポートを追記する
5. Rust 側の tool-calling 連携は MCP 単体安定後に Phase 3 で再評価する
