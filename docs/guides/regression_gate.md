# 离线评测回归（RAGAS / 用例集 / CI Gate）

## 目标

把“已有 RAGAS 回归能力”变成企业级可复现/可回归：

- 用例集可 **导入/导出**（跨环境复用）
- CI 可跑 **regression gate**，指标退化直接失败

## 用例集导入/导出

### UI

- `分析工具 → RAGAS 评测 → 回归测试 → 测试用例库`
  - `导出`：下载 JSON（不包含 id，便于跨环境导入）
  - `导入`：上传 JSON（支持覆盖更新：按 question + dataset_id 匹配）

### API

- 导出：`GET /api/v1/evaluations/ragas/regression/cases/export?dataset_id=...`
- 导入：`POST /api/v1/evaluations/ragas/regression/cases/import`（body 需要 `dataset_id` + `items[]`）

> 导出的 bundle schema 为 `mimirq.regression_cases.v1`，包含 `dataset_id` 与 `items[]`。
>
> `items[]` 支持可选 multi-hop 字段：
> - `reasoning_hops`（推理步骤，有序）
> - `evidence_chain`（证据链，有序 `ReferenceSource`）

## CI Gate 脚本

脚本：`scripts/regression_gate.py`

示例：

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --thresholds ./thresholds.json
```

说明：
- `--cases` 支持两种格式：
  - bundle：`{"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}`
  - legacy：`[{ "dataset_id":"...", ... }, ...]`（每项带 dataset_id；会被自动归并到一个 dataset）

### 常用参数：检索配置覆盖（retrieval-only/CI 友好）

回归 run 支持覆盖一小组常用检索参数（用于 CI 里强制走某个 retrieval_mode / 固定 top_k 等）：

- `--retrieval-mode`：`hybrid|vector|keyword|mmr`
- `--top-k`：覆盖 `top_k`
- `--score-threshold`：覆盖 `score_threshold`

也支持一组更贴近生产的 runtime knobs（用于 hourly/nightly 对齐生产配置）：

- `--retrieval-profile`：覆盖 `retrieval_profile`（例如 `recall20|recall50|coverage80`）
- `--fusion-strategy`：覆盖 `fusion_strategy`（例如 `linear|rrf|budgeted_rrf|weighted`）
- `--enable-sparse-retrieval` / `--disable-sparse-retrieval`：覆盖 `sparse_retrieval_enabled`
- `--sparse-retrieval-provider`：覆盖 `sparse_retrieval_provider`（例如 `deterministic|splade`）
- `--enable-query-rewrite` / `--disable-query-rewrite`：覆盖 `enable_query_rewrite`
- `--enable-multi-query` / `--disable-multi-query`：覆盖 `enable_multi_query`
- `--enable-reranker` / `--disable-reranker`：覆盖 `enable_reranker`
- `--reranker-provider` / `--reranker-top-n`：覆盖 reranker provider/top_n

如果你需要 sweep 更深/更多的 knobs：

- 推荐用 `scripts/retrieval_ablation.py` 的矩阵模式
- 或用 `--run-overrides-json path.json` 直接传一份 JSON 覆盖（键名对齐 `RagasRegressionRunCreateRequest`；CLI flags 优先生效）
- 或者直接调用 `POST /api/v1/evaluations/ragas/regression/runs`

另外，CI 里常需要把 run 的详细 JSON 作为 artifact 保存，可用：

- `--out-run-json path/to/run.detail.json`：写出最终 run detail（包含 `summary` + `retrieval_slices`）
  - 提示：run detail 的检索侧 `metrics` / `retrieval_trace` 里会包含 `retrieval_config_hash`（用于对比不同检索配置的结果差异）。

## Retrieval-only Gate（不依赖 RAGAS/LLM）

当你只想 gate “检索质量”（Recall@K / MRR / NDCG / abstain_rate），且希望 **不依赖 RAGAS/LLM** 时，可将 `--metrics` 置为空字符串：

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --metrics "" \
  --thresholds ./thresholds.json
```

说明：
- `--metrics ""` 会触发后端的 **retrieval-only regression run**（只跑检索，不做生成，不导入/调用 ragas）。
- 当 metrics 为空时：
  - 若你要 **gate**，必须提供 `--thresholds`
  - 若你要 **生成阈值（baseline workflow）**，必须提供 `--generate-thresholds-out`

`thresholds.json` 示例：

```json
{
  "faithfulness": 0.7,
  "response_relevancy": 0.7,
  "retrieval_recall": 0.3,
  "multihop_path_completeness": 0.7,
  "multihop_order_consistency": 0.6,
  "retrieval_hit_at_20": 1.0,
  "abstain_rate": 0.02
}
```

> 说明：回归 run 的默认 top_k/threshold 等参数会跟随 **regression run 的默认值**（可在 run 请求里显式覆盖）。
>
> 另外，`enable_reranker` / `reranker_provider` / `reranker_top_n` 现在默认跟随服务端运行时 settings；这让 CI / staging 可以直接用环境变量切换到真实 rerank 路径，而不必为每个 gate 单独拼 payload。
>
> 新增可选指标（run summary 里可见，也可写进 thresholds 里 gate）：
> - `retrieval_recall`: [0,1]，证据召回率（人工标注 evidence chunk_id 与检索 citations.chunk_id 的重合比例，越高越好）
> - `retrieval_hit_at_1/3/5/10/20`: [0,1]，命中率（top-k 里是否命中证据；汇总为命中占比，越高越好）
> - `retrieval_mrr`: [0,1]，MRR（证据第一次出现的平均倒数排名：`1/rank`，越高越好）
> - `retrieval_ndcg_at_10`: [0,1]，NDCG@10（证据在 Top10 的排序质量，越高越好）
> - `retrieval_ndcg_at_20`: [0,1]，NDCG@20（证据在 Top20 的排序质量，越高越好）
> - `multihop_path_completeness`: [0,1]，multi-hop 证据链覆盖率
> - `multihop_order_consistency`: [0,1]，multi-hop 证据链顺序一致性
> - `multihop_chain_hit_rate`: [0,1]，multi-hop 全链路命中率
> - `abstain_rate`: [0,1]，拒答率（`abstain_triggered` 的占比；可用于“严格可见证据模式”安全回归）
> - `must_recall_pass_rate`: [0,1]，must-recall 合同通过率（含 partial-miss recovery）
> - `parse_quality_alert_rate`: [0,1]，解析质量告警占比
> - `parse_quality_gate_block_rate`: [0,1]，strict parse gate 阻断占比
> - `parse_risk_high_rate`: [0,1]，高 parse-risk 占比
>
> 注意：`thresholds.json` 支持两种写法：
> - 简写：`"faithfulness": 0.7`（等价于 `{"min": 0.7}`）
> - 完整：`"abstain_rate": {"max": 0.02}` / `{"min": 0.3, "max": 0.9}`

另见（更聚焦 Evidence API 的检索门禁说明）：
- `docs/guides/evidence_retrieval_gate.md`

## Answer-level deterministic gate（补充）

当你已经有回归 run summary（或其他 summary artifact），并希望对答案侧关键指标做 deterministic 检查，可使用：

- 脚本：`scripts/answer_quality_gate.py`
- 阈值：`ci/answer_quality_thresholds.v1.json`

示例：

```bash
python scripts/answer_quality_gate.py \
  --input artifacts/answer_quality.summary.json \
  --thresholds ci/answer_quality_thresholds.v1.json \
  --out artifacts/answer_quality.gate.json
```

该 gate 支持 `min/max` 阈值，并可对缺失指标设置 `required=false`，适合在 retrieval-only CI 路径先做轻量答案质量契约检查。

## 阈值文件 v2（支持切片 gate）

当你需要对某些 slice 单独设更严格/更宽松的阈值（例如：`file_type=pdf`、`quality=high`），推荐使用结构化阈值文件：

```json
{
  "schema": "mimirq.thresholds.v2",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "metrics": {
    "retrieval_recall": { "min": 0.3 },
    "abstain_rate": { "max": 0.02 }
  },
  "slices": {
    "file_type": {
      "pdf": { "retrieval_recall": { "min": 0.25 } }
    },
    "quality": {
      "high": { "retrieval_recall": { "min": 0.4 } }
    }
  }
}
```

说明：
- `metrics` 为全局阈值（top-level summary metrics）。
- `slices` 为按维度/桶（bucket）细分的阈值；bucket key 会自动做 lowercase 归一化。
- 若阈值文件中带 `dataset_id`，脚本会校验其与 `--cases` 的 dataset_id 一致，防止串用。

## 从基线 run 生成阈值（baseline generator）

你可以用一次 regression run 的 summary 直接生成 `mimirq.thresholds.v2`（包含 top-level + per-slice），用于后续 CI gate：

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --metrics "" \
  --generate-thresholds-out ./thresholds.v2.json
```

常用可调参数：
- `--gen-metrics`：生成哪些 top-level metrics（默认是检索相关 + abstain_rate）
- `--gen-slice-dims`：生成哪些切片维度（默认：`file_type,language,hit_type,quality`）
- `--gen-slice-metrics`：切片里生成哪些指标
- `--gen-rel-drop / --gen-abs-slack`：阈值松弛（相对/绝对），越大越宽松
- `--gen-min-slice-items`：slice bucket 最少样本数（低于该值会跳过，避免小样本误导）

安全更新（diff preview + guardrail）：
- 若 `--generate-thresholds-out` 目标文件已存在，脚本会先打印 unified diff，然后拒绝覆盖（除非加 `--gen-force`）。

## Evidence Pack → 回归用例（证据闭环）

如果你希望从“检索预览”直接沉淀可回归的 Ground Truth 证据，推荐使用 Evidence Pack 工作流：

- UI：Knowledge 检索预览勾选证据 → 导出 Evidence Pack → 回归用例库导入创建用例
- CLI：Evidence Pack JSON → 回归用例 bundle v1 → regression_gate 导入/运行/gate

详见：`docs/guides/evidence_pack_to_regression.md`

## CI 集成（Retrieval-only Gate）

仓库内置了一个极小的、确定性的 fixture，用于在受信任的 push/发布 CI 中做 retrieval-only gate（不依赖 RAGAS/LLM）：

- Fixture：`ci/retrieval_regression_fixture.v1.json`
- 阈值：`ci/retrieval_thresholds.v2.json`
- GitHub Actions：`.github/workflows/ci.yml` 的 `retrieval-regression-gate` job

本地复现（示例）：

```bash
# 1) 准备 Postgres（示例连接串；按你的环境修改）
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/mimirq"

# 2) Seed fixture（同时导出 regression cases bundle）
mkdir -p artifacts
python scripts/seed_ci_retrieval_regression.py \
  --fixture ci/retrieval_regression_fixture.v1.json \
  --out-cases artifacts/regression_cases.json

# 3) 启动后端（禁用外部依赖；使用 faiss 让 /health/ready 通过）
ENV=ci AUTH_MODE=header DEFAULT_TENANT_ID=00000000-0000-0000-0000-000000000000 \
VECTOR_BACKEND=faiss TASK_QUEUE_ENABLED=false EMBEDDING_CACHE_ENABLED=false MINIO_ENABLED=false \
EMBEDDING_PROVIDER=deterministic_test EMBEDDING_MODEL=mimirq-deterministic-test-v1 \
LEXICAL_DB_TRGM_ENABLED=false LLM_MOCK_ENABLED=true ENABLE_RERANKER=true RERANKER_PROVIDER=pc BM25_INDEX_ENABLED=true \
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4) 运行 gate（写出 run detail + 生成候选阈值）
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id ci-bot \
  --cases artifacts/regression_cases.json \
  --metrics "" \
  --thresholds ci/retrieval_thresholds.v2.json \
  --retrieval-mode hybrid \
  --out-run-json artifacts/run.detail.json \
  --generate-thresholds-out artifacts/thresholds.generated.json

# 5) 一体化门禁：must-recall + provenance capsule 完整性
python scripts/must_recall_provenance_gate.py \
  --run-json artifacts/run.detail.json \
  --must-recall-min 1.0 \
  --provenance-min 1.0 \
  --out artifacts/must_recall_provenance_gate.report.json

# 6) must-recall proof 一致性审计（可选但推荐）
python scripts/must_recall_proof_audit.py \
  --input artifacts/run.detail.json \
  --out artifacts/must_recall_proof_audit.report.json
```

说明：

- `must_recall_provenance_gate.py` 会同时检查：
  - `must_recall_pass_rate`
  - provenance 完整性（evidence capsule 存在且包含 capsule/citation hash）
- `must_recall_proof_audit.py` 会检查 proof 对象一致性：
  - proof schema 是否正确
  - `passed` 与 `missing_source_keys/anchor_missing_any/obligation_ledger.missing_total` 是否一致
  - `failed` 状态是否包含 fail reasons
- 推荐把该 JSON 报告与 regression gate 报告一起上传为 CI artifact，作为发版审计依据。
- bounded hybrid CI 还会生成 `artifacts/multihop_diagnostics.summary.json`，
  用于审计 multi-hop 指标是否进入 artifact 链路。

## CI 集成（KG Search Gate in PR）

仓库内置了一个极小的、确定性的 KG search fixture，用于在 PR 中做 **KG search gate**（不依赖 Milvus / embeddings / LLM）：

- Fixture：`ci/kg_search_regression_fixture.v1.json`
- 阈值：`ci/kg_search_thresholds.v1.json`
- Seed 脚本：`scripts/seed_ci_kg_search_regression.py`
- Gate 脚本：`scripts/kg_search_regression_gate.py`

本地复现（示例）：

```bash
# 1) 准备 Postgres（示例连接串；按你的环境修改）
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/mimirq"

# 2) Seed fixture（DB + KG rows + 导出 regression cases bundle）
mkdir -p artifacts
python scripts/seed_ci_kg_search_regression.py \
  --fixture ci/kg_search_regression_fixture.v1.json \
  --out-cases artifacts/kg_regression_cases.json

# 3) 启动后端（禁用外部依赖；KG 走 alias-driven recall，不需要 Milvus/embeddings）
ENV=ci AUTH_MODE=header DEFAULT_TENANT_ID=00000000-0000-0000-0000-000000000000 \
VECTOR_BACKEND=faiss TASK_QUEUE_ENABLED=false EMBEDDING_CACHE_ENABLED=false MINIO_ENABLED=false \
LEXICAL_DB_TRGM_ENABLED=false ENABLE_RERANKER=false BM25_INDEX_ENABLED=false \
KG_ENABLED=true KG_SEARCH_VECTOR_RECALL_ENABLED=false \
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4) 运行 gate（基于 /evaluations/kg/search/diagnostics 的 baseline_hit_rate/mrr/recall）
python scripts/kg_search_regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id ci-bot \
  --cases artifacts/kg_regression_cases.json \
  --thresholds ci/kg_search_thresholds.v1.json \
  --k 10 \
  --out-run-json artifacts/kg.diagnostics.json
```
