# Public Benchmarks（中文 / Milvus / Ollama）

开源项目很难提供一个“统一的企业知识库数据集”（文档类型/行业/权限/更新频率差异太大）。

更主流、也更可复现的做法是：
- **统一评测格式**（`mimirq.regression_cases.v1`）
- 提供 1～2 个 **可公开下载** 的 benchmark（用户自行下载，不把大语料塞进 repo）
- 让 benchmark 跑通你们的真实检索栈：**Postgres + Milvus + Embeddings + Hybrid fusion**，并支持 nightly 回归与 ablations

本指南给出一套中文主导的默认公开基准：**MIRACL-zh pool v1（主）**，并以 **Ollama/bge-m3** 作为最容易复现的 embedding 方案。

---

## 1) 主基准选择（默认）

### 主跑：MIRACL-zh pool v1（覆盖 A/C）

目标：
- **A 检索质量**：Recall/Hit@K/MRR/NDCG（基于 `reference_sources.chunk_id`）
- **C 成本/延迟**：同一组 queries + 同一套语料池，nightly 对比最稳定

为什么是 “pool-corpus”：
- MIRACL 全量中文语料是百万级 passage；把全量语料当 nightly 基准会让“每天回归”变成“每天建库”
- pool 的策略是：**保留每个 query 的正例 passage（qrels）** + **确定性采样一批负例**，把语料规模冻结到一个“小时级能回归”的范围

### 副跑：CFEVER dev evidence v1（覆盖 B）

目标：
- **B 引用可信/可核验**：每条 claim 都带有 gold evidence 指针（`page_title + sentence_id`）
- 在 MimirQ 中我们把 wiki 页面切成 “sentence-per-chunk”，再把 evidence 指针对齐到 `reference_sources.chunk_id`

实现方式（开源友好）：
- 不导入全量 wiki（太大）
- 只 seed **dev evidence 涉及到的 wiki pages 子集**（474 pages 量级），一次性建库即可

---

## 2) 前置条件（Milvus + Ollama）

### 2.1 启动 infra（Postgres + Milvus）

仓库内置了 infra compose（包含 Postgres / Redis / Milvus / etcd / MinIO）：

```bash
docker compose -f docker/docker-compose.infra.yml up -d
```

### 2.2 启动 Ollama + 拉取 embedding 模型

本指南默认 embedding 使用 `bge-m3`：

```bash
ollama pull bge-m3
```

Ollama 默认 embedding endpoint 是 `http://localhost:11434/api/embed`。

---

## 3) 环境变量（推荐最小集）

下面配置让你可以跑 **retrieval-only nightly**（不依赖 LLM）：

```bash
export AUTH_MODE=header
export DEFAULT_TENANT_ID=00000000-0000-0000-0000-000000000000

export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mimirq

export VECTOR_BACKEND=milvus
export MILVUS_HOST=localhost
export MILVUS_PORT=19530

# Embeddings: Ollama / bge-m3
export EMBEDDING_PROVIDER=ollama
export EMBEDDING_MODEL=bge-m3
# 可选：不填也行（OllamaEmbedding 有默认值）
export EMBEDDING_API_BASE=http://localhost:11434/api/embed

# 保证 nightly 不会因为 rerank 触发 LLM 调用而失败
export RERANKER_PROVIDER=none
```

---

## 4) 一次性建库：seed MIRACL-zh pool + 导出回归用例

脚本：`scripts/seed_public_bench_miracl_zh_pool.py`

> 为了让评测可复现，建议显式 pin HuggingFace revision（tag/commit hash），并把脚本输出的 manifest 作为产物保存。
> 否则上游 dataset 更新后，下载到的语料可能发生漂移，导致 nightly 对比失真。

### 4.1 Dry-run（推荐先跑一次）

```bash
python scripts/seed_public_bench_miracl_zh_pool.py \
  --dry-run \
  --hf-revision <miracl_revision> \
  --hf-revision-corpus <miracl_corpus_revision> \
  --out-cases runs/public_bench/miracl_zh_pool_v1/regression_cases.json \
  --out-manifest runs/public_bench/miracl_zh_pool_v1/seed_manifest.json
```

输出会包含（JSON）：
- `dataset_id`：后续 nightly/回归要用
- `cases`：用例数量（建议保持 <= 2000，方便 `regression_gate.py` 一次导入）
- `plan`：pool 构建计划（dry-run 不会下载/统计全量语料）

### 4.2 Execute（会下载语料并写入 DB + Milvus）

这一步通常是一次性构建，可能耗时较长（取决于 `target_passages`、机器性能、Ollama 吞吐）：

```bash
python scripts/seed_public_bench_miracl_zh_pool.py \
  --execute \
  --overwrite \
  --target-passages 200000 \
  --chunks-per-document 1000 \
  --hf-revision <miracl_revision> \
  --hf-revision-corpus <miracl_corpus_revision> \
  --out-cases runs/public_bench/miracl_zh_pool_v1/regression_cases.json \
  --out-manifest runs/public_bench/miracl_zh_pool_v1/seed_manifest.json
```

说明：
- `--overwrite` 会 best-effort 删除该 dataset 的历史 documents + vectors（适合本地重建）
- `--target-passages` 建议先从 50k～200k 起步，确认跑通后再放大
- seeding 使用 `Indexer`，会写入：Postgres（chunks）+ Milvus（vectors）+ BM25（内存）

---

## 4.5) 一次性建库：seed CFEVER dev evidence（sentence-level wiki 子集）

脚本：`scripts/seed_public_bench_cfever_dev.py`

### 4.5.1 Dry-run（推荐先跑一次）

```bash
python scripts/seed_public_bench_cfever_dev.py \
  --dry-run \
  --hf-revision <cfever_revision> \
  --out-cases runs/public_bench/cfever_dev_v1/regression_cases.json \
  --out-manifest runs/public_bench/cfever_dev_v1/seed_manifest.json
```

### 4.5.2 Execute（会下载 wiki 子集并写入 DB + Milvus）

```bash
python scripts/seed_public_bench_cfever_dev.py \
  --execute \
  --overwrite \
  --hf-revision <cfever_revision> \
  --out-cases runs/public_bench/cfever_dev_v1/regression_cases.json \
  --out-manifest runs/public_bench/cfever_dev_v1/seed_manifest.json
```

可选参数：
- `--max-pages N`：只 seed 前 N 个 required pages（先小规模跑通时很有用）
- `--include-nei`：把 `NOT ENOUGH INFO` 也导出到 case bundle（默认只包含有证据的 supports/refutes）

---

## 5) 启动后端 API

```bash
python main.py
```

---

## 6) 跑 retrieval-only regression gate（导入用例 + 生成阈值）

脚本：`scripts/regression_gate.py`

**推荐第一次先生成 thresholds（v2）**，后续 nightly 才做“门禁”：

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases runs/public_bench/miracl_zh_pool_v1/regression_cases.json \
  --metrics "" \
  --generate-thresholds-out runs/public_bench/miracl_zh_pool_v1/thresholds.v2.json
```

后续 gate（强制阈值）：

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases runs/public_bench/miracl_zh_pool_v1/regression_cases.json \
  --metrics "" \
  --thresholds runs/public_bench/miracl_zh_pool_v1/thresholds.v2.json
```

---

## 7) Nightly：跑一组检索消融（ablations）

脚本：`scripts/run_nightly_ablations.py`

```bash
python scripts/run_nightly_ablations.py \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --dataset-id <dataset_uuid_from_seed_output> \
  --cases runs/public_bench/miracl_zh_pool_v1/regression_cases.json \
  --execute
```

提示：
- 默认 ablations 是有界的（适合每天跑）
- 默认 `hybrid_rerank` 使用非 LLM 的 `pc` reranker 变体（可覆盖 rerank 代码路径的基本行为且不依赖 LLM key）
- 如果你希望 nightly 结果更可复现，建议传 `--cases <mimirq.regression_cases.v1 bundle>` 锁定 suite。  
  注意：`--cases` 不会自动导入用例；请先用 `scripts/regression_gate.py` 或 UI 导入一次。

---

## 8) 常见坑（中文 + Milvus + embeddings）

1. **换 embedding 模型就要重建向量**  
   MimirQ 会在检索侧做 `embedding_space_hash` guard，避免不同 embedding space 混用导致 silent 退化。

2. **只跑检索回归时不需要 LLM**  
   保持 `--metrics ""`（retrieval-only gate），并设置 `RERANKER_PROVIDER=none`，就能把 nightly 做成纯检索回归。

3. **语料下载很大**  
   seeding 过程会下载 MIRACL-zh corpus（来自 HuggingFace）；建议确保磁盘空间与网络条件充足。
