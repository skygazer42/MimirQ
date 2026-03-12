# LTR Reranker（XGBoost）指南

LTR（Learning-to-Rank）用于把多个检索信号（dense/bm25/lexical/sparse/KG 角色等）组合成一个可学习的排序函数。

本仓库提供的是一个 **可插拔、可回归** 的 xgboost LTR 骨架：
- deterministic tests 可跑通
- 生产默认不启用（必须显式配置 model path）

当前 provider tier：
- `ltr`：`prod`
- 推荐用途：在你已经有稳定训练数据和 registry/rollback 流程之后，作为生产精排路径
- 如果你只是想先建立一个明确的 production baseline，请先用 `retrieval_profile=hybrid_ce`

代码位置：
- `app/rag/reranker/ltr.py`
- `app/rag/reranker/factory.py`（provider wiring）

---

## 1) 特征规范（Feature Spec）

特征顺序必须稳定（训练与推理一致）：
- 见 `app/rag/reranker/ltr.py:LTRFeatureSpec.v1()/v2()/v3()`

### v1（默认）

默认 spec 是 v1（兼容已有模型工件）：
- `vector_score`
- `bm25_score`
- `lexical_score`
- `sparse_score`
- `base_score`
- `role_*` one-hot（用于把 query expansion/KG 注入等 “来源角色” 作为信号）

### v2（可选，包含 KG 排序特征）

v2 在 v1 基础上加入一组低基数 KG 特征（用于把 KG 从 “召回扩展” 提升为 “排序信号来源”）：
- `kg_pagerank`
- `kg_shared_events`
- `kg_path_length`
- `kg_edge_conf_low|mid|high`
- `kg_evidence_anchored`

启用方式（必须与模型工件一致）：

```bash
LTR_FEATURE_SPEC_VERSION=2
```

### v3（可选，强化排序关键特征）

v3 在 v2 基础上加入融合后排序更敏感的信号：
- `field_aware_boost`
- `field_signal_title`
- `field_signal_heading`
- `keyword_max_score`
- `vector_keyword_gap`
- `multi_channel_hits`

启用方式（必须与模型工件一致）：

```bash
LTR_FEATURE_SPEC_VERSION=3
```

> 如果你修改了 feature spec，必须同时更新训练与推理侧，并通过回归测试锁住。

---

## 2) 训练模型（从 regression cases 生成训练数据）

脚本：`scripts/train_ltr_from_regression_cases.py`

它会：
1. 读取 regression case bundle（`mimirq.regression_cases.v1`）
2. 通过 Evidence API 拉取 `citations`
3. 用 `reference_sources.chunk_id` 给 citations 打 label（命中=1，否则=0）
4. 训练 xgboost 并输出模型文件（JSON bytes）

示例：

```bash
python scripts/train_ltr_from_regression_cases.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --out-model ./artifacts/ltr.json \
  --top-k 50 \
  --retrieval-mode hybrid \
  --score-threshold 0.0 \
  --num-boost-round 50
```

建议：
- 默认会把 retriever 内置 reranker 关闭（收集 pre-rerank candidates），避免 “用 rerank 训练 rerank” 的污染。
- `--max-negatives-per-case` 用于控制训练集规模与类别不平衡。

---

## 3) 启用 LTR（HybridRetriever 内置 reranker）

当你希望在 retriever 内部进行 LTR 精排：

```bash
ENABLE_RERANKER=true
RERANKER_PROVIDER=ltr
LTR_MODEL_PATH=./artifacts/ltr.json
RERANKER_TOP_N=30
```

说明：
- `LTR_MODEL_PATH` 必填；不设置不会启用（避免默认行为改变）。
- `RERANKER_TOP_N` 建议从 20-50 起步，用回归门禁观察 MRR/NDCG 的提升与 latency 成本。

---

## 4) 启用 LTR（Evidence API 的 post-fusion rerank）

如果你想在 retrieval-only Evidence API 上做后置精排实验：

```bash
EVIDENCE_POST_RERANK_ENABLED=true
EVIDENCE_POST_RERANK_PROVIDER=ltr
EVIDENCE_POST_RERANK_TOP_N=30
LTR_MODEL_PATH=./artifacts/ltr.json
```

输出体现：
- citations：`reranker_provider=ltr`、`rerank_score`、`retrieval_score`（best-effort）
- metrics：`evidence_post_rerank_*`（best-effort）

---

## 5) 有界 rollout workflow（evidence / feedback -> train -> eval -> compare）

脚本：`scripts/prepare_ltr_rollout.py`

这个脚本把原来分散的几步串成一个 **不自动激活** 的受控工作流：
1. 从一个 `EvidenceSuite` 的 `approved` items 和/或一组 `feedback_id` 物化出 `mimirq.regression_cases.v1` bundle
2. 调用 `train_ltr_from_regression_cases.py` 训练 candidate 模型
3. 调用 `eval_ltr_offline.py` 跑 candidate 离线评估
4. 如果当前已有 active LTR model，再对 active model 跑同一份离线评估
5. 生成 candidate-vs-baseline comparison artifact
6. 可选地把 candidate 注册进本地 LTR registry，但 **不会 activation**

示例：

```bash
python scripts/prepare_ltr_rollout.py \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --suite-id 11111111-1111-1111-1111-111111111111 \
  --feedback-id 22222222-2222-2222-2222-222222222222 \
  --feedback-id 33333333-3333-3333-3333-333333333333 \
  --base-url http://localhost:8000/api/v1
```

默认产物会写到 `UPLOAD_DIR/.ltr_rollouts/<timestamp>/`，关键文件包括：
- `cases.bundle.json`: 物化后的 regression case bundle
- `candidate.model.json`: 训练出的 candidate 模型
- `candidate.manifest.json`: candidate 训练 lineage
- `candidate.eval.json`: candidate 的离线评估摘要
- `baseline.eval.json`: 当前 active model 的离线评估摘要（如果存在）
- `comparison.json`: candidate-vs-baseline 对比结果
- `workflow.json`: 整个 workflow 的索引、sha256 和人工激活状态

`comparison.json` 的 baseline 规则：
- 有 active model 时，对比 `candidate.ltr` vs `active_model.ltr`
- 没有 active model 时，对比 `candidate.ltr` vs retrieval baseline

### Gate（train 之后、activate 之前）

Wave B 增加了显式 gate evaluator 与独立 gate CLI，推荐流程从“feedback->train->eval->compare”升级为：

1. feedback/evidence 物化回归 case
2. train candidate
3. eval candidate + baseline
4. compare 产出
5. **gate 判定（通过才允许激活）**
6. 人工 activate

`prepare_ltr_rollout.py` 已内置 gate 结果，支持：

- `--gate-thresholds <path.json>`
- `--gate-min-delta-ndcg-at-k`
- `--gate-min-delta-mrr`
- `--gate-min-cases-used`

并会把 `gate` 写入：

- `comparison.json`
- `workflow.json`

也可以单独运行：

```bash
python scripts/ltr_rollout_gate.py \
  --comparison ./comparison.json \
  --workflow ./workflow.json \
  --out ./gate.json
```

返回码语义：

- `0`：gate pass
- `3`：gate fail（不应激活）
- `2`：输入/参数错误

激活与回滚仍然单独控制：

```bash
# 查看注册过的 candidate
curl http://localhost:8000/api/v1/ltr/models

# 人工激活
curl -X POST http://localhost:8000/api/v1/ltr/models/activate \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"<candidate_model_id>"}'

# 一步回滚
curl -X POST http://localhost:8000/api/v1/ltr/models/rollback
```

如果你只想准备工件、不注册 candidate，可加 `--skip-register`。

---

## 6) 生产化差距（需要额外工程）

训练脚本默认支持 **按 query 分组** 的 ranking objective（例如 `rank:pairwise` / `rank:ndcg`），并提供
hard negative（near-miss）采样能力。

常用开关（训练侧）：

```bash
python scripts/train_ltr_from_regression_cases.py \
  --objective rank:pairwise \
  --hard-negatives-per-case 10 \
  --max-negatives-per-case 30 \
  --feature-spec-version 2
```

离线评估（不依赖后端启用 LTR；本地 rerank Evidence API candidates）：

```bash
python scripts/eval_ltr_offline.py \
  --cases ./regression_cases.json \
  --model ./artifacts/ltr.json \
  --k 20 \
  --top-k 50
```

仍然存在的生产化差距（需要额外工程）：
- 更强的 hard negative mining（跨 run、跨版本、从 trace/feedback 自动挖掘）
- 更细粒度的 rollout guardrail（例如自动 gate / 自动 canary / 人工审批队列）
- A/B 分流与线上指标回写

详见最新差距快照与实施计划：`docs/plans/2026-03-12-top-tier-rag-gap-wave-c-40-task-implementation-plan.md`。
