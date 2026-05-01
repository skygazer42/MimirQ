 # RAG 可视化全面调研 — 业界全景 + 接入建议

## Context

**触发场景**:用户从 `/knowledge/similarity` 页面(Plotly heatmap + 3D ForceGraph 诊断图)出发,要求**全面调研 RAG 可视化能力**并给出**接入建议**。RAG 系统的可视化贯穿"建库 → 检索 → 生成 → 评测 → 运营"全链路,是定位 bad case、解释结果、客户沟通和团队协作的核心工具。MimirQ 当前可视化资产已具规模(echarts/plotly/recharts/force-graph 全栈、相似度工作台、KG 浏览器、诊断面板),但**缺少业界主流 RAG 可视化平台的关键能力**(向量空间地图、检索 trace 时间线、chunk 在原文高亮、评测对比看板、会话拓扑、token 成本流),需要系统性补齐。

**目标**:盘清现状、对标业界主流方案(LangSmith / Langfuse / Phoenix / Atlas / GraphRAG Visualizer 等),给出**P0 接入清单**与**12 个月可视化路线图**,避免重复造轮子,优先复用已有依赖栈。

---

## 1. 现状盘点(已确认)

### 1.1 已有依赖栈(`web/package.json`)

| 库 | 版本 | 用途 |
|---|---|---|
| `plotly.js-dist-min` | 3.5.0 | 热力图、散点、3D 表面 |
| `echarts` | 6.0.0 | 通用统计图、桑基图、关系图 |
| `recharts` | 3.8.1 | React 原生折线/柱状/饼图 |
| `react-force-graph-2d` | 1.29.1 | 2D 力导向图 |
| `react-force-graph-3d` | 1.29.1 | 3D 力导向图 |

**结论**:可视化基础设施齐备,**无须新增大型库**;补能力靠组合现有依赖 + 少量新组件。

### 1.2 已实现页面与组件

| 路径 | 能力 | 关键文件 |
|---|---|---|
| `/knowledge/similarity` | 跨 Collection 相似度矩阵热力图 + 3D 诊断图 | `web/components/ragviz/similarity-workbench.tsx`(~700 行) + `similarity-diagnostics-graph.tsx`(react-force-graph-3d) |
| `/knowledge/evidence` | 证据/citation 工作台 | `web/components/ragviz/evidence-workbench.tsx` |
| `/graph` | KG 知识图谱浏览器 + 网络分析 panel + 节点/边详情 | `web/app/graph/_components/*` (graph-canvas / graph-node-detail-panel / kg-network-analysis-panel / graph-explainability-panel) |
| `/graph/diagnostics` | 图谱诊断 | `web/app/graph/diagnostics/page.tsx` |
| `/graph/snapshots` | KG 快照对比 | `web/components/graph/kg-snapshots-page.tsx` |
| `/diagnostics` | RAG 指标 / Embedding 漂移 / 性能套件 / A11y 标签 | `web/app/diagnostics/page-client.tsx` + 4 个 source.test |
| `/datasets/[id]/profile` | 数据集画像(分布/质量) | `web/app/datasets/[id]/profile/page-client.tsx` |
| `/datasets/[id]/health` | 数据集健康度 | `web/app/datasets/[id]/health/page-client.tsx` |
| `/datasets/[id]/precheck` | 入库前预检报告 | `web/app/datasets/[id]/precheck/page-client.tsx` |
| `/observability` | 可观测看板 | `web/app/observability/page-client.tsx` |
| `/reports` | 报告导出 | `web/app/reports/page-client.tsx` |
| `/evaluations` | 评估 | `web/app/evaluations/page.tsx` + `queryset-health-tab-client.tsx` |
| `/audit` | 审计 | `web/app/audit/page.tsx` |

### 1.3 已实现后端 API

- `app/api/v1/ragviz.py` — `/similarity/collections` + `/similarity/calculate`(矩阵计算,3000 项硬上限)
- `app/services/ragviz_similarity.py` — 跨 collection 相似度服务
- `web/lib/api/graph.ts` / `web/lib/api/rag.ts` / `web/lib/api/settings.ts` — 已拆分的可视化相关 API client

### 1.4 当前的 8 大缺口

1. ❌ **向量空间地图**(UMAP/t-SNE 散点 + 客户聚类),仅在 Pre-POC 计划提过,未落地前端
2. ❌ **检索 Trace 时间线**(LangSmith/Phoenix 风格)— pipeline 各阶段 latency 火焰图
3. ❌ **Chunk 在原文高亮回看**(PDF/DOCX 坐标级 highlight + 多 chunk 组合视图)
4. ❌ **评测对比看板**(基线 vs 实验,RAGAS/Trulens 风格)
5. ❌ **会话拓扑/Agent 决策图**(LangGraph Studio 风格,展示 agentic RAG 调用链)
6. ❌ **Token 成本流**(per-query / per-stage / per-model 成本归因)
7. ❌ **检索失败案例归因看板**(POC plan 的差评三分类可视化)
8. ❌ **多模态 chunk 预览**(图表/表格 thumbnail + bbox)

---

## 2. 业界 RAG 可视化全景(2024-2026)

### A. 检索/生成 Trace 与 LLM Observability 平台

| 平台 | 核心可视化 | 开源? | 是否可自部 | 与 MimirQ 关系 |
|---|---|---|---|---|
| **LangSmith** | 完整 trace 树 / token 成本 / playground / 评测 | 闭源 | ✗ | 商业,SaaS,$39/seat |
| **Langfuse** | trace + dataset + prompt + eval,UI 极佳 | ✅ MIT | ✅ Docker/K8s | **首选自部 trace 平台** |
| **Phoenix (Arize)** | embeddings 散点 / drift / RAG triad / span | ✅ Apache 2.0 | ✅ 单容器 | **embeddings 视图最强** |
| **TruLens** | RAG triad(context relevance / groundedness / answer relevance) + leaderboard | ✅ MIT | ✅ Python lib + UI | **评测可视化首选** |
| **OpenLIT** | OTel 原生 + dashboards | ✅ Apache 2.0 | ✅ | OpenTelemetry GenAI 推动者 |
| **Helicone** | 代理层 + 看板 | ✅ MIT(部分) | ✅ Docker | proxy 模式拦截全请求 |
| **Logfire** (Pydantic) | 时序 trace 优先 | 商业 | ✗ | Python 生态友好 |
| **W&B Weave** | trace + evaluation + datasets | 闭源(免费层) | ✗ | 与 W&B 体验同源 |
| **DeepEval** | pytest 化评测 + 报告 | ✅ Apache 2.0 | ✅ | CI 集成强 |
| **Promptfoo** | prompt 对比矩阵 / red team | ✅ MIT | ✅ | matrix view 极强 |

**评估**:**Langfuse + Phoenix + TruLens** 三者组合可覆盖 85% trace/embedding/evaluation 可视化需求,均开源可自部、有 OTel 兼容,与 MimirQ Python/FastAPI 栈无缝。

### B. 向量空间可视化

| 工具 | 能力 | 部署 |
|---|---|---|
| **Nomic Atlas** | 百万级 embedding 交互式地图 + 标注 | SaaS + 私有部 |
| **TensorBoard Embedding Projector** | PCA/UMAP/t-SNE 经典工具 | 自部署,免费 |
| **Phoenix Embeddings View** | 时序 drift + 异常聚类 | 已在 Phoenix 内 |
| **Pinecone Console** | embedding 查询可视化 | 仅 Pinecone 用户 |
| **Cohere Embed Studio** | 类 Atlas | 商业 |
| **datamapplot**(matplotlib 风格) | 静态 UMAP 图 + 主题标签 | Python lib |
| **DeepScatter** / **regl-scatterplot** | 百万点级 WebGL 散点 | 库,可嵌入前端 |

**评估**:**前端用 `regl-scatterplot` 或 `deck.gl` 自建** 性能与扩展最佳;**Atlas 风格的"主题标签 + 多边形圈选"是业界 SOTA**,可作为 P1 目标。Pre-POC scanner 已规划"UMAP 客户沟通可视化",此处复用。

### C. 知识图谱可视化

| 工具 | 能力 | 与 MimirQ |
|---|---|---|
| **Neo4j Bloom** / **NeoDash** | 商业可视化 | 已有 KG 但未必 Neo4j |
| **yWorks (yFiles)** | 商业级图布局 | 商业,$10k+ |
| **Cytoscape.js** | 开源,生态最大,布局丰富 | 候选,与 force-graph 互补 |
| **Sigma.js** + **Graphology** | WebGL 大规模(10w+ 节点) | **超大图首选** |
| **react-force-graph**(已用) | 2D/3D 力导向 | ✅ 已集成 |
| **GraphRAG Visualizer** (Microsoft) | 社区 + 实体子图 + LLM 摘要联动 | **GraphRAG 团队官方,Streamlit/React** |
| **Memgraph Lab** | 开源图 IDE | 与 Cypher 强绑定 |
| **D3-force** | 自定义最强,门槛高 | 已隐式使用 |

**评估**:已有 force-graph 适合中等规模(<2k 节点);**P1 引入 Sigma.js + Graphology** 处理 1w+ 节点社区视图,对齐 GraphRAG Visualizer。

### D. Chunk/原文高亮可视化

| 工具 | 能力 |
|---|---|
| **PDF.js + 自定义高亮层**(已用) | `web/public/pdfjs/` 在 |
| **Unstructured.io UI** | 解析后 element bbox 可视化 |
| **Llamacloud Parse Viewer** | 商业,一流体验 |
| **Docling Viewer** | 解析结果对照 |
| **react-pdf-highlighter** | React 组件,适合 chunk 标注 |
| **Layout Parser Viz** | 表格/图框 bbox |

**评估**:已有 PDF.js,**P0 在证据视图加 chunk-level bbox 高亮**(对齐 PoC-to-MVP plan 的"双重输出 + 点击跳转"理念)。

### E. 评测/对比可视化

| 工具 | 能力 |
|---|---|
| **RAGAS Dashboard** | 4 维(faithfulness/answer relevance/context precision/recall) + 趋势 |
| **TruLens Leaderboard** | 多 app 对比 + RAG triad 雷达 |
| **DeepEval** | 测试报告,适合 CI |
| **promptfoo viewer** | 矩阵对比(变体 × 测试用例) |
| **MLflow Evaluations** | 行业标杆 |
| **GraphRAG-Bench dashboard** | KG-RAG 专用 |

**评估**:`/evaluations` 页面已存在,但**缺 RAG triad 雷达 + 矩阵对比 + 失败案例钻取**;P1 接入 RAGAS/TruLens 思路。

### F. Agent/Workflow 拓扑

| 工具 | 能力 |
|---|---|
| **LangGraph Studio** | 节点/边可视化 + 时间旅行调试 + checkpoint diff |
| **AutoGen Studio** | 团队/智能体编排 |
| **CrewAI UI** | 类似 |
| **Llama Workflows Viewer** | 节点链路 |

**评估**:MimirQ 已用 LangGraph Functional API(`app/rag/pipelines/langgraph.py` 1751 行),**P1 自研 LangGraph 风格 workflow 浏览器**与 agentic-reasoning plan 协同。

### G. 标准与协议

- **OpenTelemetry GenAI Semantic Conventions**(OTel 2024 工作组)— trace 跨平台兼容
- **OpenInference** (Arize)— Phoenix 用,标准化 RAG span attributes
- **Span Kinds**:`llm` / `chain` / `retriever` / `embedding` / `reranker` / `tool`

**评估**:接入任何 trace 平台都应**先打 OTel/OpenInference span**,避免 lock-in。

---

## 3. Gap 分析(MimirQ vs 业界)

| 维度 | 业界 SOTA | MimirQ 现状 | Gap | 优先级 |
|---|---|---|---|---|
| 检索 Trace 时间线 | LangSmith/Phoenix span 树 + flame | 仅 `/diagnostics` 性能套件聚合 | **缺 per-query span tree** | **P0** |
| 向量空间 2D 地图 | Atlas / Phoenix UMAP | 无 | **完全缺** | **P0** |
| Chunk 原文高亮 | Llamacloud Parse Viewer | PDF 已支持但未联动 chunk | 缺 chunk → bbox 联动 | **P0** |
| RAG triad 评测 | TruLens/RAGAS | `/evaluations` 通用 | 缺标准化雷达 + 失败钻取 | P1 |
| Agent workflow 浏览器 | LangGraph Studio | 无 | LangGraph 已用但未可视化 | P1 |
| Token 成本流 | LangSmith / Helicone | 无 | 缺 per-stage 成本归因 | P1 |
| 大规模 KG (10w+ 节点) | Sigma.js / GraphRAG Visualizer | force-graph 上限 ~2k | 缺 WebGL 大图渲染 | P2 |
| 多模态 chunk 预览 | Unstructured UI | 无 | 图表/表格 thumbnail | P2 |
| 客户沟通故事板 | Atlas + 多边形圈选 | 无 | 缺导出报告级别可视化 | P2 |
| 红队/Jailbreak 看板 | Garak / promptfoo red team | 无 | safety plan 已有 redteam 但无 UI | P3 |

---

## 4. 推荐方案:三层接入策略

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3 — 战略层(P2/P3,自研深度可视化)                       │
│   - WebGL 向量地图(Atlas 风格)                                │
│   - Sigma.js KG 大图                                            │
│   - 多模态 chunk gallery                                        │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2 — 集成层(P1,接入开源平台)                            │
│   - Langfuse(trace + prompt + dataset)自部                    │
│   - Phoenix(embeddings drift + RAG triad)自部                 │
│   - TruLens(评测雷达)                                         │
│   通过 OTel/OpenInference span 单点埋点,多平台共用            │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 — 现有栈增量(P0,2-3 周快速交付)                      │
│   - per-query span 时间线(echarts gantt)                      │
│   - 向量 UMAP 2D 散点(plotly,后端预算 UMAP)                  │
│   - chunk PDF bbox 高亮联动(PDF.js + 已有坐标)              │
│   - 失败案例归因看板(三分类柱状 + 钻取)                      │
└──────────────────────────────────────────────────────────────────┘
```

**核心设计原则**:
1. **OTel-first**:先打标准化 span,再选 UI(Langfuse/Phoenix 都支持)
2. **复用依赖**:plotly + echarts + force-graph 已能覆盖 80% 需求,**避免引入 d3 重复造轮子**
3. **联动而非孤岛**:chunk → 原文 → 检索分数 → trace span 一键跳转
4. **客户可导出**:每个可视化必须有"导出 PNG / JSON / 报告"按钮(对齐 Pre-POC scanner 的离线脱敏报告原则)

---

## 5. P0 落地任务(2-3 周交付)

### 5.1 Per-query 检索 Trace 时间线(~600 行)

**新建** `web/components/ragviz/retrieval-trace-timeline.tsx`:
- 输入:`/api/v1/rag/explain` 的 trace JSON(已有 `app/api/v1/retrieval_explain.py`)
- 用 echarts gantt 展示各 stage:`embed → vector_search → bm25 → rerank → expand → llm_generate`
- 每段显示 latency、命中数、score 范围
- 点击 stage 展开 sub-spans
- **嵌入位置**:`/knowledge/similarity` 与 `/diagnostics` 各加一个 tab

**后端**:`app/rag/retrieval/orchestrator.py` 增加 OTel span(`opentelemetry.trace`),OpenInference 命名约定(`retriever`/`reranker`/`llm`)

### 5.2 向量空间 UMAP 2D 散点(~500 行)

**新建** `web/components/ragviz/embedding-map.tsx`:
- 用 plotly `scattergl`(已用 plotly,`scattergl` 适合 50k 点)
- 颜色编码:document_id / cluster_id / score / quarantine_status
- 框选 → 输出 chunk_id 列表 → 跳转 `/knowledge/evidence`
- **后端**:`app/api/v1/ragviz.py` 新增 `/embedding-map` endpoint
- 算法:`umap-learn` Python 包(预计算 + Redis 缓存,数据集 SHA 为 key)
- 数据量 >5w 走采样;支持 user 上传自定义 query 标记位置

### 5.3 Chunk PDF Bbox 高亮联动(~300 行)

**修改** `web/components/ragviz/evidence-workbench.tsx`:
- 检索结果 citation 已有 `page_number` / `chunk_index`
- 利用 `app/parsing/parsers/` 输出的 bbox(检查 metadata 字段)
- 用 PDF.js overlay 多 chunk 高亮(同色族表示同一 query)
- **新增** `web/components/ragviz/pdf-highlight-layer.tsx`(150 行复用 react-pdf-highlighter 思路)

### 5.4 失败案例归因看板(~400 行)

**新建** `web/app/evaluations/bad-cases/page.tsx`:
- 对齐 POC-attribution plan 的三分类(检索不到 24% / 答错 35% / 超纲 37%)
- 用 echarts pie + sankey 展示从 query → 失败原因
- 钻取列表:点击分类显示 query + final_context + feedback,导出 CSV
- **后端**:利用已规划的 `evaluation/poc_runner/` 5 字段埋点(若已落地)

### 5.5 OTel/OpenInference 埋点

**修改**:
- `app/rag/engine.py` / `pipelines/langgraph.py` / `retrieval/orchestrator.py` 加 OTel span
- 新建 `app/observability/otel_tracer.py` 统一 tracer 配置
- 安装 `opentelemetry-sdk` + `openinference-semantic-conventions`(纯库,无服务依赖)
- export 默认到 console,可配置 OTLP endpoint(指向 Langfuse/Phoenix)

---

## 6. P1 落地任务(1-2 个月)

### 6.1 接入 Langfuse(自部署)
- Docker Compose 一键起;配 OTLP endpoint
- 配置 Langfuse `dataset` + `score`,与 `/evaluations` 双向打通
- 收益:获得现成的 prompt 管理、A/B、人工标注 UI

### 6.2 接入 Phoenix
- Docker 单容器,Embedding view + Drift detection 开箱即用
- 把 chunk embeddings 持续 export
- 与 `embedding_drift_monitor.py` 配合(已有服务,见现有审查 memory)

### 6.3 RAG Triad 评测雷达
- TruLens 思路(faithfulness / context relevance / answer relevance)
- 用 echarts radar,放 `/evaluations` 标准化 tab
- 后端复用 `app/rag/evaluation/ragas.py`

### 6.4 Workflow 浏览器
- 自研:从 `app/rag/pipelines/langgraph.py` 解析 graph 结构
- react-force-graph-2d 渲染节点(已用)
- 点击节点显示该 step 的 in/out + 时长
- 时间旅行(回放历史 query 的执行路径)

### 6.5 Token 成本流
- 在 OTel span attribute 里记录 input_tokens / output_tokens / model
- 前端用 sankey(echarts)展示 query → stage → model → cost
- 与已有 cost tracker(rag-deep-research plan Quick Win)对接

---

## 7. P2/P3(季度计划)

- **P2**:Sigma.js + Graphology 替换 force-graph 处理 1w+ KG 节点
- **P2**:多模态 chunk gallery(图表/表格 thumbnail,LayoutLM bbox)
- **P2**:Atlas 风格主题标签 + 多边形圈选导出
- **P3**:红队/Jailbreak 失败案例看板(对齐 safety plan 的 `redteam_suite.py`)
- **P3**:客户故事板编辑器(选区 + 注释 + 一键 PDF)
- **P3**:WebGL 1M+ 点 embedding 地图(`regl-scatterplot` 或 `deck.gl`)

---

## 8. 关键文件清单

**修改**:
- `app/rag/engine.py`(OTel span)
- `app/rag/pipelines/langgraph.py`(OTel + workflow 元数据导出)
- `app/rag/retrieval/orchestrator.py`(per-stage span)
- `app/api/v1/ragviz.py`(新增 `/embedding-map` 与 `/trace/{query_id}`)
- `app/api/v1/retrieval_explain.py`(扩 trace JSON 结构)
- `web/components/ragviz/similarity-workbench.tsx`(加 trace tab)
- `web/components/ragviz/evidence-workbench.tsx`(加 PDF 高亮联动)
- `web/app/diagnostics/page-client.tsx`(加 trace 时间线 tab)
- `web/app/evaluations/page.tsx`(加 RAG triad + bad cases)
- `web/lib/api/rag.ts` 或 `web/lib/api-client.ts`(新增 trace / embedding-map 方法)

**新建**:
- `app/observability/otel_tracer.py`
- `app/services/ragviz_embedding_map.py`(UMAP 服务 + Redis 缓存)
- `web/components/ragviz/retrieval-trace-timeline.tsx`
- `web/components/ragviz/embedding-map.tsx`
- `web/components/ragviz/pdf-highlight-layer.tsx`
- `web/components/ragviz/rag-triad-radar.tsx`(P1)
- `web/components/ragviz/workflow-explorer.tsx`(P1)
- `web/app/evaluations/bad-cases/page.tsx`
- `tests/test_otel_spans.py` / `tests/test_embedding_map_service.py`

**复用**(零修改):
- 已有依赖:plotly / echarts / recharts / react-force-graph-2d/3d
- `app/services/ragviz_similarity.py`
- `app/rag/evaluation/ragas.py`
- `app/services/embedding_drift_monitor.py`
- PDF.js (`web/public/pdfjs/`)

---

## 9. 验证方法

1. **OTel 单测**:`pytest tests/test_otel_spans.py` — 验证 span 名称符合 OpenInference 约定
2. **trace 联调**:发一条 query → `/diagnostics` 展示完整 stage timeline,latency 与服务端日志一致
3. **embedding map 联调**:`pnpm dev`,访问 `/knowledge/similarity` → embedding map tab → 框选 50 个点 → 跳转 evidence 显示对应 chunks
4. **PDF 高亮联调**:`/knowledge/evidence` 检索一篇带 PDF 的文档 → 点击 citation → PDF 自动跳页 + 高亮 bbox
5. **bad cases 联调**:`/evaluations/bad-cases` 显示三分类饼 + 钻取,导出 CSV 字段齐全
6. **Langfuse 集成**(P1):docker compose up langfuse → 配 OTLP endpoint → 一条 query 在 Langfuse UI 出现完整 trace
7. **Phoenix 集成**(P1):docker run phoenix → embedding 持续上报 → 漂移图非空
8. **完整验证**:`pnpm verify` + `pytest tests/` 全绿

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| OTel 埋点性能开销 | 默认采样率 10%(配置可调);span attr 仅核心字段;批量 export |
| UMAP 计算耗时(>10s) | 后端预算 + Redis 30 天缓存;数据集 SHA + sample_count 为 key;首次冷启提示用户 |
| Langfuse/Phoenix 自部署成本 | 单 Docker 容器 + SQLite 即可起步;生产再切 Postgres |
| 大规模 embedding 内存爆 | scattergl 50k 点上限;>5w 强制采样;前端 `<canvas>` 分片渲染 |
| PDF bbox 数据缺失 | 解析器输出空 bbox 时降级到 page-level 高亮;不阻塞 |
| trace 数据隐私(query 含 PII) | OTel attr 走 Presidio 脱敏(对齐 safety plan);采样存原文 |
| LangGraph workflow 结构变化 | 浏览器只读,从 graph definition 文件实时解析,不缓存 |

---

## 11. 与已有调研的关系

- 与 `plans/rag-pre-poc-scanner-2026-q2.md` "UMAP 客户沟通可视化" 同源,本计划是其**前端落地形态**
- 与 `plans/rag-poc-attribution-framework-2026-q2.md` "5 字段埋点 + 差评三分类" 配对,本计划新增 `/evaluations/bad-cases` 看板
- 与 `plans/rag-agentic-reasoning-deep-dive-2026-q2.md` 的 LangGraph 栈协同,P1 workflow 浏览器是其可视化 UI
- 与 `plans/rag-kg-deep-research-2026-q2.md` 的 KG agentic search 协同,P2 Sigma.js 替换 force-graph 支持大规模图谱
- 与 `plans/rag-safety-compliance-deep-dive-2026-q2.md` 的 redteam 协同,P3 红队失败案例看板
- 与 `plans/rag-auto-tagging-services-2026-q2.md`(刚完成)的标签协同:embedding map 颜色可按 LLM 生成的 topic/category/domain 编码
- 与 `plans/rag-poc-to-mvp-delivery-2026-q2.md` 的"Query Rewrite SSE 透出"理念一致:**让用户看到 RAG 的内部决策**是核心信任建设

---

## 12. 关键洞察

1. **可视化的最大价值不是好看,是"定位 bad case"**:每个可视化都应支持从聚合 → 个体的钻取(对齐 POC plan)
2. **OTel 是 lock-in 的解药**:任何 LLM observability 平台都在跟进,先标准化埋点再选 UI
3. **客户能拿走的可视化才有价值**:导出 PNG/PDF/CSV 是产品差异化(对齐 Pre-POC plan 离线报告原则)
4. **力导向 vs WebGL**:<2k 节点用 force-graph(美观、交互流畅),>1w 用 Sigma.js(性能、信息密度)
5. **不要全自研**:Langfuse + Phoenix 自部 + 自研 5 个组件 = 业界一线水平,自研 trace 平台是死路
6. **RAG triad 是评测的"红绿灯"**:faithfulness / context relevance / answer relevance,任何 RAG 项目都该有

---

## 13. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地:
- 后端闭环:`/api/v1/chat/conversations/{conversation_id}/rag-traces` 提供会话级 PII-safe trace 列表,`/api/v1/observability/rag-metrics/trace-bundle` 与 `/trace-bundle/diff` 提供 request 级导出和对比.
- 前端闭环:`RagTraceDialog` / `RagTracePanel` 已支持 pipeline timeline、channel score、top citations、证据漂移、bundle ZIP 导出和 request diff.
- 显式入口:历史页与首页对话页均可从当前会话直接打开 RAG Trace,无需复制后端 ID 或跳转诊断工作台.
- 测试闭环:后端 trace schema/bundle/diff 测试与前端 trace source/timeline/channel 测试覆盖主要路径.

暂缓:
- Langfuse / Phoenix / TruLens 自部署集成.
- UMAP/Atlas 风格向量地图与 WebGL 百万点地图.
- Sigma.js 超大 KG 与多模态 chunk gallery.
- OTel/OpenInference 全链路埋点迁移.

Directive: 后续只在真实使用路径出现缺口时增量补可视化,不要把外部 observability 平台和实验地图默认塞进主产品界面.
