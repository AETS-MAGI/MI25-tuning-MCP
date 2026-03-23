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

---

## 10. 追加反復（preset n=10 / thread 4,6 長時間）

source: [main-node confirmed]  
`multi_llm-client/worklog/2026-03-24_phase3-extended-bench.md`

tinyllama preset sweep（steady）:

| preset | n | steady_ttft_ms | steady_tok/s |
|---|---:|---:|---:|
| `gfx900_safe` | 9 | 112.44 | 215.87 |
| `gfx900_balanced` | 9 | 94.44 | 216.46 |
| `gfx900_longctx` | 9 | 103.67 | 213.37 |

thread 4/6 比較:

| model | num_thread | n | steady_ttft_ms | steady_tok/s |
|---|---:|---:|---:|---:|
| tinyllama | 4 | 19 | 99.95 | 213.65 |
| tinyllama | 6 | 19 | 96.63 | 217.70 |
| qwen2.5:7b | 4 | 9 | 296.33 | 49.36 |
| qwen2.5:7b | 6 | 9 | 292.00 | 48.65 |

更新結論:

- 研究基準は `gfx900_safe` のまま維持。
- クロスモデル既定値は `num_thread=4` を採用（qwen 側の安定性を優先）。
- tinyllama 吞吐特化プロファイルとして `num_thread=6` を別線で保持。

---

## 11. dispatch 境界プローブ（timestamp + rocBLAS trace）

source: [main-node confirmed]  
- `ROCm-MI25-build/g4-fallback-strace-check.sh`（拡張版）
- `ROCm-MI25-build/summarize-fallback-phases.sh`
- `ROCm-MI25-build/vega_path_check_logs/g4_summary_tinyllama_latest_20260324_014707.txt`
- `ROCm-MI25-build/vega_path_check_logs/fallback_phase_summary_tinyllama_latest_20260324_014707.tsv`

計測要点:

| 指標 | 値 | 解釈 |
|---|---:|---|
| `strace_timestamp` | `1` | `-tt` で時系列比較を有効化 |
| `fallback_dat_openat` | `54` | fallback catalog（dat）読込あり |
| `fallback_hsaco_openat` | `54` | fallback kernel（hsaco）読込あり |
| dat span | `0.035186s` | 初期化バースト寄り |
| hsaco span | `1.302794s` | 実行中にも分布する可能性 |
| `rocblas_trace_handle_lines` | `1` | rocBLAS handle 作成は観測 |
| `rocblas_trace_gemm_lines` | `0` | GEMM 呼び出し行は未観測 |

判定:

- `catalog read` と `dispatch` の境界観測は前進。
- ただし dispatch 直接証跡（GEMM 呼び出し行）までは未到達。
- 次段は rocBLAS trace の粒度改善、または別トレース手段の併用が必要。

追加確認:

- `ROCBLAS_LAYER=63` の短時間再プローブでも `rocblas_trace_gemm_lines=0`（`g4_summary_tinyllama_latest_20260324_015056.txt`）。

---

## 12. rocprofv3 kernel dispatch probe（tinyllama）

source: [main-node confirmed]  
- `ROCm-MI25-build/g4-rocprofv3-dispatch-check.sh`
- `ROCm-MI25-build/vega_path_check_logs/rocprofv3_summary_tinyllama_latest_20260324_020034.txt`

要点:

| 指標 | 値 |
|---|---:|
| `kernel_dispatch_rows` | 3605 |
| `kernel_mul_mat_q_rows` | 151 |
| `kernel_mul_mat_vec_rows` | 934 |
| `kernel_flash_attn_rows` | 352 |
| `kernel_quantize_rows` | 1085 |
| `kernel_tensile_like_rows` | 0 |

解釈:

- dispatch 直接証跡（kernel trace）は取得に成功。
- ただし今回の run では、観測 kernel は ggml-hip 側が中心。
- `rocBLAS/Tensile` 名の dispatch は未観測で、`fallback` 資産アクセスとの直結は継続課題。

---

## 13. fallback+dispatch 統合ゲート（2026-03-24）

source: [main-node confirmed]  
- `ROCm-MI25-build/g4-fallback-dispatch-link-check.sh`
- `ROCm-MI25-build/vega_path_check_logs/g4_link_summary_tinyllama_latest_20260324_020803.txt`
- `ROCm-MI25-build/vega_path_check_logs/g4_link_summary_qwen2.5_7b_20260324_021010.txt`

要点:

| model | `fallback_confirmed` | `dispatch_confirmed` | `direct_rocblas_or_tensile_dispatch` | `rocblas_trace_gemm_lines` | `kernel_tensile_like_rows` | `link_status` |
|---|---:|---:|---:|---:|---:|---|
| `tinyllama:latest` | 1 | 1 | 0 | 0 | 0 | `indirect_link_only_same_scenario` |
| `qwen2.5:7b` | 1 | 1 | 0 | 0 | 0 | `indirect_link_only_same_scenario` |

判定:

- G4 以降の Phase 2 は、`fallback + dispatch` の同時観測まで前進。
- 上記 2 モデルで同じ判定になり、現状のボトルネックは model 固有ではなく経路可視化側に寄っている。
- 次の達成条件は `direct_rocblas_or_tensile_dispatch=1` を1件確保すること。

---

## 14. ROCBLAS_LAYER スイープ（trace 粒度確定, 2026-03-24）

source: [main-node confirmed]  
- `ROCm-MI25-build/g4-rocblas-layer-sweep.sh`
- `ROCm-MI25-build/vega_path_check_logs/g4_rocblas_layer_sweep_tinyllama_latest_20260324_021652.txt`
- `ROCm-MI25-build/vega_path_check_logs/g4_rocblas_layer_sweep_qwen2.5_7b_20260324_021747.txt`

比較（共通傾向）:

| layer | tinyllama `trace_lines/gemm_lines` | qwen `trace_lines/gemm_lines` | 備考 |
|---:|---:|---:|---|
| 1 | `1 / 0` | `1 / 0` | `rocblas_create_handle` のみ |
| 8 | `0 / 0` | `0 / 0` | internal 単体では有効行なし |
| 9 | `1 / 0` | `1 / 0` | trace + internal |
| 15 | `1 / 0` | `1 / 0` | bench/profile 有効でも行増加なし |
| 63 | `1 / 0` | `1 / 0` | 15 と同等（過剰ビット） |

確定:

- 観測既定値は `ROCBLAS_LAYER=9` を採用。
- 理由:
  - `1` と同等の情報を維持しつつ internal(bit 8) を保持
  - `63` より運用が単純
- なお現行 GGUF run では `bench/profile` は 0 行、`gemm` 行も 0 のまま。

次段:

- `ROCBLAS_LAYER` 探索は完了扱い。
- 以後は「rocBLAS GEMM を実際に呼ぶ workload 条件」の探索へ移る。
