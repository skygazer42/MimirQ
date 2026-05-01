# `/knowledge/ingestion` 入库流水前端调研 — 现状评估 + 自研深化

## Context

**触发场景**:用户从 `/knowledge/ingestion` 出发,要求对**知识库入库流水前端**做全面调研,**约束:不引大包优先自研**。这是 RAG 入库的"主流水线":upload → parse → chunk → embed → KG → ready。前端是用户监控/调试入库的核心 UI,涉及大量异步状态、错误归因、批量操作。

**问题**:`/knowledge/ingestion` 已极重(`page-client.tsx` **3720 行**!+ `web/components/ingestion/` 多组件:bulk-action-bar 151 / drop-zone 254 / empty-state 142 / error-treemap 62 / ingestion-detail-dialog 503 / live-velocity 57 / stat-card 90 / monitor-utils),覆盖文件上传 / 批量操作 / 速度指标 / 错误 treemap / 详情 dialog / 状态卡,**但缺**:① 端到端 stage 时间线(parse→chunk→embed→KG 各阶段进度)② 失败案例归因看板(对齐 POC plan 三分类)③ 流水重试/续传 UI ④ 增量入库 vs 全量重导 选择 ⑤ 入库前预检集成(对接 `/datasets/[id]/precheck`)⑥ 双重输出可视化(Markdown + DOCX)⑦ 速度异常告警(基于 live-velocity)⑧ 资源占用看板(LLM 配额、embedding 队列水位)。本调研对标 LangChain Document Loaders / LlamaIndex Ingestion Pipeline / Unstructured / Llamacloud,**全部自研**。

---

## 1. 现状盘点

### 1.1 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `page-client.tsx` | **3720** | 主 client 组件(过重,需拆) |
| `page.tsx` | 38 | server entry |
| `demo-documents.ts` | - | 演示数据 |
| `web/components/ingestion/ingestion-detail-dialog.tsx` | 503 | 详情对话框 |
| `web/components/ingestion/drop-zone.tsx` | 254 | 拖拽上传 |
| `web/components/ingestion/bulk-action-bar.tsx` | 151 | 批量操作 |
| `web/components/ingestion/empty-state.tsx` | 142 | 空态 |
| `web/components/ingestion/stat-card.tsx` | 90 | 状态卡 |
| `web/components/ingestion/error-treemap.tsx` | 62 | 错误 treemap |
| `web/components/ingestion/live-velocity.tsx` | 57 | 速度指标 |
| `web/components/ingestion/monitor-utils.ts` | - | 监控工具 |

### 1.2 已具备能力

- ✅ **拖拽上传** + 批量操作
- ✅ **实时速度** (live-velocity)
- ✅ **错误 treemap** (按错误类型可视化)
- ✅ **状态卡** (待处理 / 进行中 / 完成 / 失败)
- ✅ **详情 dialog** (单文件 503 行)
- ✅ **demo 模式**
- ⚠️ 主组件 3720 行**过重,可维护性差**

### 1.3 8 大缺口

1. ❌ **端到端 stage 时间线**(parse → chunk → embed → KG 阶段化进度)
2. ❌ **失败案例归因看板**(对齐 POC plan 差评三分类)
3. ❌ **流水重试 / 续传 UI**(失败的 stage 可单独重跑而非全量重导)
4. ❌ **增量 vs 全量**选择(只入新文档 vs 重导整个数据集)
5. ❌ **预检集成**(上传前先跑 Pre-POC scanner)
6. ❌ **双重输出可视化**(Markdown 入库 + DOCX 跳转,对齐 PoC-to-MVP)
7. ❌ **速度异常告警**(基线 +3σ 触发)
8. ❌ **资源占用看板**(LLM 配额 / embedding 队列水位 / GPU 占用)

---

## 2. 业界对标

| 工具 | 借鉴点 | 排除原因 |
|---|---|---|
| **LangChain Document Loaders** | 文档源接入 | 全套强耦合 |
| **LlamaIndex Ingestion Pipeline** | pipeline 模型 | 引入框架太重 |
| **Unstructured.io** | element-aware | 商业 |
| **Llamacloud** | 一流体验 | 商业 SaaS |
| **Airbyte** | ELT 模型 | 偏数据集成不是 RAG |
| **Prefect / Dagster** | 工作流编排 | 服务太重(P3 才考虑) |

**结论**:全部自研,流水线状态机 + 时间线 UI。

---

## 3. P0 落地任务(2-3 周)

### 3.1 端到端 stage 时间线(~500 行)

**新建** `web/components/ingestion/ingestion-stage-timeline.tsx`:
- 每个文档显示 5-stage 进度(类似 GitHub Actions):
  - `upload` → `parse` → `chunk` → `embed` → `kg`(可选) → `ready`
- 每 stage:状态(pending / running / success / failed) + 耗时 + token 消耗
- 失败 stage 可点击查看 stack trace(脱敏)
- 与 OTel span 联动(viz plan P0)
- 用 echarts gantt(已有)

### 3.2 失败案例归因看板(~400 行)

**新建** `web/components/ingestion/failure-attribution-dashboard.tsx`:
- 对齐 POC plan 三分类:`parse_failed / chunk_failed / embed_failed / kg_failed / quota_exceeded / acl_blocked`
- 饼图(echarts)+ 钻取列表
- 每分类显示 top-N 失败文档 + 推荐修复
- 一键批量重试 stage

### 3.3 流水重试 / 续传(~350 行)

**新建** `web/components/ingestion/stage-retry-controls.tsx`:
- 失败 stage 单独重跑(不重 upload)
- 续传:已完成 stage 跳过,从失败处继续
- 后端:`POST /api/v1/ingestion/{doc_id}/retry?from=stage_name`
- 复用已有 `ingestion-detail-dialog.tsx` 503 行架构

### 3.4 增量 vs 全量选择(~200 行)

**修改** `bulk-action-bar.tsx`:
- 选中数据集时显示 toggle:`增量入库`(只新文档)/ `全量重导`(强制重处理)
- 全量重导前 confirm dialog(避免误操作)
- 显示预期影响:N 文档 / 预估 X 分钟 / Y¥成本

### 3.5 入库前预检集成(~250 行)

**新建** `web/components/ingestion/precheck-banner.tsx`:
- 上传后自动触发 `/datasets/[id]/precheck`(对齐 Pre-POC scanner)
- 显示 5 档文档标签(Clean_Markdown / Scan_PDF / Table_Heavy / Image_Heavy / Parse_Failed)
- 高风险文档(Scan_PDF + 大 Excel)标红警告
- 可选"先预检不入库"模式

### 3.6 双重输出可视化(~300 行)

**修改** `ingestion-detail-dialog.tsx`(503 行):
- 完成 stage 后展示双重输出:
  - `Clean Markdown`(入库)
  - `Clean DOCX`(点击跳转,对齐 PoC-to-MVP plan)
- 图片双阶段(Base64→MinIO 映射,对齐 PoC-to-MVP)

### 3.7 速度异常告警(~200 行)

**修改** `live-velocity.tsx`(57 行):
- 记录基线速度(p50)
- 当前 < p50 - 3σ 触发 banner 告警
- 显示可能原因(LLM 限流 / 网络 / GPU 占满)

### 3.8 拆 3720 行 page-client(~重构,不增量)

**重构** `page-client.tsx`(3720 → ~1500):
- 拆为:`ingestion-page-shell.tsx` / `ingestion-doc-list.tsx` / `ingestion-stats-bar.tsx` / `ingestion-filter-toolbar.tsx`
- 严格保留所有 source.test 用例
- 提升可维护性,新功能更易加

---

## 4. P1 任务

### 4.1 资源占用看板
- LLM 配额使用率 / embedding 队列水位 / GPU 占用
- 与 `/usage` 联动

### 4.2 入库工作流模板
- 保存 user 自定义流水(parser + chunking + KG 开关)
- 复用快速创建数据集

### 4.3 多源接入(对齐 deep-research 连接器前 5)
- SharePoint / Confluence / Notion / GitHub / S3
- 统一 ConnectorBase 抽象(已有 `app/connectors/base.py`)

### 4.4 入库时序对比
- 同数据集不同时间入库结果(对齐 snapshot plan)

### 4.5 黑名单文档隔离
- 持续失败文档自动加入黑名单(对齐 quarantine plan)

---

## 5. 关键文件

**重构**:
- `page-client.tsx`(3720 → ~1500,拆 4 个子组件)
- `ingestion-detail-dialog.tsx`(503,加双重输出)
- `bulk-action-bar.tsx`(151,加增量/全量)
- `live-velocity.tsx`(57,加异常告警)

**新建**:
- `web/components/ingestion/ingestion-stage-timeline.tsx`(P0)
- `web/components/ingestion/failure-attribution-dashboard.tsx`(P0)
- `web/components/ingestion/stage-retry-controls.tsx`(P0)
- `web/components/ingestion/precheck-banner.tsx`(P0)
- `web/components/ingestion/ingestion-page-shell.tsx`(P0,拆出)
- `web/components/ingestion/ingestion-doc-list.tsx`(P0,拆出)
- `web/components/ingestion/ingestion-stats-bar.tsx`(P0,拆出)
- `web/components/ingestion/ingestion-filter-toolbar.tsx`(P0,拆出)

**复用**:
- 已有 `monitor-utils.ts`(getDocumentKind 等)
- echarts gantt(已用)
- viz plan OTel span 数据源
- Pre-POC scanner 5 档文档标签

---

## 6. 验证

1. stage 时间线:上传 5 文档,看到每个 5 stage 进度
2. 失败归因:故意上传损坏 PDF → parse_failed 分类正确
3. 重试:点击 "retry from chunk" → 不重 upload/parse
4. 增量入库:数据集已有 100 文档,新加 5 → 只处理 5
5. 预检:扫描 PDF → 🔴 banner 警告
6. `pnpm verify` + 11 个现有 source.test 全过(关键!不能拆碎)

---

## 7. 与已有调研协同

- **`rag-pre-poc-scanner`**:5 档文档标签 + 7 项核心功能集成入预检 banner
- **`rag-poc-attribution-framework`**:差评三分类对接失败归因看板
- **`rag-poc-to-mvp-delivery`**:双重输出 + 图片双阶段 + 业务专家反馈基础设施
- **`rag-deep-research`** 连接器前 5(SharePoint/Confluence/Notion/GitHub/S3) → P1
- **`rag-visualization-deep-dive`** OTel span 是时间线数据源
- **`rag-parsing-chunking-deep-dive`** 各 stage 联动后端
- **`rag-auto-tagging-services`** 入库时自动打标(治理打标流水)

---

## 8. 关键洞察

1. **3720 行 page-client 是技术债**:必须拆,否则后续所有新功能都难加
2. **stage 时间线是真护城河**:让客户看到入库每一步,信任建设(对齐 PoC-to-MVP "让用户看到 RAG 内部决策")
3. **失败归因比成功率重要**:平均成功率 95% 没意义,要看哪 5% 失败 + 为什么(对齐 POC 差评分类)
4. **增量入库是企业刚需**:大数据集全量重导成本高,默认应增量
5. **不引大包**:LlamaIndex Ingestion Pipeline 全套都不要,自研 8 个组件 ~2200 行
6. **预检前置是 Pre-POC 落地点**:用户上传前就知道"会不会糟糕",对齐"基于样例报价总偏差"的解药

---

## 9. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- 入库页已拆成售前摸底/执行监控双模式,默认面向售前证据台,保留执行监控作为二级模式。
- 售前模式已接入预检 summary、samples、near-dup、风险热力、建议 POC 样本、高风险文件、脱敏报告导出与 demo 数据。
- 执行监控模式已接任务队列、worker、最近结果、预检抽样侧栏和刷新流程,满足本地联调和上线观察的必要闭环。

明确不做:
- 连接器配置/Run replay/Reconcile 这类开发排障操作不再作为显著运营 UI 暴露,避免把运维日志台塞进知识库主页面。
- 暂不按本文继续拆 8 个独立 ingestion 子组件;只有当 page-client 维护成本再次阻塞功能时再做专门重构。

Directive: 入库页面后续优先服务“客户样本摸底、报价证据、执行状态可见”,开发排障走日志/API/诊断页。
