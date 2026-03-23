# Reference Asset Map (Applied)

最終更新: 2026-03-24  
正本: `SPEC.md`, `agreement.md`

この文書は、`MI25_TODO/MI25-tuning-MCP_TODO.md` の
「正本参照資産を実装判断に反映する」を満たすために、
どの資産をどの仕様判断に反映したかを明示する。

## 1. 参照した正本資産

- `ROCm-project/ROCm-repos_AETS`
  - `rocBLAS/`, `Tensile/` の fork 実装群（実装系の正本）
- `ROCm-project/vega-hbmx-experiments`
  - `README.md`
  - `work_log/investigations/2026-03-07_gfx900_gate_matrix.md`
  - `work_log/investigations/2026-03-07_gfx900_existing_workarounds_matrix.md`
- `ROCm-project/vega_investigations`
  - `README.md`
  - `work_logs.md`
- `ROCm-project/vega-hbmx-pages`
  - `index.html`（研究公開ページの要約）
  - `presentation_advanced_en-jp.html`（gate/fallback 可視化）

## 2. 実装・仕様への反映

### A. 観測優先（MI25/gfx900 は residual path 前提）

反映先:
- `src/mi25_tuning_mcp/server.py` の `get_gpu_metrics`, `read_perf_log`, `summarize_perf_log`
- `docs/tool-spec.md`

理由:
- 資産側で「gfx900 は default から外れても residual/fallback path が残る」ことが示されているため、
  まず観測 (`metrics + logs`) を主導線にした。

### B. build/runtime path 固定 + 安全化

反映先:
- `update_config` allowlist + `.bak`
- `run_inference` の一時 `config.json` 差し替え -> 復元
- `set_config_raw` の policy gate

理由:
- 研究資産で「正しい artifact/探索先に乗っているか」の重要性が繰り返し示されるため、
  可変点を減らす設計を優先した。

### C. 旧世代向け運用（フォールバックを壊さない）

反映先:
- `list_presets` と `gfx900_*` プリセット
- `run_inference` の conservative defaults

理由:
- `vega_investigations/work_logs.md` の文脈（MLIR iGEMM 除外・ASM/DLOPS/旧経路の活用）に合わせ、
  攻めた最適化より安定運用を先に固定した。

### D. インフラ層との責務分離

反映先:
- `mcp-config.phase3.json` で `mi25_tuning` + `rocm_ops` を同時利用
- `tests/llm_bridge_integration_test.py`（bridge 統合）

理由:
- `ROCm-ollama-mcp` をインフラ層、`MI25-tuning-MCP` を実験ワークフロー層に分離する合意に一致。

## 3. 運用上の結論

- MI25/gfx900 では「最適化」より先に「経路固定・観測・安全な反復」を優先する。
- `MI25-tuning-MCP` は thin-client / rich-MCP 方針を維持し、ツール境界を明確にする。
