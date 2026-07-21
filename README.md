<div align="center">

<img src="./docs/images/banner.svg" alt="MimirQ：可检查、可回归、可治理的开源 RAG 知识库" width="100%"/>

<p><b>全栈开源、中文优先的企业 RAG 知识库</b><br/>从文档怎么被切，到检索命中什么、答案凭什么生成，整条链路都可查看、可调试、可回归。</p>

<p>
  <a href="#-快速开始"><b>快速开始</b></a> ·
  <a href="#-产品界面"><b>产品界面</b></a> ·
  <a href="#-接入-dify"><b>Dify 接入</b></a> ·
  <a href="#-已在真实场景验证"><b>800 题实测</b></a> ·
  <a href="https://skygazer42.github.io/MimirQ/"><b>API 文档</b></a>
</p>

<p>
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License: Apache 2.0"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"/></a>
  <img src="https://img.shields.io/badge/Dify-External_Knowledge_%2B_HTTP-1C64F2" alt="Dify External Knowledge and HTTP integration"/>
  <img src="https://img.shields.io/badge/Benchmark-800_questions-0F766E" alt="800-question benchmark"/>
</p>

<p>
  <a href="./README.md"><img src="https://img.shields.io/badge/简体中文-d9d9d9" alt="简体中文"/></a>
  <a href="./README_EN.md"><img src="https://img.shields.io/badge/English-d9d9d9" alt="English"/></a>
</p>

</div>

---

## 💡 MimirQ 是什么

**MimirQ** 是一个专注 RAG 全链路可观测性的知识库问答平台，前后端全开源，可通过 Docker Compose 或 Helm 部署。

<table>
  <tr>
    <td align="center" width="25%"><strong>30+</strong><br/><sub>文档解析后端</sub></td>
    <td align="center" width="25%"><strong>78</strong><br/><sub>切块策略</sub></td>
    <td align="center" width="25%"><strong>15</strong><br/><sub>重排器</sub></td>
    <td align="center" width="25%"><strong>800</strong><br/><sub>固定题集实测</sub></td>
  </tr>
</table>

<table>
  <tr>
    <td width="50%"><strong>看得见</strong><br/><sub>解析结果、切块边界、检索与重排过程</sub></td>
    <td width="50%"><strong>追得回</strong><br/><sub>逐句引用、版本、证据与完整 Trace</sub></td>
  </tr>
  <tr>
    <td><strong>守得住</strong><br/><sub>文档 ACL、RBAC、脱敏、审计与安全护栏</sub></td>
    <td><strong>能回归</strong><br/><sub>Golden 题集、评测看板与发布门禁</sub></td>
  </tr>
</table>

<details>
<summary><b>为什么做 MimirQ？</b></summary>

MimirQ 起源于一个政务智能问答项目：系统已经能回答问题，但答错时很难判断根因在解析、切块、召回、重排还是生成。政务知识又存在多地区版本、政策更新、扫描件和表格，一个通顺但引用旧政策的答案，比直接说不知道更危险。

现成平台擅长工作流或 Agent，但 RAG 排障所需的解析、索引、检索、引用和评测往往散落在不同组件。MimirQ 不再造通用节点画布，而是把重点放在可检查的 RAG 链路。

> **MimirQ 想解决的不是“RAG 能不能跑”，而是“这套 RAG 为什么值得被相信”。**

</details>

---

## 🚀 快速开始

### 前置要求

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- GNU Make 与 Python 3.9+（仅用于幂等生成本地配置和随机密钥）
- 至少 4 核 CPU / 16 GB RAM / 50 GB 磁盘

### 最小启动

```bash
git clone https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

`make init` 会生成完整 `.env` 和随机 JWT `SECRET_KEY`。`.env` 是高级配置参考，不是需要逐项填写的表单；默认硅基流动配置只需填写这一项：

```dotenv
# 唯一必填
LLM_API_KEY=<your-siliconflow-api-key>
```

然后启动：

```bash
make up-web
```

`make up-web` 会启动前端、后端、Worker、Postgres、Milvus、MinIO 与 Redis；已有配置不会被覆盖。打开 [http://localhost:3000](http://localhost:3000) 后创建本地账户即可进入系统。

> 想先轻量体验？`make up-lite` 用 Chroma/FAISS 替代 Milvus、免 MinIO。外部 LLM/Embedding 调用仍需配置你自己的模型供应商密钥；项目不会内置或提交密钥。

高级模型、解析器和代理配置见 [`.env.example`](./.env.example)。更换 Embedding 模型后必须重建已有知识库索引；常州政务公开演示数据和测试命令见[插件说明](./plugins/pipelines/changzhou-gov-service-knowledge/README.md)。

### 验证服务

```bash
make ps
curl http://localhost:8000/api/v1/health/ready
```

| 服务 | 地址 |
|:---:|:---|
| **前端 UI** | [http://localhost:3000](http://localhost:3000) |
| **API 文档** | [http://localhost:8000/docs](http://localhost:8000/docs) |

> 如需从源码部署或本地开发，请参考[开发文档](./docs/quickstart.md)。

---

## 🖼️ 产品界面

以下界面使用仓库内公开的政务插件演示样例生成，不含生产知识库数据。

<table>
  <tr>
    <td colspan="2" align="center">
      <img src="./docs/images/screenshots/knowledge-graph.png" alt="MimirQ 知识图谱界面" width="100%"/>
      <br/><strong>知识图谱</strong>
      <br/><sub>在同一画布中检索和分析实体、事件与关系。</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/dataset-management.png" alt="MimirQ 知识库管理界面" width="100%"/>
      <br/><strong>知识库管理</strong>
      <br/><sub>集中查看数据集、文档、Chunk 与入库状态。</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/rag-evaluation.png" alt="MimirQ Golden 回归评测界面" width="100%"/>
      <br/><strong>Golden 回归评测</strong>
      <br/><sub>标准问答、运行记录与 Recall / MRR 等指标同屏可查。</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/settings.png" alt="MimirQ 系统设置界面" width="100%"/>
      <br/><strong>系统设置</strong>
      <br/><sub>集中查看依赖状态、解析能力以及模型服务接入。</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/chat-history.png" alt="MimirQ 问答历史与证据回看界面" width="100%"/>
      <br/><strong>问答历史与证据回看</strong>
      <br/><sub>检索历史会话，并回看完整回答、来源与反馈入口。</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/ingestion-monitor.png" alt="MimirQ 入库执行监控界面" width="100%"/>
      <br/><strong>入库执行监控</strong>
      <br/><sub>按数据集观察解析、切块、治理、导出和失败重试状态。</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/data-governance.png" alt="MimirQ 数据治理工作台" width="100%"/>
      <br/><strong>数据治理</strong>
      <br/><sub>在同一工作台完成文档预览、质量检测、清洗与标注。</sub>
    </td>
  </tr>
</table>

---

## 🔌 接入 Dify

MimirQ 不重复实现 Dify 的工作流画布，而是把可治理、可追溯的 RAG 能力接入已有 Dify 应用。当前支持两种方式：

| 接入方式 | Dify 负责 | MimirQ 负责 | 适用场景 |
|:---|:---|:---|:---|
| **External Knowledge API** | Chatflow / Agent 编排、Prompt 与答案生成 | 文档治理、混合检索、重排、权限过滤与证据返回 | 把 MimirQ 当作 Dify 外部知识库 |
| **Workflow HTTP 节点** | 自定义路由、参数组装与答案展示 | 按指定知识范围返回检索证据和 Trace | 需要多分支、动态知识库或自定义回传逻辑 |

#### External Knowledge API

<p align="center">
  <a href="./docs/images/screenshots/dify-mimirq-workflow.png">
    <img src="./docs/images/screenshots/dify-mimirq-workflow.png" alt="Dify 工作流通过区域路由接入八个 MimirQ 政务知识库" width="750"/>
  </a>
  <br/>
  <sub>真实 Dify Chatflow（已脱敏）：区域分支路由到 7 个区域级 + 1 个市级 MimirQ 知识检索节点，再统一合并证据。</sub>
</p>

#### Workflow HTTP 节点

<p align="center">
  <a href="./docs/images/screenshots/dify-mimirq-http-workflow.png">
    <img src="./docs/images/screenshots/dify-mimirq-http-workflow.png" alt="Dify HTTP 节点调用 MimirQ 检索接口并合并证据" width="1100"/>
  </a>
  <br/>
  <sub>真实 Dify HTTP 子链（已脱敏）：安全构造 JSON 请求 → POST MimirQ 检索接口 → 转换 Dify 结果 → 合并知识证据。</sub>
</p>

Dify 标准外部知识库端点为 `POST /api/v1/integrations/dify/retrieval`；可选用 `POST /api/v1/integrations/dify/conversation-turns` 回传答案、引用与会话标识。配置见 [`.env.example`](./.env.example)，部署前校验见 [readiness gate](./scripts/README.md)，实测结果见[真实场景验证](#-已在真实场景验证)。

---

## 🧭 核心功能对比

<details>
<summary><b>展开查看与 Dify、RAGFlow、FastGPT、AnythingLLM 和 LangChain 的功能对比</b></summary>


| 功能维度 | **MimirQ** | [Dify](https://github.com/langgenius/dify) | [RAGFlow](https://github.com/infiniflow/ragflow) | [FastGPT](https://github.com/labring/FastGPT) | [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | [LangChain](https://github.com/langchain-ai/langchain) |
|:---|:---|:---|:---|:---|:---|:---|
| **文档解析** | **30+ 解析后端**：PDF、OCR、版式、表格、公式、VLM | Knowledge Pipeline；PDF、PPT 等常见格式 | **DeepDoc**；复杂版式、扫描件、MinerU / Docling | PDF、扫描件、表格、公式转 Markdown | PDF、TXT、DOCX 等文档管道 | Document Loaders 与第三方解析器集成 |
| **切块能力** | **78 种策略**：递归、语义、父子、RAPTOR、Late Chunking；可视化预览 | 通用、父子、Q&A 与可编排处理 | 模板化切块；支持可视化人工干预 | 自动、手工、Q&A 与增强处理 | 文档管道自动分块 | Text Splitters；由应用代码组合 |
| **检索 / 重排** | Milvus / FAISS / Chroma + BM25 / SPLADE / ColBERT / LTR / RRF；**15 种重排器** | 语义、全文、混合检索；可配置 rerank | 多路召回 + 融合重排 | 语义、全文、混合检索 + RRF + rerank | 多种向量库检索 + 来源引用 | Retriever / reranker 组件；自行编排 |
| **知识图谱** | 实体、关系、事件抽取；实体消解、社区发现与多跳检索 | 通过工作流、插件或外部服务接入 | 内建 GraphRAG | 通过工作流或外部服务接入 | 通过 Agent / Tool 外接 | 图数据库集成与自定义链路 |
| **Agent / MCP** | LangGraph Agent、Self-RAG / CRAG / FLARE；MCP client / server | Function Calling / ReAct Agent、工具与 MCP | Agentic Workflow、MCP、代码执行器 | Agent V2、工具、MCP 与 VM 执行 | No-code Agent Builder、MCP、定时任务 | Agents / LangGraph / MCP；代码优先 |
| **可视化工作流** | **无通用节点画布**；专注 RAG 调试、治理页面与 API | **核心能力**：应用 / Agent 节点编排 | Agent 与入库 Pipeline 编排 | **核心能力**：Flow 节点编排 | No-code Agent Builder | 无内建产品 UI；由应用实现 |
| **评测 / 治理闭环** | RAGAS、回归门禁、Leaderboard、显著性检验、证据审计 | 运行日志、观测与人工标注 | 检索测试、切块检查与引用追溯 | 运行详情、检索调试与日志 | 来源引用；无内建 RAG 回归门禁 | 需另接 LangSmith 或自建评测 |
| **安全 Guard** | InputGuard / OutputGuard、PII / Secret 脱敏、SSRF 逐跳校验 | 内容审查节点与工作流规则 | 代码执行沙箱；业务 Guard 需配置 | 工作流内容审查与 VM 沙箱 | Local-first、Agent 工具权限 | 由应用中间件与部署边界实现 |
| **企业权限 / 合规** | 文档 ACL + Security Trimming、RBAC、SCIM / SSO / SAML、审计 | Workspace 权限；企业版组织与 SSO | 账号与 API 鉴权；细粒度合规需按部署建设 | ABAC + RBAC；团队、群组与资源权限 | Docker 版多用户与权限控制 | 框架本身不提供；由应用实现 |
| **RAG 调试可视化** | 切块预览、检索 Trace、重排过程、逐句引用、KG、评测看板 | Dataset 测试、Workflow Trace 与应用日志 | 切块可视化、命中片段与引用 | 知识库测试、Workflow 运行详情 | Workspace、来源引用与聊天 UI | 无内建 UI；可另接观测平台 |
| **Dify 外部知识库** | **原生兼容 Dify External Knowledge API** | 原生消费外部知识库 | 需通过 API 适配 | 需通过 API 适配 | 需通过 API 适配 | 自行实现适配器 |
| **开箱方式** | Docker Compose / Helm；完整企业 RAG 栈 | Docker Compose / Cloud | Docker Compose；官方建议 4C / 16 GB / 50 GB | Docker / Cloud | Desktop / Docker | Python / JS 库；需自行组装应用 |

> 对比基于各项目公开版本与官方文档（2026-07），描述的是**仓库直接提供的能力表面**，不是统一 benchmark。插件、商业版和后续版本可能改变结果。

</details>

---

## 📍 已在真实场景验证

MimirQ 已用于**市级政务智能问答助手**，覆盖 7 个区域级 + 1 个市级知识库。2026-07-21 使用同一套固定 800 题，复测四种实际接入链路：

<!-- 数据来源：artifacts/changzhou_dify_4way_800_20260721/comparison_report.json；输入 SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2；生成时间 2026-07-21T04:56:03Z。 -->

| 链路 | 成功执行 | 准确率 / 可用率 | 答案条款覆盖 | 答案受证据支持 | 错误证据率 | 平均 / P50 / P95 |
|:---|---:|---:|---:|---:|---:|---:|
| **MimirQ 检索直连** | **800 / 800** | **95.9% / 96.9%** | **96.3%** | **96.6%** | 5.4% | 12.10s / 7.47s / 36.05s |
| **Dify External → MimirQ** | 798 / 800 | 60.5% / 88.5% | 81.6% | 93.3% | 7.0% | 11.57s / 7.68s / 40.16s |
| **Dify HTTP → MimirQ** | **800 / 800** | 62.6% / 90.3% | 82.0% | 92.2% | 5.9% | **4.75s / 4.56s / 6.73s** |
| **Dify 原生知识库** | **800 / 800** | 38.9% / 76.8% | 67.3% | 87.1% | 79.1% | 10.61s / 8.52s / 27.65s |

2393 个必答条款中，四路共同未召回的只有 4 个。External 与 HTTP 的主要损失发生在答案生成阶段；Dify 原生知识库还存在地区路由和 Top-K 噪声。检索直连与生成链路的任务不同，延迟也不是严格同条件对比。

[完整方法、指标解释与历史复测](./docs/benchmarks/changzhou_dify.md) · [Dify 接入方式与真实工作流](#-接入-dify)

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
| **标准 + 前端** | `make up-web` | 推荐首次启动；自动初始化本地配置并启动完整 Web 栈 |
| **轻量模式** | `make up-lite` | Chroma/FAISS 替代 Milvus，无需 MinIO，适合快速体验 |
| **开发模式** | `make infra-up` | 仅基础设施，后端/前端本地运行 |
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

已交付能力见上方对比表。近期计划：

- [ ] RAG 专用调试编排（非通用 Agent 画布）
- [ ] 更多数据源连接器（Confluence / S3 / Notion）
- [ ] 跨语言检索
- [ ] 统一 LLM-as-Judge（G-Eval + Self-Consistency）

> Roadmap 通过 [GitHub Issues](https://github.com/skygazer42/MimirQ/issues) 公开跟踪，欢迎提需求 / 投票。

---

## 🤝 参与贡献

修复 typo、报告 bug 或提交功能前，请阅读 [CONTRIBUTING.md](./.github/CONTRIBUTING.md)。本地开发流程见[快速开始](./docs/quickstart.md)，提交前运行 `make enterprise-checks`。

---

## 📜 许可证

本项目采用 [Apache License 2.0](LICENSE)。第三方组件（含 vendored 自 RAGFlow/DeepDoc 的代码及构建时下载的模型权重）的归属声明见 [NOTICE](NOTICE)。

> ⚠️ **注意 PyMuPDF (AGPL-3.0)**：默认 PDF 解析可能使用 PyMuPDF，其协议为 AGPL-3.0 / 商业双授权。若你以 SaaS 形式对外提供服务，AGPL 的网络条款可能要求公开整个组合作品的源码。如需规避，请改用宽松协议的解析后端（pypdf / pdfplumber）。详见 NOTICE。

---

## 🙏 致谢

MimirQ 构建于优秀的开源生态之上，感谢以下项目：

[Dify](https://github.com/langgenius/dify) · [RAGFlow](https://github.com/infiniflow/ragflow) · [FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

感谢[硅基流动](https://siliconflow.cn/)为 MimirQ 的公开联调提供 50 元 API 体验额度支持。

---

<div align="center">

**如果 MimirQ 帮你把 RAG 从"能跑"做到了"敢上生产"，请给我们一个 ⭐ Star！**

每一个 Star 都是我们把黑盒继续打开的动力。

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
