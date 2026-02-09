# Ingestion & RAG 可视化增强 + PaddleOCR-VL v1.5 集成（设计稿）

**日期**：2026-02-01  
**分支**：`feat/ingestion-optimizations`  
**范围**：切块 / 文档解析（PaddleOCR-VL-1.5）/ 入库分析可视化 / RAG 可解释性 / 文档治理规则与自定义 / 设置页模型图标

## 1) 目标（Goals）

1. **切块体验与质量可控**：在“入库前”就能通过可视化与指标快速验证 chunk 结构、覆盖率、重叠浪费、断裂风险，并提供可复现的配置导出/对比。
2. **文档解析增强（重点：PaddleOCR-VL v1.5）**：按当前“外部服务 + ZIP 产物”集成方式升级为 **PaddleOCR-VL-1.5**，并把解析产物（Markdown/JSON/Images）标准化，支撑后续可视化与溯源。
3. **入库文档分析可视化**：在 parsing / governance / chunk-preview 以及 dataset precheck/ingestion 页面提供一致的“文档画像”（长度分布、页面/图片/表格统计、语言/关键词、质量门禁原因）。
4. **文档治理（更多规则 + 可自定义）**：在现有治理开关基础上扩充 rule packs，并强化自定义规则（声明式 JSON/regex + UI 校验），让团队可复用/可审计。
5. **设置页体验**：模型提供商图标替换为 LobeHub 彩色图标风格，并统一映射/兜底逻辑，提升辨识度与一致性。

## 2) 非目标（Non-goals）

- 不重写整体 RAG 架构与存储层（Milvus/Postgres/MinIO/Redis 保持不变）。
- 不强制改变全局 UI 设计体系（只在新增/优化组件中对齐现有 tokens，并补齐可访问性与图标一致性）。
- 不把 PaddleOCR 相关重依赖塞进主后端镜像（继续使用外部解析服务）。

## 3) 总体方案（Architecture）

### 3.1 外部解析服务产物：统一 “ZIP Schema”

维持当前契约：后端通过 `PADDLE_VL_API_URL` 调外部服务，**服务返回 ZIP**。

新增约束（后端 best-effort 兼容多种输出）：
- ZIP 内至少包含一个 Markdown（优先 `result.md|output.md|index.md`）
- 若包含图片，统一规整到 `images/` 并重写 Markdown 引用（启用 MinIO 时上传并替换为 URL）
- 若包含结构化 JSON（layout/OCR），统一落到 `result.json`（用于可视化：blocks、bbox、页码等）

> 目标：把“不同解析器的怪异输出”收敛为后端可消费的稳定结构，从而支撑 parsing 与入库分析可视化。

### 3.2 PaddleOCR-VL v1.5 集成方式

外部服务（`docker/paddlevl`）升级为 **PaddleOCR 的 `doc_parser` 管线（v1.5）**：
- 输入：PDF
- 输出：Markdown + JSON（layout）+ 可选图片（页面渲染或裁剪）
- 对外 API：保持 `POST /convert`（multipart `file`）+ `GET /health`

后端 parser（`app/parsing/parsers/paddle_vl_parser.py`）：
- 继续把 ZIP 解压到 `.paddlevl/<run_id>/output`
- 使用统一 ZIP Schema 归一化（提取 md/json/images；必要时上传 MinIO；写入 metadata）

### 3.3 入库分析可视化（Parsing / Governance / Chunk）

复用现有页面与数据结构，补齐/统一：
- **Parsing**：展示解析质量门禁、blocks/图片统计、可选“结构化 JSON 浏览/抽样页 bbox 预览”
- **Governance**：除 diff 外，输出“规则命中归因”（default/pack/custom），并提供一键导出 profile
- **Chunk Preview**：补齐统计图（长度直方图、overlap 浪费、coverage、dup/gap flags），并支持 A/B 结果对比导出

### 3.4 文档治理规则扩展与自定义

- 扩充内置 `GOVERNANCE_RULE_PACKS`
- 自定义规则坚持“**声明式**”：
  - profiles（已有）：`pipeline_patch` + `regex_rules` + `rule_packs`
  - 增强：UI 侧正则实时校验 + server-side 强限制（避免 ReDoS）

### 3.5 设置页图标（LobeHub）

- 前端引入 LobeHub 彩色图标（静态 SVG 落地到 `web/public/logos/` 或通过 package 同步脚本）
- `ProviderIcon` 统一走 SVG（可选保留 PNG fallback），并在 `logos-preview` 页面验证多背景/多尺寸可读性

## 4) 测试与验收（Testing & Acceptance）

- 后端：为 ZIP 归一化与 `paddle_vl` parser 增加单测（不依赖真实模型）
- 前端：ProviderIcon 映射与兜底逻辑增加最小化组件测试（或 typecheck + lint + ui-check）
- 验收：`make verify` / `make enterprise-checks`（按项目当前 CI 约束）

