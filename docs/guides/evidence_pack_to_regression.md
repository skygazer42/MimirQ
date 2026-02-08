# Evidence Pack → 回归用例（企业级证据闭环）

本指南描述一个面向企业知识库的“证据闭环”工作流：

1) 先在 **Knowledge → 检索测试（Retrieval Preview）** 中找到“应该被召回”的证据切片  
2) 把检索结果导出为 **Evidence Pack**（JSON，可审计/可分享）  
3) 从 Evidence Pack 生成 **回归用例（Regression Case）**，再跑 **retrieval-only / RAGAS** 回归  
4) 通过 **引用定位（span-level）** 与 **claim→evidence** 映射，确保每一步都有依据、可追溯

> 说明：本闭环设计的核心是 RAG 系统本身（检索/证据/回归/可视化），不依赖 LLM 才能跑通。

---

## 1. 导出 Evidence Pack（Knowledge → Retrieval Preview）

路径：`知识库管理 → 检索测试`

1) 选择数据集（dataset）  
2) 输入 query，运行检索预览  
3) 在检索结果列表中勾选你认为“Ground Truth”的引用（证据切片）  
4) 点击 `导出 Evidence Pack`（下载 JSON）

Evidence Pack（典型字段）：

- `dataset_id`：数据集 id（用于后续回归用例归属）
- `query / query_for_retrieval`：问题与实际用于检索的 query（可能包含 rewrite）
- `citations[]`：检索预览的引用列表（chunk_id / document_id / score / snippet 等）
- `selected_chunk_ids[]`：你勾选的 Ground Truth chunk_id
- `reference_sources[]`：由勾选项生成的证据指针（用于回归用例）

---

## 2A. 方式 A：直接在 UI 中导入 Evidence Pack 创建回归用例

路径：`分析工具 → RAGAS 评测 → 回归测试 → 测试用例库`

1) 选择数据集  
2) 点击 `导入 Evidence Pack`，上传 JSON  
3) 勾选 Ground Truth（会生成 `reference_sources`）  
4) 点击创建回归用例

优点：纯 UI 流程，适合运营/标注同学。

---

## 2B. 方式 B：CLI 转换 Evidence Pack → 回归用例 Bundle（适合 CI / 批处理）

### 2B.1 将 Evidence Pack 转换为回归用例 Bundle v1

脚本：`scripts/evidence_pack_to_regression_bundle.py`

```bash
python scripts/evidence_pack_to_regression_bundle.py \
  --in ./evidence-pack.json \
  --out ./regression_cases.json \
  --pretty
```

输出格式为 `mimirq.regression_cases.v1`：

- `dataset_id`
- `items[]`（每项包含 `question` / `reference_sources` / `tags` 等）

### 2B.2 使用 regression_gate 导入 + 运行 + gate

脚本：`scripts/regression_gate.py`

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --metrics "" \
  --thresholds ./thresholds.json
```

> `--metrics ""` 表示 retrieval-only gate（不依赖 RAGAS/LLM），只 gate 检索质量与 abstain_rate。

更多细节见：`docs/guides/regression_gate.md`

---

## 3. 为什么要存 reference_sources（以及如何抗“重切块”）

企业级知识库的回归用例必须具备“证据指针”，而不是只存一个 expected answer。

本项目的 `reference_sources` 会尽量携带：

- `document_id + chunk_id`：最强指针（理想情况下稳定）
- `doc_pipeline_key / pipeline_hash / chunk_index`：用于审计与“切块变动”后的回溯匹配
- `quote`：当 chunk_id 失效时，作为内容回退匹配的最后手段（best-effort）

目标是：即使文档重新解析/重新切块，回归仍能尽量匹配到正确证据，并对“不匹配”的情况给出可解释原因。

---

## 4. 可视化与定位：span-level 引用 + claim→evidence

为了让“每一句话都有依据”变得可操作：

- `citations` 支持 best-effort 的 `evidence_start_char / evidence_end_char`（点击引用可定位高亮）
- 严格可见证据模式下，会生成 `claim_evidence`（每条 claim → 支撑证据 span 列表）

你可以在 Chat 中打开 **诊断面板（右下角图标）** 查看 `claim_evidence` 并一键跳转到文档定位。

