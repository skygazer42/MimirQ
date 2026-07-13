# RAG 入库域可靠性计划（2026-Q3）——分阶段重试 + 增量重嵌 + 死信运营闭环

> 日期：2026-07-13 ｜ 前置调研：`plans/rag-ingestion-frontend-deep-dive-2026-q2.md`（前端 stage-retry P0 的后端前置）
> 定位：入库骨架企业级（arq 队列 + 阶段类编排 + IngestDeadLetter + SHA-256/SimHash 双去重 + 影子 collection 蓝绿），但三个"全量思维"的残留让它在生产规模下费钱费时：**失败全量重跑、文档更新全量重嵌、死信有模型无运营**。本计划把入库从"能跑通"升级为"跑得省、坏得起"。

## Context（2026-07-13 核实）

- **分阶段重试缺**：`app/parsing/processors/processor.py`(6676 行) 仅 `:4715 _clear_failure_retry_fields`，reprocess 走全量；stage_durations_ms 已按阶段记录（processor.py + `app/services/ingestion_run_service.py`）——**阶段边界已存在，只是重试没用上**
- **增量更新缺**：`ingestion_run_service.py` grep `incremental|changed_chunk|delta|resume` = 0——文档小改一处，全文重解析+重切+重嵌+KG 重抽
- **死信半闭环**：`app/models/ingest_dead_letter.py` 模型齐（tenant/document/status 索引），但重放/归因运营路径薄
- 资产：SHA-256 文件级 + SimHash64 chunk 级双去重已有（增量的判定原料现成）；arq max_tries 分类配置（worker.py:115-130）；IngestionRun 阶段状态机
- 巨文件警告:processor.py 6676 行——本计划所有改动**只加不改核心路径**，拆分另立（见工程债索引）

## 落地设计

### P0-1 分阶段重试（stage-retry）
- IngestionRun 已有阶段状态 → 补每阶段**产物快照引用**（parse 产物/chunk 集/嵌入批次 ID），失败重试从最后成功阶段续跑：`retry(run_id, from_stage=...)`。
- API：`POST /documents/{id}/reprocess` 增加 `from_stage` 参数（parse/chunk/embed/index/kg/enrich），默认自动定位失败阶段；前端 stage 时间线的 retry 按钮（既定 P0）直接可接。
- 死信联动：IngestDeadLetter 记录 failed_stage（分阶段失败归因已有），重放默认走 stage-retry 而非全量。
- 验收：embed 阶段故障注入 → 重试不重新解析；单文档重试成本降为故障阶段之后的部分。

### P0-2 增量重嵌（delta re-embed，成本大项）
- 文档更新时：新旧版本 chunk 级 SimHash 对齐 → 三分类 `unchanged / modified / added-removed`——**去重指纹资产直接复用**。
- unchanged chunk 保留向量与 chunk_id（引用/反馈/KG 挂接不失效）；modified/added 才重嵌；removed 走软删。KG 侧只对变更 chunk 重抽三元组（与 KG 域 plan 的增量装载衔接）。
- 版本语义：文档版本号 +1，chunk 保留 `first_seen_version/last_modified_version`——为治理域 RTBF 级联与快照 diff 提供地基。
- 预期收益：政务文档"改一条附则"场景，重嵌成本从 100% 降到 <10%；嵌入是入库最贵阶段，这是入库域 ROI 最高的一项。

### P1-1 死信运营闭环
- 死信看板 API：按 failed_stage × 错误类聚合 + 批量重放（带 stage-retry）+ 重放结果回写；毒丸防护：同文档重放 ≥3 次仍死 → 自动转隔离区（来源=`ingest_dead`，接治理域五类归因）。
- 每日死信摘要进现有审计/报告链路。

### P1-2 阶段速度异常告警（既定缺口，顺手接线）
- stage_durations_ms 已记录未消费：按 tenant×stage 建 p95 基线，超 3σ 报警（`OBS_ANOMALY_*` 骨架在 `config.py:1549`，仅 dashboard 消费过）——扫描件 OCR 卡死、embedding 服务降速这类"慢性故障"当前不可见。

### P2 进阶
- 入库背压：embedding 服务过载时按 tenant 优先级排队降速（arq 队列分级已有雏形）。
- 蓝绿嵌入迁移（indexer.py:116 影子 collection）与增量重嵌统一为"重嵌编排器"：换 embedding 模型 = 全量 delta，同一套机制。**与召回计划 P0-2① embedding 切换直接衔接——先有此项，切模型才敢在生产做。**

## 优先级矩阵

| 优先级 | 任务 | 工作量 | 落点 |
|---|---|---|---|
| P0 | 分阶段重试 + API + 死信联动 | ~5 人日 | processor 阶段编排 + ingestion_run_service + API |
| P0 | 增量重嵌（SimHash 对齐三分类） | ~6 人日 | ingestion_run_service + indexer + chunk 版本字段 |
| P1 | 死信运营闭环 + 毒丸转隔离 | ~3 人日 | dead_letter service + API |
| P1 | 阶段速度告警 | ~2 人日 | metrics 消费 + OBS_ANOMALY 接线 |
| P2 | 重嵌编排器统一 | ~4 人日 | indexer + 蓝绿机制 |

## 验证与门槛
- stage-retry：各阶段故障注入用例进 CI；重试幂等（同 run 重放两次结果一致）。
- 增量重嵌：改 5% 内容的文档，重嵌 chunk 占比 <15% 且检索质量无回退（holdout 集验证，judge 版本按验证域标注）。

## 不做什么
- 不上工作流引擎（Temporal 等）替换 arq——阶段类编排已够，引擎是架构级动荡；不做实时流式入库（`rag-streaming-2026-q4.md` 既定：分钟级 cron 满足 80% 客户）；processor.py 拆分不在本计划内(避免与功能改动互相踩)。
