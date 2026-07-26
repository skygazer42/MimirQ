# Evidence Capsule Contract (`mimirq.evidence_capsule.v1`)

## 目标

Evidence capsule 用于把一次 retrieval 结果固化为可回放、可审计、可比较的证据对象，重点解决“有据可查”：

- 回答对应了哪些证据锚点
- must-recall 合同是否满足
- 解析质量风险是否影响本次召回
- 后续回放时如何验证完整性

## 返回位置

`POST /api/v1/rag/retrieve` 响应新增：

- `evidence_capsule`

开关：

- `RAG_EVIDENCE_CAPSULE_ENABLED=true`

## 结构要点

根字段（摘要）：

- `schema`: `mimirq.evidence_capsule.v1`
- `generated_at`
- `query_for_retrieval`
- `retrieval_summary`
- `must_recall`
- `retrieval_contract`
- `quality`
- `citations[]`
- `citation_hashes[]`
- `retrieval_trace`
- `capsule_hash`

哈希约束：

- citation 级：`citation_hash` + `evidence_anchor_hash`
- capsule 级：`capsule_hash`

## 持久化与读取

API：

- `POST /api/v1/evidence/capsules`
- `GET /api/v1/evidence/capsules/{capsule_id}`

配置：

- `EVIDENCE_CAPSULE_PERSIST_ENABLED=true`
- `EVIDENCE_CAPSULE_STORE_DIR=./runs/evidence_capsules`

## 回放

```bash
python scripts/replay_from_evidence_capsule.py \
  --capsule runs/evidence_capsules/<capsule_id>.json \
  --out runs/evidence_replay.json
```

回放输出会校验 `capsule_hash`，并生成最小 replay request（query + rag_config + expected citation hashes）。

## 与 CI 门禁联动

一体化门禁脚本会检查：

- `must_recall_pass_rate`
- provenance 完整性（capsule/citation hash 完整）

```bash
python scripts/must_recall_provenance_gate.py \
  --run-json artifacts/run.detail.json \
  --must-recall-min 1.0 \
  --provenance-min 1.0 \
  --out artifacts/must_recall_provenance_gate.report.json
```
