# Wave3 Design: LTR 模型治理 + 多阶段重排序 Pipeline（Evidence post-rerank）

日期：2026-02-26

## 背景 / 目标

本 Wave 聚焦“learning & reranking system”，将现有 LTR（XGBoost LTR scaffold）从可用原型升级到更接近生产的形态，并补齐 ColBERT stack 的关键一环：**多阶段、可预算（budgeted）**的后融合（post-fusion）重排序能力。

目标：

1. **LTR artifact/version 治理（可审计、可回放）**
   - LTR 模型支持 sidecar `manifest`，包含特征 schema、特征顺序、模型 hash 等。
   - 线上加载时校验，避免“模型文件/特征版本不匹配”导致 silent quality regression。
2. **线上推理护栏（online inference safeguards）**
   - LTR 预测失败时 fail-closed：重排序变为 no-op，不影响主检索链路可用性。
3. **多阶段重排序 Pipeline（可预算 top_n）**
   - 在 Evidence post-rerank（query expansion fusion 之后）增加多阶段 pipeline：
     - stage1 可以是更宽的候选（top_n 更大）的轻量 rerank
     - stage2/3 只在更小前缀上做更昂贵/更精细的 rerank
4. **离线指标 gating**
   - 在启用线上 flag 前，用离线脚本对 regression cases 做对比评估，确保有收益再上线。

非目标（本 Wave 不做）：

- 真正的 token-level ColBERT index（本项目当前是“ColBERT-style ANN scaffold”用于 candidate generation + late-interaction 实验）
- 默认行为变更：所有新能力均为显式 opt-in

## 设计要点

### 1) LTR 模型 sidecar manifest

**文件命名（默认自动发现）：**

- `LTR_MODEL_PATH=/path/to/model.json`
- sidecar：`/path/to/model.manifest.json`（自动读取）
- 或显式设置：`LTR_MODEL_MANIFEST_PATH=/path/to/custom.manifest.json`

**manifest schema（v1）：**

`schema = "mimirq.ltr_model_manifest.v1"`

关键字段（最小集）：

- `model_sha256`: 模型字节 sha256，用于 pin 住 artifact
- `feature_schema`: `LTRFeatureSpec.schema`
- `feature_names`: 有序特征名列表（必须与线上 spec 完全一致）

线上加载校验：

- schema 必须匹配
- feature_schema / feature_names 必须匹配
- 如果 manifest 提供 `model_sha256`，则校验模型文件内容未漂移

### 2) 多阶段 Evidence post-rerank pipeline

**配置项：**

- `EVIDENCE_POST_RERANK_ENABLED=true|false`
- `EVIDENCE_POST_RERANK_PROVIDER=ltr|colbert|...`（legacy 单阶段）
- `EVIDENCE_POST_RERANK_PIPELINE_ENABLED=true|false`
- `EVIDENCE_POST_RERANK_PIPELINE='[{"provider":"ltr","top_n":50},{"provider":"colbert","top_n":20}]'`

**执行规则（budgeting）：**

- pipeline 为 stage 列表，按顺序执行
- `top_n` 控制每个 stage 仅对前缀候选 rerank（后续 stage 不能扩大候选范围）
- 最终 stage 负责写入：
  - `rerank_score` / `score`（用于最终排序）
  - `reranker_provider`
  - `rerank_elapsed_sec`（累计耗时）
  - `rerank_model_used`（尽量避免泄露本地路径；LTR 使用 sha256 前缀或 basename）

### 3) 观测与可比对

- `retrieval_config_hash` 增加 pipeline 的低基数摘要（providers + top_n），便于 leaderboard/回归分组。
- `retrieval_trace.post_rerank` 增加 pipeline 元信息（enabled/used/stages）。

## 离线评估 / 上线流程（建议）

1. 训练 LTR（从 regression cases + Evidence API candidates）：
   - `python scripts/train_ltr_from_regression_cases.py --cases <cases.json> --out-model data/ltr/model.json`
   - 默认会写 `data/ltr/model.manifest.json`
2. 离线对比评估多阶段 pipeline：
   - `python scripts/eval_rerank_pipeline_offline.py --cases <cases.json> --pipeline '[{"provider":"ltr","top_n":50},{"provider":"colbert","top_n":20}]' --ltr-model data/ltr/model.json`
3. 达到阈值/收益后，在环境中显式开启：
   - `EVIDENCE_POST_RERANK_ENABLED=true`
   - `EVIDENCE_POST_RERANK_PIPELINE_ENABLED=true`
   - `EVIDENCE_POST_RERANK_PIPELINE=...`

