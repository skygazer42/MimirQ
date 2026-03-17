# Retrieval API Examples

面向开源贡献者的最小可运行示例，聚焦检索质量排查与回归复现。

## Prerequisites

1. 启动最小检索环境：
   - `make up-retrieval-dev`
2. 使用 header 模式鉴权（本地默认）时，请携带：
   - `X-Tenant-ID`
   - `X-User-ID`

## 1) 查看检索 profile 定义

```bash
curl -sS http://localhost:8000/api/v1/retrieval/profiles \
  -H "X-Tenant-ID: 00000000-0000-0000-0000-000000000001" \
  -H "X-User-ID: local-dev-user" | jq .
```

用途：
- 查看支持的 profile（`recall20/recall50/coverage80/hybrid_ce`）
- 查看运行时 defaults 与 `version_hash`

## 2) 单查询 explain（retrieval-only）

```bash
curl -sS http://localhost:8000/api/v1/retrieval/explain \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 00000000-0000-0000-0000-000000000001" \
  -H "X-User-ID: local-dev-user" \
  -d '{
    "query": "解释 recall 下降可能来自哪些阶段",
    "retrieval_only": true,
    "rag_config": {
      "retrieval_profile": "recall50",
      "retrieval_mode": "hybrid",
      "top_k": 50
    }
  }' | jq .
```

重点字段：
- `channels`
- `candidate_counts`
- `top_citations`
- `rerank`
- `stage_timings`

## 2.1) 单查询 explain（Hierarchy Recall Overlay）

当你希望提升“同一文档结构族（family）”层面的召回稳定性，或希望在不改解析/不改索引结构的前提下做轻量的层级去重与上下文扩展，可以使用 hierarchy profile（或显式打开开关）。

可用 profile（以当前版本为准）：
- `hierarchy_recall20`：recall-first，适合做离线对比/排查召回缺失。
- `hierarchy_recall20_expand`：recall-first + 默认开启 parent/sibling 上下文扩展（便于快速对照 KohakuRAG 类范式）。
- `hierarchy_hybrid_ce`：production baseline + hierarchy overlay defaults。
- `hierarchy_grounded_strict`：strict grounded baseline + hierarchy overlay defaults。

示例：

```bash
curl -sS http://localhost:8000/api/v1/retrieval/explain \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 00000000-0000-0000-0000-000000000001" \
  -H "X-User-ID: local-dev-user" \
  -d '{
    "query": "为什么同一段落上下文经常检索不到？",
    "retrieval_only": true,
    "rag_config": {
      "retrieval_profile": "hierarchy_hybrid_ce",
      "retrieval_mode": "hybrid",
      "top_k": 20,
      "hierarchy_parent_depth": 1,
      "hierarchy_sibling_window": 1
    }
  }' | jq .
```

重点字段：
- `hierarchy_recall`：是否启用、family collapse/aggregation、tree dedup、context expansion 等关键信号。
- `top_citations[*].retrieval_role`：`main` vs `hierarchy_parent` / `hierarchy_sibling`（用于区分“主证据”与“层级补充上下文”）。

## 3) 生成 retrieval config hash（可复现对比）

```bash
curl -sS http://localhost:8000/api/v1/retrieval/config-hash \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 00000000-0000-0000-0000-000000000001" \
  -H "X-User-ID: local-dev-user" \
  -d '{
    "rag_config": {
      "retrieval_profile": "hybrid_ce",
      "retrieval_mode": "hybrid",
      "top_k": 20,
      "enable_reranker": true,
      "reranker_provider": "cross_encoder",
      "reranker_top_n": 20
    },
    "include_runtime_defaults": true
  }' | jq .
```

用途：
- 对同配置运行进行稳定比对（hash 一致）
- 对有意义参数变化进行差异定位（hash 改变）

## 4) 回归门禁与消融 CLI（离线）

```bash
python scripts/regression_gate.py --help
python scripts/retrieval_ablation.py --help
```

建议：
- 先用 `scripts/regression_gate.py` 固化阈值门禁，再用 `scripts/retrieval_ablation.py` 做 profile / fusion / rerank 组合分析。
- 报告产物可回填到发布说明中的 Retrieval Quality 区块。
