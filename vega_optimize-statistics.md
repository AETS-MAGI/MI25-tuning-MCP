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

---

## 7. Phase3 初回一括測定（2026-03-24, all x3）

source: [main-node confirmed]  
`multi_llm-client/worklog/bench_phase3_all_20260324.tsv`

条件:

- mode: `all`（preset/thread/keep_alive）
- repeat: `3`
- model: `tinyllama:latest`
- prompt: `short test`

steady（repeat_idx=2,3）集計:

| 条件 | steady_ttft_ms | steady_tok/s |
|---|---:|---:|
| preset `gfx900_safe` | 103.0 | 207.47 |
| preset `gfx900_balanced` | 89.0 | 214.93 |
| preset `gfx900_longctx` | 84.5 | 215.28 |
| thread `2` (`safe`) | 104.0 | 202.91 |
| thread `4` (`safe`) | 88.5 | 208.41 |
| thread `6` (`safe`) | 128.5 | 216.37 |
| keep_alive `0s` (`safe`) | 1239.5 | 209.04 |
| keep_alive `10m` (`safe`) | 127.0 | 215.82 |

暫定解釈:

- `keep_alive=10m` は TTFT 安定化に有効（`0s` より大幅改善）。
- `num_thread=6` は tok/s は高いが TTFT が悪化。`num_thread=4` は中庸。
- 研究基準値としては引き続き `gfx900_safe` を維持し、運用最適化候補は別線で評価する。

---

## 8. n=10 反復測定（2026-03-24）

source: [main-node confirmed]  
`multi_llm-client/worklog/2026-03-24_phase3-n10-results.md`

### 8.1 tinyllama: thread (`safe`, keep_alive=10m)

steady（rep>=2）:

| num_thread | n | steady_ttft_ms | steady_tok/s |
|---|---:|---:|---:|
| 2 | 9 | 90.89 | 213.61 |
| 4 | 9 | 100.00 | 214.24 |
| 6 | 9 | 105.11 | 215.26 |

### 8.2 keep_alive 比較 (`safe`)

tinyllama steady（rep>=2）:

| keep_alive | n | steady_ttft_ms | steady_tok/s |
|---|---:|---:|---:|
| 0s | 9 | 1245.44 | 201.70 |
| 10m | 9 | 113.22 | 212.86 |

qwen2.5:7b steady（rep>=2）:

| keep_alive | n | steady_ttft_ms | steady_tok/s |
|---|---:|---:|---:|
| 0s | 9 | 3413.89 | 46.91 |
| 10m | 9 | 284.33 | 49.47 |

### 8.3 実務向け結論

- 研究基準は `gfx900_safe` 固定を維持。
- `keep_alive=10m` は 2モデルで一貫して有利（TTFT/tok/s とも改善）。
- `num_thread` は `4` を既定候補（バランス重視）。
- 吞吐最優先ケースのみ `num_thread=6` を候補化する。

---

## 9. fallback 型別集計（catalog read）

source: [main-node confirmed]  
`ROCm-MI25-build/vega_path_check_logs/fallback_type_summary_tinyllama_20260324.txt`

要点:

- `matched_lines=108`（`.dat` 54 + `.hsaco` 54）
- 型別（上位）:
  - `Type_CC: 18`
  - `Type_ZZ: 18`
  - `Type_HH: 8`
  - `Type_HS_HPA: 8`
  - `Type_HH_HPA: 8`

留保:

- これは dispatch の直接証跡ではなく、catalog read の型分布を示す。
- 次段は GEMM 呼び出し粒度の dispatch 追跡。
