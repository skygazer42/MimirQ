# KB Gap Analysis（对标：Dify / MaxKB / RAGFlow）— 2026-01-30 更新

> 日期：2026-01-30  
> 目标：把「可视化、文档解析、文档入库、文档治理、知识库管理」链路做成 *可解释、可回溯、可运营*。  
> 关联计划：`docs/plans/2026-01-30-kb-functional-optimization-30tasks-plan.md`

## 对标对象与口径

- 对标对象：Dify / MaxKB / RAGFlow
- 口径：只关注知识库（KB/RAG）链路上“用户能看到、能解释、能复现、能运营”的能力，不追求功能堆叠

## MimirQ 当前能力（2026-01-30 分支快照）

- 文档：上传/批量上传、URL 上传、列表/详情、状态/重试/取消、版本（pipeline_hash）、chunk 列表/CRUD、chunk preview（含 stats/review_signals）
- 解析：parsing preview（多 parser_backend）、subprocess worker、解析缓存（preview_parse_cache）
- 治理：governance profiles + clean preview（含 rule stats）
- 数据集：profile summary、precheck、ingestion 监控页
- 可追溯：已有 audit_logs 表与 `audit_log_event`（但缺少面向文档的 timeline 聚合视图）
- 本分支已新增/增强（节选）：
  - 解析对比：ParsingPage 增加 run 对比弹窗（便于 A/B 解析差异定位）
  - 图片理解：解析工作台增加“caption enrich”开关（默认保守）
  - Chunking：semantic sentence chunker 更稳地保留代码块与列表块结构
  - Connectors：新增 connector configuration（create/update/list）端点与模型（为后续 run 监控/调度做地基）

## Gap 列表（P0/P1/P2）→ 映射到 30 Tasks

| Gap | 对标来源 | MimirQ 当前模块 | 需要新增/修改 | 对应 Task | 优先级 |
|---|---|---|---|---|---|
| 文档处理时间线（解析/治理/切块/入库/重试/取消/权限变更） | Dify / RAGFlow | audit_logs + documents API | 新增 `GET /documents/{id}/timeline` + UI Timeline | Task 8 | P0 |
| Dataset Health Dashboard（一页汇总 profile/precheck/ingestion + 建议） | RAGFlow | datasets profile/precheck/ingestion | 新增 `GET /datasets/{id}/health` + `/datasets/[id]/health` | Task 6 | P0 |
| Chunk Preview：PDF 视图定位（选中 chunk → PDF 高亮/跳页） | RAGFlow | chunk preview + pdf viewer | 透传 position tags/blocks；新增 PDF workbench panel | Task 2 | P0 |
| Chunk 质量仪表盘 + 导出 review-report（coverage/gap/重复/短块/浪费） | RAGFlow / MaxKB | chunk preview stats/review_signals | 增强 stats + 导出 JSON/MD（带 filters） | Task 3 / Task 30 | P0 |
| 解析质量门禁（统一评分 + reasons + 自动 fallback） | RAGFlow | parsing preview | quality_gate 结构；规则化评分；自动切换 parser_backend | Task 9 | P0 |
| 解析产物统计/元数据入库并可检索（parser_backend、质量分、结构信息） | RAGFlow | Document metadata / indexer | indexer 写入规范；UI 支持筛选/展示 | Task 10 / Task 15 | P1 |
| 解析 A/B 对比工作台（diff + 一键选用） | RAGFlow | parsing page | parse-compare API 或复用 preview；UI diff + apply | Task 5 | P1 |
| 解析缓存工程化（file_sha256 + parser_backend + version 作为 key） | RAGFlow | preview_parse_cache | 统一 cache key；复用到 pipeline/document processing | Task 14 | P1 |
| 表格管道闭环（table_id、table store、引用） | RAGFlow | dataset_tables + table_store | 解析表格实体化；引用回链接 | Task 11 | P1 |
| OCR/图片理解增强（可选启用、默认保守） | RAGFlow | parsing enrich | options 开关；caption/ocr 产物持久化 | Task 12 | P2 |
| 入库策略 Policy Builder（版本化 + 回滚） | RAGFlow | ingestion policy | policy 版本表/元数据；回滚；UI builder | Task 17 / Task 24 | P0 |
| Ingestion Preview 可解释化（命中规则/最终生效配置/导出快照） | RAGFlow | ingestion-preview + UI | 返回 explain payload；UI 展示 reasons；导出 | Task 17 / Task 30 | P0 |
| Connector Run 运维增强（错误聚类 + 续跑 + 只重试失败） | RAGFlow | connectors/runs | error group；resume；retry failed-only | Task 7 / Task 20 | P1 |
| URL 入库 2.0（sitemap/robots/canonical/readability/xpath） | RAGFlow | web_crawler/url_ingest | 规范化去重；可配置抽取策略 | Task 19 / Task 28 | P1 |
| 治理 Diff 解释器 v2（规则归因 + 影响面统计 + 样例片段） | Dify / RAGFlow | governance cleaner UI | richer diff explain；impact stats；samples | Task 4 | P0 |
| 页眉/页脚/样板学习模式（跨文档发现候选 → 一键写入 profile） | MaxKB / RAGFlow | governance rules | learn endpoint；候选管理；apply to profile | Task 27 | P1 |
| PII/Secrets 合规包（阈值 gate + 动作 + 审计） | 企业需求 | pii/secrets preprocess | policy pack；quarantine/skip；audit | Task 26 / Task 25 | P0 |
| 批量上传 UX 2.0（目录结构保留、元数据映射、并发与失败重试） | RAGFlow | upload + ingestion | uploader 队列化；失败重试；映射 UI | Task 18 | P1 |
| 入库去重闭环（同文件/近重复/跨版本重复） | 企业需求 | precheck + ingestion | 可配置去重策略 + UI explain | Task 22 / Task 28 | P2 |
| 文档生命周期治理（retention/legal hold） | 企业需求 | dataset/doc status | retention policy + scheduled jobs + UI | Task 29 | P1 |
| 报告中心（质量报告/合规报告/版本快照） | 企业需求 | export/download | 统一导出中心 + 报告模板 | Task 30 | P1 |

## 备注

- 优先级含义：
  - P0：形成“可运营闭环”的必要能力（能解释、能回溯、能批量治理）
  - P1：显著提升可用性/运维效率
  - P2：增强项（在 P0/P1 稳定后再做）
- “外部经验规则”（chunking / parsing / retrieval）统一维护在 30-task 计划里的 External Rules 小节，避免散落多处。

