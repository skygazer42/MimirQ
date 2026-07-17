<div align="center">

<img src="./images/logo.png" alt="MimirQ" width="100%"/>

<h3>看得见的 RAG · 中文知识库问答平台</h3>

<p><b>不是又一个黑盒 RAG</b>——从文档怎么被切、检索命中了什么、答案凭什么这么答，每一步都摊开给你看、让你调。</p>

<p>深度文档理解 · 混合检索 · 知识图谱 · 可视化切片 · 评测治理 · 企业级安全</p>

<p>
  <a href="https://github.com/skygazer42/MimirQ/wiki"><b>文档</b></a> ·
  <a href="https://skygazer42.github.io/MimirQ/"><b>在线 API</b></a> ·
  <a href="./docs/api/README.md"><b>API 导读</b></a> ·
  <a href="#-快速开始"><b>快速开始</b></a> ·
  <a href="https://github.com/skygazer42/MimirQ/issues"><b>反馈</b></a> ·
  <a href="./.github/CONTRIBUTING.md"><b>参与贡献</b></a>
</p>

<p>
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License: Apache 2.0"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"/></a>
  <a href="https://nextjs.org/"><img src="https://img.shields.io/badge/Next.js-14-black" alt="Next.js 14"/></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.135-009688.svg" alt="FastAPI"/></a>
  <a href="https://langchain.com/"><img src="https://img.shields.io/badge/LangChain-1.x-green" alt="LangChain"/></a>
  <a href="https://langchain-ai.github.io/langgraph/"><img src="https://img.shields.io/badge/LangGraph-1.0-1C3C3C" alt="LangGraph"/></a>
  <a href="https://milvus.io/"><img src="https://img.shields.io/badge/Milvus-2.3-00a1e0" alt="Milvus"/></a>
</p>

<p>
  <a href="https://github.com/skygazer42/MimirQ"><img src="https://img.shields.io/github/stars/skygazer42/MimirQ?style=social" alt="GitHub Stars"/></a>
  <a href="https://github.com/skygazer42/MimirQ/issues"><img src="https://img.shields.io/github/issues/skygazer42/MimirQ" alt="GitHub Issues"/></a>
  <a href="https://github.com/skygazer42/MimirQ/actions"><img src="https://img.shields.io/github/actions/workflow/status/skygazer42/MimirQ/ci.yml?label=CI" alt="CI Status"/></a>
</p>

<p>
  <a href="./README.md"><img src="https://img.shields.io/badge/简体中文-d9d9d9" alt="简体中文"/></a>
  <a href="./README_EN.md"><img src="https://img.shields.io/badge/English-d9d9d9" alt="English"/></a>
</p>

</div>

---

## 🤔 为什么又一个 RAG 项目？

大多数 RAG 工具在你问"**为什么答错了**"时只能耸耸肩——文档被怎么切的看不见，检索到底命中了什么看不见，答案凭哪句原文生成的也看不见。调参像开盲盒。

**MimirQ 把这些黑盒全打开了：**

- 📐 **切块所见即所得**——上传文档，实时预览分块效果、边界、打分，参数一改立刻重算，不用反复入库试错。
- 🔬 **检索全程可追溯**——每次问答都有 Trace：走了哪些通道、命中哪些片段、重排怎么调序、引用来自原文哪一句，一目了然。
- 📊 **质量用数字说话**——内置 RAGAS 评测 + 回归门禁 + Leaderboard，改动效果好不好有基线对比，不靠"感觉变好了"。
- 🇨🇳 **中文是一等公民**——从中文分词、混排 PII 脱敏，到中文政务/金融场景的行业规则库，不是英文项目顺手加个中文。

> 一句话：**MimirQ 帮你把"能跑的 Demo"变成"敢上生产、出了问题查得到根因"的知识库系统。**

---

## 📍 已在真实场景验证

MimirQ 不是实验室 Demo——它已在**市级政务智能问答助手**场景落地，覆盖 7 个区级 + 市级共多个真实知识库，并用一套 **800 题政务基准 + 确定性评测（无 LLM judge、参数固定）** 做了同参前后对比。

<!-- 数据来源：artifacts/dify_3way_benchmark_*_20260713/（被 .gitignore 忽略，盘上留档可查）。下表均为 2026-07-13 实测值。 -->

| 指标（800 题政务基准 · 2026-07-13 同参复测） | 结果 |
|:---|:---|
| **完整执行成功率** | **800 / 800**（旧链路为 687 / 800） |
| **配对平均时延（共同 687 题）** | **5.1 秒** ← 旧链路 35.1 秒（**↓ 85.5%**） |
| **配对中位时延（共同 687 题）** | **4.9 秒** ← 旧链路 34.8 秒（↓ 86.1%） |
| **完整 800 题平均时延** | **5.0 秒** |
| **答案可用率** | 86.4% |
| **答案条款覆盖率** | 80.2% |
| 评测方式 | 确定性证据条款匹配，参数固定 |

> 📝 **诚实说明**：本次同参复测的硬结论是 **端到端时延骤降（35s → 5s）且 800 题全部跑通**；答案质量为当前绝对值，尚未在统计意义上超过旧版（区级 +3pp，市级因输出风格变化 -15.7pp，正在恢复完整字段输出）。完整报告与逐题结果保存在测试机器的 `artifacts/`，未随公开仓库发布；中文公开可复现基准（MIRACL-zh / CFEVER）见 [公开评测指南](./docs/guides/public_benchmarks_zh.md)。

**🔌 无缝接入 Dify 生态**：MimirQ 提供 [Dify External Knowledge API](./docs/guides/pipeline_plugins.md) 兼容接口，可作为**外部知识库**直接挂到 Dify 工作流——已有的 Dify 应用无需改造，即可用上 MimirQ 的混合检索、知识图谱与引用溯源能力。上面这套 800 题基准，正是通过 Dify HTTP 链路直连 MimirQ 跑出来的。

---

## 📑 目录

- [为什么又一个 RAG 项目？](#-为什么又一个-rag-项目)
- [已在真实场景验证](#-已在真实场景验证)
- [核心特性](#-核心特性)
- [项目规模](#-项目规模)
- [系统架构](#-系统架构)
- [RAG Pipeline](#-rag-pipeline)
- [技术栈](#-技术栈)
- [快速开始](#-快速开始)
- [API 参考（OpenAPI / Pages）](#-api-参考openapi--github-pages)
- [部署方式](#-部署方式)
- [功能指南](#-功能指南)
- [开发自检](#-开发自检)
- [Roadmap](#-roadmap)
- [参与贡献](#-参与贡献)
- [许可证](#-许可证)
- [致谢](#-致谢)

---

## 💡 MimirQ 是什么

**MimirQ**（名字取自北欧神话中守护智慧之泉的巨人 **Mímir**）是一个**全栈开源、中文优先**的 RAG 知识库问答平台。它把**深度文档理解、混合检索、知识图谱、可视化切片、评测治理、企业级安全**整合成一套可以直接上手的系统——前端后端都开源，Docker 一键起。

它面向这样的团队：

- 想搭一个**能落地生产**的企业知识库，而不只是跑通一个 Demo；
- 受够了 RAG 调参靠玄学，想要**看得见、可复现、有基线**的迭代方式；
- 处理的是**中文文档**（合同、政务、金融、技术手册），需要真正的中文解析与合规能力。

---

## ✨ 核心特性

<div align="center">
  <img src="./docs/images/features.svg" alt="MimirQ Features" width="100%"/>
</div>

<br/>

<table>
  <tr>
    <td width="50%">

**🔍 混合检索引擎**

开箱即用的 **Vector 语义 + BM25 关键词** 双通道，RRF 融合排序，兼顾"理解意思"和"精确命中关键词"。需要更强召回时，可按需开启 **SPLADE 稀疏检索、ColBERT 晚交互重排、LTR 学习排序**——能力齐备，默认精简。

</td>
    <td width="50%">

**📐 可视化切片预览**

上传即预览，告别黑盒切块。多策略并排（递归 / 语义 / 分层 / 父子），边界可视、打分透明、参数即改即算，所见即所得。
→ [使用指南](./docs/guides/chunk_preview.md)

</td>
  </tr>
  <tr>
    <td>

**🔄 多模态文档解析**

**30+ 种解析后端**覆盖 PDF / Markdown / HTML / 图文混排。集成 PyMuPDF、MinerU、ETL4LLM、Marker、Docling、PaddleOCR-VL、olmOCR、Qianfan-OCR，中文扫描件与复杂版式也能拿下，可按需扩展。

</td>
    <td>

**💬 RAG 智能问答**

流式响应、逐句引用溯源、多轮对话记忆。基于 LangChain Runnable 架构，可选 LangGraph Agent 流水线（Self-RAG / CRAG / FLARE 等自纠正策略）。

</td>
  </tr>
  <tr>
    <td>

**🕸️ 知识图谱（KG）**

从文档自动抽取实体 / 事件 / 关系，Force Graph 可视化、多跳检索、社区发现。更进一步：**图谱快照精确 Diff + BFS 影响分析**，改一处知识能看到牵连了哪些下游。可回注 RAG 做 query expansion。
→ [使用指南](./docs/guides/knowledge_graph.md)

</td>
    <td>

**📊 评测治理框架**

内置 RAGAS（Faithfulness / Relevancy / Context Precision）+ **回归门禁 + Leaderboard + 统计显著性检验**（t-test / Wilcoxon / Bootstrap）。每次改动都有基线对比，好不好用数字说话。

</td>
  </tr>
  <tr>
    <td>

**🔒 企业级安全**

文档级 ACL（owner / 成员 / 团队 / 继承）+ 检索侧权限裁剪，杜绝引用越权；RBAC + SCIM/SSO + SAML 单点登录；中文场景 PII 脱敏、InputGuard/OutputGuard、SSRF 逐跳校验。
→ [使用指南](./docs/guides/document_acl.md)

</td>
    <td>

**📑 文档版本管理**

同一文档在不同 pipeline 配置下形成独立版本（`pipeline_hash`），支持查看、激活回滚、删除历史，UI 中直接切换预览——调参不怕改坏，随时回到上一版。
→ [使用指南](./docs/guides/document_versions.md)

</td>
  </tr>
  <tr>
    <td>

**🔗 URL 导入与连接器**

后端拉取远程 URL 入库，批量导入带状态 / 统计 / 错误归因（Connector Run）。内置 SSRF 防护与安全开关，公网抓取也放心。
→ [使用指南](./docs/guides/url_ingest.md)

</td>
    <td>

**🏢 生产级架构**

Milvus 十亿级向量、PostgreSQL 持久化、arq 异步任务队列、OpenAI 兼容接口。Docker Compose / Helm / K8s 多形态部署，CI/CD + Prometheus + Grafana 开箱可观测。

</td>
  </tr>
  <tr>
    <td>

**🔌 Dify 生态集成**

提供 Dify External Knowledge API 兼容接口，作为外部知识库直接挂到 Dify 工作流。已有 Dify 应用零改造，即可用上 MimirQ 的混合检索、KG 与引用溯源。
→ [使用指南](./docs/guides/pipeline_plugins.md)

</td>
    <td>

**🏛️ 政务 / 垂直场景就绪**

面向政务、金融等严肃场景，内置就绪度门禁（readiness gate）、证据审计（evidence audit）、行业规则库与离线脱敏，已在市级政务问答助手落地验证。

</td>
  </tr>
</table>

---

## 📈 项目规模

不是玩具项目——这是一套认真做工程的全栈系统：

| 维度 | 规模 |
|:---|:---|
| **后端代码** | ~30 万行自研 Python（不含 vendored 解析器） |
| **前端代码** | ~20 万行 TypeScript / React |
| **文档解析后端** | 30+ 种（PDF / OCR / 版式 / 视觉） |
| **切块策略** | 78 种（递归 / 语义 / 分层 / 父子 / RAPTOR / Late Chunking …） |
| **重排序器** | 15 种（RRF / ColBERT / LTR / LLM-based / long-context …） |
| **测试** | 106 个后端测试文件，后端 576 用例 + 前端 61 用例 + CI 契约门禁 |

---

## 🔎 系统架构

<div align="center">
  <img src="./docs/images/architecture.svg" alt="MimirQ Architecture" width="100%"/>
</div>

---

## 🔄 RAG Pipeline

<div align="center">
  <img src="./docs/images/rag-pipeline.svg" alt="RAG Pipeline" width="100%"/>
</div>

<details>
<summary><b>流程详解</b></summary>

### 入库流程（Ingestion）

```
文档上传 → 格式解析 (PyMuPDF/MinerU/ETL4LLM/…) → 智能切块 (递归/语义/父子)
→ 向量化 (OpenAI/Ollama/本地模型) → 多路索引 (Milvus + BM25，可选 SPLADE)
→ [可选] 知识图谱抽取 (实体/关系/事件)
```

### 问答流程（Retrieval & Generation）

```
用户提问 → Query 向量化 → 混合检索 Top-K (Vector + BM25，可选 SPLADE)
→ 融合重排 (RRF，可选 ColBERT/LTR) → 权限裁剪 (Security Trimming)
→ 上下文构建 → LLM 生成 → 流式回答 + 逐句引用溯源 + 检索 Trace
```

> 💡 SPLADE / ColBERT / LTR / HyDE / 多查询改写等进阶通道**默认关闭**，需要时在配置里显式开启——保证开箱即用路径的延迟与成本可控，进阶能力随取随用。

</details>

---

## 🛠 技术栈

<div align="center">
  <img src="./docs/images/tech-stack.svg" alt="Tech Stack" width="100%"/>
</div>

<br/>

| 层级 | 技术 |
|:---:|:---|
| **前端** | Next.js 14 (App Router) · React 19 · TypeScript · Tailwind CSS · shadcn/ui · Zustand · TanStack Query · Radix UI · Recharts · react-force-graph |
| **后端** | FastAPI · Python 3.11+ · LangChain 1.x · LangGraph · SQLAlchemy · Alembic · arq Worker · RAGAS |
| **检索** | Milvus (默认) / FAISS / Chroma · BM25 · SPLADE · ColBERT · LTR · RRF Fusion |
| **解析** | PyMuPDF · MinerU · ETL4LLM · Marker · Docling · PaddleOCR-VL · olmOCR · Qianfan-OCR |
| **存储** | PostgreSQL 15 · Redis 7 · MinIO · etcd |
| **部署** | Docker Compose · Helm / K8s · Prometheus · Grafana · GitHub Actions CI |

---

## 🚀 快速开始

### 前置要求

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- 至少 4 核 CPU / 16 GB RAM / 50 GB 磁盘

### 一键启动

```bash
git clone https://github.com/skygazer42/MimirQ.git
cd MimirQ

# 1. 生成本地配置文件，并自动创建 JWT SECRET_KEY
make init
# Windows 无 make 可用：python scripts/init_env.py

# 2. 启动后端 + 基础设施（Postgres / Milvus / MinIO / Redis）
make up

# 3. [可选] 启动前端（Next.js 生产构建）
make up-web
```

> 想先轻量体验？`make up-lite` 用 Chroma/FAISS 替代 Milvus、免 MinIO，几分钟跑起来。

Docker 首次构建会下载并校验固定版本的 DeepDoc 模型包；本地源码运行解析器前执行 `make models`。

### 验证服务

```bash
# 检查服务状态
make ps

# 健康检查
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/ready
```

启动后访问：

| 服务 | 地址 |
|:---:|:---|
| **前端 UI** | [http://localhost:3000](http://localhost:3000) |
| **API 文档** | [http://localhost:8000/docs](http://localhost:8000/docs) |
| **健康检查** | [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health) |

> 如需从源码部署或本地开发，请参考 [开发文档](./docs/quickstart.md)

---

## 📡 API 参考（OpenAPI / GitHub Pages）

| 资源 | 链接 / 说明 |
|:---|:---|
| **在线交互文档（GitHub Pages）** | [https://skygazer42.github.io/MimirQ/](https://skygazer42.github.io/MimirQ/)（Redoc，全量 `openapi.json`；fork 后请改为 `https://<owner>.github.io/<repo>/`） |
| **仓库内导读** | [docs/api/README.md](./docs/api/README.md)（认证、Base path、**全量 Tag 对照表**） |
| **场景化调用顺序** | [docs/api/workflows.md](./docs/api/workflows.md) |
| **本地 Swagger** | 后端启动后 [http://localhost:8000/docs](http://localhost:8000/docs) |
| **导出 OpenAPI** | `make openapi-export` → `web/openapi.json` |
| **构建静态站（与 CI 一致）** | `make api-docs-build` → `docs/api/site/` |

> 认证约定：后端无全局认证中间件，**每个路由必须显式依赖 `get_current_account_id`**；访问租户数据时再同时依赖 `get_tenant_id`。详见 [backend_structure.md](./docs/backend_structure.md#添加新-api-路由)。

首次启用 Pages：仓库 **Settings → Pages → Source: GitHub Actions**，推送 `main` 后由 [`.github/workflows/api-docs.yml`](./.github/workflows/api-docs.yml) 部署。

---

## 📦 部署方式

从本地体验到生产集群，覆盖各种场景：

| 方式 | 命令 | 说明 |
|:---:|:---|:---|
| **标准部署** | `make up` | 完整栈：Postgres + Milvus + MinIO + Redis + API + Worker |
| **标准 + 前端** | `make up-web` | 标准部署 + Next.js 前端 |
| **轻量模式** | `make up-lite` | Chroma/FAISS 替代 Milvus，无需 MinIO，适合快速体验 |
| **开发模式** | `make up-infra` | 仅基础设施，后端/前端本地运行 |
| **Helm / K8s** | `helm install` | 生产级部署，含 HPA、PDB、CronJob、PrometheusRule |
| **解析器扩展** | `make up-etl4llm` | 启用 ETL4LLM / Marker / MinerU / PaddleOCR-VL / Qianfan-OCR 等解析器 |

<details>
<summary><b>生产部署建议</b></summary>

```bash
# 编辑 docker/.env 设置生产参数
# ENV=production
# AUTH_MODE=jwt
# SECRET_KEY=<至少 32 位随机字符串>
# POSTGRES_PASSWORD=<强密码>

make up
```

Kubernetes 生产部署请参考 [Helm 部署文档](./docs/deployment/helm.md) 和 [运维手册](./docs/deployment/runbook.md)。

</details>

---

## 📖 功能指南

| 指南 | 说明 |
|:---|:---|
| [切片预览](./docs/guides/chunk_preview.md) | 可视化文档分块效果与参数调整 |
| [知识图谱](./docs/guides/knowledge_graph.md) | KG 抽取、可视化与 RAG 增强 |
| [文档 ACL](./docs/guides/document_acl.md) | 文档级访问控制与 Security Trimming |
| [URL 导入](./docs/guides/url_ingest.md) | 远程 URL 抓取与批量导入 |
| [文档版本](./docs/guides/document_versions.md) | Pipeline 版本管理与回滚 |
| [稀疏检索](./docs/guides/sparse_retrieval.md) | SPLADE 稀疏检索通道 |
| [ColBERT 重排](./docs/guides/reranking_colbert.md) | ColBERT 晚交互重排序 |
| [RAG 优化](./docs/guides/rag_optimization.md) | 检索效果与回答质量优化 |
| [检索排障](./docs/guides/retrieval_debugging.md) | 检索问题诊断 |
| [SAML SSO](./docs/guides/saml_sso.md) | SAML 单点登录集成 |
| [API 参考导读](./docs/api/README.md) | OpenAPI Tag 全表、GitHub Pages、静态站构建 |
| [API 场景流程](./docs/api/workflows.md) | 认证 / 入库 / 检索 / 对话等端点顺序 |
| [API 文档（教程）](./docs/API.md) | 快速入门与示例代码 |
| [快速开始](./docs/quickstart.md) | 从源码开发部署 |
| [运维手册](./docs/deployment/runbook.md) | 生产运维与排障 |

---

## ✅ 开发自检

提交前建议运行一键自检（后端 + 前端），与 CI 保持一致：

```bash
# 完整自检（后端 lint/test + 前端 lint/test）
make enterprise-checks

# 仅后端
make verify && make test

# 仅前端
cd web && pnpm lint && pnpm test
```

---

## 🗺 Roadmap

**已交付：**

- [x] 混合检索（Vector + BM25，可选 SPLADE / ColBERT / LTR）
- [x] 可视化切片预览（多策略并排 + 边界打分）
- [x] 知识图谱（抽取 + 可视化 + 搜索 + 快照 Diff 影响分析）
- [x] 评测治理（RAGAS + 回归门禁 + 统计显著性检验）
- [x] 文档级 ACL（Security Trimming）
- [x] 文档版本管理（Pipeline Versions）
- [x] URL 连接器与批量导入
- [x] 自纠正 Agent 流水线（Self-RAG / CRAG / FLARE）
- [x] 中文 PII 脱敏与安全护栏

**规划中：**

- [ ] 可视化 RAG 工作流编辑器
- [ ] 更多数据源连接器（Confluence / S3 / Notion）
- [ ] 跨语言检索
- [ ] 统一 LLM-as-Judge（G-Eval + Self-Consistency）

> Roadmap 通过 [GitHub Issues](https://github.com/skygazer42/MimirQ/issues) 公开跟踪，欢迎提需求 / 投票。

---

## 🤝 参与贡献

无论是修一个 typo、报一个 bug，还是提一个新特性，我们都欢迎！请参阅 [CONTRIBUTING.md](./.github/CONTRIBUTING.md)。

```bash
# Fork 后克隆
git clone https://github.com/<your-username>/MimirQ.git
cd MimirQ
make init

# 本地开发
make up-infra          # 启动基础设施
make models            # 下载并校验固定版本的 DeepDoc 模型
cd web && pnpm dev     # 前端开发
python main.py         # 后端开发

# 提交前自检
make enterprise-checks
```

---

## 📜 许可证

本项目采用 [Apache License 2.0](LICENSE)。第三方组件（含 vendored 自 RAGFlow/DeepDoc 的代码及构建时下载的模型权重）的归属声明见 [NOTICE](NOTICE)。

> ⚠️ **注意 PyMuPDF (AGPL-3.0)**：默认 PDF 解析可能使用 PyMuPDF，其协议为 AGPL-3.0 / 商业双授权。若你以 SaaS 形式对外提供服务，AGPL 的网络条款可能要求公开整个组合作品的源码。如需规避，请改用宽松协议的解析后端（pypdf / pdfplumber）。详见 NOTICE。

---

## 🙏 致谢

MimirQ 构建于优秀的开源生态之上，感谢以下项目：

[FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

---

<div align="center">

**如果 MimirQ 帮你把 RAG 从"能跑"做到了"敢上生产"，请给我们一个 ⭐ Star！**

每一个 Star 都是我们把黑盒继续打开的动力。

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
