# KB Gap Analysis（对标：Dify / MaxKB / RAGFlow）

> 日期：2026-01-29  
> 目标：把「可视化、文档解析、文档入库、文档治理、知识库管理」链路做成 *可解释、可回溯、可运营*。

## 对标对象

- Dify
- MaxKB
- RAGFlow

## MimirQ 当前能力（快照）

- 文档：上传/批量上传、URL 上传、列表/详情、状态/重试/取消、版本（pipeline_hash）、chunk 列表/CRUD、chunk preview（含 stats/review_signals）
- 解析：parsing preview（多 parser_backend）、subprocess worker、解析缓存（preview_parse_cache）
- 治理：governance profiles + clean preview（含 rule stats）
- 数据集：profile summary、precheck、ingestion 监控页
- 可追溯：已有 audit_logs 表与 `audit_log_event`（但缺少面向文档的 timeline 聚合视图）

## Gap 列表（P0/P1/P2）

| Gap | 对标来源 | MimirQ 当前模块 | 需要新增/修改 | 优先级 |
|---|---|---|---|---|
| 文档处理时间线（解析/治理/切块/入库/重试/取消/权限变更） | Dify / RAGFlow | audit_logs + documents API | 新增 `GET /documents/{id}/timeline` + UI Timeline | P0 |
| Dataset Health Dashboard（一页汇总 profile/precheck/ingestion + 建议） | RAGFlow | datasets profile/precheck/ingestion | 新增 `GET /datasets/{id}/health` + `/datasets/[id]/health` | P0 |
| Chunk Preview：PDF 视图定位（选中 chunk → PDF 高亮/跳页） | RAGFlow | chunk preview + pdf viewer | 透传 position tags/blocks；新增 PDF workbench panel | P0 |
| Chunk 质量仪表盘 + 导出 review-report（coverage/gap/重复/短块/浪费） | RAGFlow / MaxKB | chunk preview stats/review_signals | 增强 stats + 导出 JSON/MD（带 filters） | P0 |
| 文档生命周期：Enable/Disable/Archive（含批量） | Dify / MaxKB | documents list/detail | Document 增加 archived/disabled 标记；批量 API + UI 过滤/批量操作 | P0 |
| Chunk 运营：编辑/禁用/合并拆分/重嵌入（局部重建索引） | Dify / MaxKB | document_chunks CRUD | chunk CRUD 扩展 + re-embed selected + UI 操作面板 | P0 |
| 解析质量门禁（统一评分 + reasons + 自动 fallback） | RAGFlow | parsing preview | quality_gate 结构；规则化评分；自动切换 parser_backend | P0 |
| 解析 A/B 对比工作台（diff + 一键选用） | RAGFlow | parsing page | parse-compare API 或复用 preview；UI diff + apply | P1 |
| 解析缓存工程化（file_sha256 + parser_backend + version 作为 key） | RAGFlow | preview_parse_cache | 统一 cache key；复用到 pipeline/document processing | P1 |
| 解析产物元数据入库并可检索（parser_backend、质量分、结构信息） | RAGFlow | Document metadata / indexer | indexer 写入规范；UI 支持筛选/展示 | P1 |
| 表格管道闭环（table_id、table store、引用） | RAGFlow | dataset_tables + table_store | 解析表格实体化；引用回链接 | P1 |
| OCR/图片理解增强（可选启用、默认保守） | RAGFlow | parsing enrich | options 开关；caption/ocr 产物持久化 | P2 |
| 入库策略 Policy Builder（版本化 + 回滚） | RAGFlow | ingestion policy | policy 版本表/元数据；回滚；UI builder | P0 |
| Ingestion Preview 可解释化（命中规则/最终生效配置/导出快照） | RAGFlow | ingestion-preview + UI | 返回 explain payload；UI 展示 reasons；导出 | P0 |
| Connector Run 运维增强（错误聚类 + 续跑 + 只重试失败） | RAGFlow | connectors/runs | error group；resume；retry failed-only | P1 |
| URL 入库 2.0（sitemap/robots/canonical/readability/xpath） | RAGFlow | web_crawler/url_ingest | 规范化去重；可配置抽取策略 | P1 |
| 治理 Diff 解释器 v2（规则归因 + 影响面统计 + 样例片段） | Dify / RAGFlow | governance cleaner UI | richer diff explain；impact stats；samples | P0 |
| Common Lines 学习模式（跨文档发现候选 → 一键写入 profile） | MaxKB / RAGFlow | governance rules | learn endpoint；候选管理；apply to profile | P1 |
| PII/Secrets 合规包（阈值 gate + 动作 + 审计） | 企业需求 | pii/secrets preprocess | policy pack；quarantine/skip；audit | P0 |
| 知识库（Dataset）管理：更清晰的配置入口（解析/治理/入库策略聚合） | RAGFlow | datasets pages | datasets/[id] 下聚合配置导航与状态卡 | P1 |
| 知识库管理：批量导入进度与失败可追溯（按文件/按 run） | RAGFlow | ingestion monitoring | 按 run 聚合；失败原因聚类；跳转到 timeline | P1 |
| 知识库管理：去重策略（hash/canonical/url 级别） | RAGFlow | duplicates endpoint | 可配置去重策略 + UI 提示/合并 | P2 |
| 知识库管理：权限模型可视化（dataset/document acl 解释） | Dify | dataset/doc permissions | “为什么我看不到”解释器；UI 可视化权限树 | P2 |
| 知识库管理：数据治理运营台（规则命中趋势、隔离率趋势） | 企业需求 | governance + profile | metrics time-series；导出报告 | P2 |

## 备注

- 优先级含义：
  - P0：形成“可运营闭环”的必要能力（能解释、能回溯、能批量治理）
  - P1：显著提升可用性/运维效率
  - P2：增强项（在 P0/P1 稳定后再做）

