# Vega最適化 統計メモ（MI25/gfx900）

最終更新: 2026-03-24  
用途: `vega_optimize.md` の定性戦略に対応する定量メモ。

---

## 1. 方針と判定軸

- 基準 preset: `gfx900_safe`
- 判定軸:
  - 遅延: `ttft_ms`
  - 吞吐: `approx_tok_per_sec`
  - 経路確定: `fallback_confirmed`（runtime 証跡）

---

## 2. preset sweep（tinyllama）

source: [main-node confirmed] `multi_llm-client/client_index.md` Section 9

| preset | ttft_ms (steady2) | total_ms (steady2) | tok/s (steady2) | メモ |
|---|---:|---:|---:|---|
| `gfx900_safe` | 112.0 | 745.5 | 221.47 | 基準運用 |
| `gfx900_balanced` | 137.5 | 1079.5 | 223.73 | 吞吐優位 |
| `gfx900_longctx` | 141.0 | 770.0 | 224.77 | 長文脈向け |
| `gfx900_tinybench` | 118.5 | 281.5 | 219.71 | 短時間測定向け |

暫定解釈:

- 研究基準値は `safe`（TTFT の安定性重視）
- 吞吐最適化は `balanced` を別線で継続

---

## 3. G4 fallback_confirmed 実測

source: [main-node confirmed]  
`ROCm-MI25-build/vega_path_check_logs/g4_summary_tinyllama_latest_20260324_005717.txt`

- `libggml_hip_openat=4`
- `fallback_dat_openat=54`
- `fallback_hsaco_openat=54`

観測された runtime openat 対象（抜粋）:

- `TensileLibrary_Type_*_fallback.dat`
- `TensileLibrary_Type_*_fallback_gfx900.hsaco`

判定:

- `G4 fallback_confirmed` は達成。
- Ollama journal の `falling back` 文字列未観測でも、runtime 資産アクセス証跡で gate を満たす。

---

## 4. 参照証跡

- `ROCm-MI25-build/g4-fallback-strace-check.sh`
- `ROCm-MI25-build/vega_path_check_logs/g4_summary_tinyllama_latest_20260324_005717.txt`
- `ROCm-MI25-build/vega_path_check_logs/g4_strace_openat_tinyllama_latest_20260324_005717.log*`
- `Workspace-map.md` Section 15（ゲート更新）

---

## 5. 次の定量タスク（Phase 3）

1. 問題サイズ別 solver 選択マップ（small/medium/large）を作る  
2. `safe` 固定で `NumThreads` 感度（2/4/6）を再測  
3. `keep_alive=0s/10m` の warm 影響を model 別に比較  
4. `balanced` の吞吐優位が再現するかを 10 回反復で確認

---

## 6. 自動化の追加（2026-03-24）

source: [main-node confirmed] `multi_llm-client/scripts/phase3_bench.sh`

- one-shot CLI と sweep スクリプトを追加し、preset/thread/keep_alive 比較を再現実行可能化
- smoke (`preset-sweep`, repeat=1) の参考値:

| preset | ttft_ms | total_ms | tok/s |
|---|---:|---:|---:|
| `gfx900_safe` | 1444 | 2101 | 214.21 |
| `gfx900_balanced` | 1517 | 2557 | 200.27 |
| `gfx900_longctx` | 1797 | 2453 | 212.65 |
| `gfx900_tinybench` | 1530 | 1742 | 164.76 |

注記:

- 上表は smoke の単回値。意思決定には反復平均（n>=10）を使う。
- 既定方針は維持: 研究基準は `gfx900_safe`、吞吐最適化は `balanced` を別線で評価。
