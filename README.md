<div align="center">

<img src="./images/logo.png" alt="MimirQ" width="100%"/>

<h3>开源 RAG 知识库问答平台</h3>

<p>深度文档理解 · 混合检索 · 知识图谱 · 可视化切片 · 企业级安全</p>

<p>
  <a href="https://github.com/skygazer42/MimirQ/wiki"><b>文档</b></a> ·
  <a href="https://skygazer42.github.io/MimirQ/"><b>在线 API</b></a> ·
  <a href="./docs/api/README.md"><b>API 导读</b></a> ·
  <a href="#-快速开始"><b>快速开始</b></a> ·
  <a href="https://github.com/skygazer42/MimirQ/issues"><b>反馈</b></a> ·
  <a href="./CHANGELOG.md"><b>更新日志</b></a> ·
  <a href="./CONTRIBUTING.md"><b>参与贡献</b></a>
</p>

<p>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"/></a>
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

## 📑 目录

- [什么是 MimirQ？](#-什么是-mimirq)
- [核心特性](#-核心特性)
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

## 💡 什么是 MimirQ？

**MimirQ**（名字源自北欧神话中掌管智慧之泉的巨人 **Mímir**）是一个全栈开源 RAG 知识库问答平台。它将**深度文档理解**、**混合检索**、**知识图谱**、**可视化切片**、**评测框架**等能力整合为一体，帮助你快速构建**企业级**知识库应用。

与传统 RAG 方案不同，MimirQ 在以下方面做了深度优化：

- **检索质量**：三路混合检索（Vector + BM25 + SPLADE），RRF 融合排序 + ColBERT/LTR 重排，确保语义理解与精确匹配兼顾
- **可观测性**：可视化切片预览、RAG 检索 Trace、评测 Leaderboard，全链路透明可调
- **安全合规**：文档级 ACL 权限裁剪、RBAC、SCIM/SSO 集成，满足企业级数据隔离需求
- **可扩展性**：Milvus 十亿级向量、Helm/K8s 生产部署、Prometheus/Grafana 可观测

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

三路检索融合：Vector 语义检索 + BM25 关键词检索 + SPLADE 稀疏检索。RRF 融合排序、ColBERT 晚交互重排、LTR 学习排序，兼顾召回率与精准度。

</td>
    <td width="50%">

**📄 可视化切片预览**

实时预览文档分块效果，告别黑盒处理。支持多种切块策略（递归/语义），精确调整参数，所见即所得。
→ [使用指南](./docs/guides/chunk_preview.md)

</td>
  </tr>
  <tr>
    <td>

**🔄 多模态文档解析**

支持 PDF、Markdown、HTML、TXT 等格式。集成 PyMuPDF、MinerU、ETL4LLM、Marker、PaddleOCR-VL、olmOCR、Qianfan-OCR 等多种解析后端，可按需扩展。

</td>
    <td>

**💬 RAG 智能问答**

流式响应、引用溯源、多轮对话记忆。基于 LangChain Runnable/Retriever 架构，支持 LangGraph Agent 可选流水线。

</td>
  </tr>
  <tr>
    <td>

**🕸️ 知识图谱（KG）**

从文档 chunks 自动抽取事件/实体/关系，支持图谱可视化（Force Graph）、KG 搜索、以及对 RAG 的 query expansion / chunk injection 增强。
→ [使用指南](./docs/guides/knowledge_graph.md)

</td>
    <td>

**📊 RAGAS 评测框架**

内置评测体系，支持 Faithfulness、Relevancy、Context Precision 等指标。回归门禁 + Leaderboard + 检索质量快照，持续保障质量。

</td>
  </tr>
  <tr>
    <td>

**🔒 文档级权限（Security Trimming）**

在数据集权限之上支持文档级访问控制（owner / 指定成员 / 团队成员 / 继承），检索侧权限裁剪避免引用越权。
→ [使用指南](./docs/guides/document_acl.md)

</td>
    <td>

**📑 文档版本管理**

同一文档在不同 pipeline 配置下形成不同版本（`pipeline_hash`），支持查看、激活回滚、删除历史版本，UI 中直接切换预览。
→ [使用指南](./docs/guides/document_versions.md)

</td>
  </tr>
  <tr>
    <td>

**🔗 URL 导入与连接器**

后端拉取远程 URL 入库，支持批量导入（Connector Run 记录状态/统计/错误）。内置 SSRF 防护与安全开关。
→ [使用指南](./docs/guides/url_ingest.md)

</td>
    <td>

**🏢 企业级架构**

Milvus 十亿级向量检索、PostgreSQL 持久化、OpenAI 兼容接口。Docker Compose / Helm / K8s 多种部署方式，CI/CD + Prometheus + Grafana。

</td>
  </tr>
</table>

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
文档上传 → 格式解析 (PyMuPDF/MinerU/ETL4LLM) → 智能切块 (Recursive/Semantic)
→ 向量化 (OpenAI/Ollama/Local) → 多路索引 (Milvus + BM25 + SPLADE)
→ [可选] 知识图谱抽取 (Entity/Relation/Event)
```

### 问答流程（Retrieval & Generation）

```
用户提问 → Query 向量化 → 混合检索 Top-K (Vector + BM25 + SPLADE)
→ 重排序 (RRF + ColBERT/LTR) → 权限裁剪 (Security Trimming)
→ 上下文构建 → LLM 生成 → 流式回答 + 引用溯源
```

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

# 1. 生成本地配置文件（.env / docker/.env / web/.env.local）
make init
# Windows 无 make 可用：python scripts/init_env.py

# 2. 启动后端 + 基础设施（Postgres / Milvus / MinIO / Redis）
make up

# 3. [可选] 启动前端（Next.js 生产构建）
make up-web
```

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
| **API 文档** | [http://localhost:8000/docs](http://localhost:8000/docs) |
| **前端 UI** | [http://localhost:3000](http://localhost:3000) |
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

首次启用 Pages：仓库 **Settings → Pages → Source: GitHub Actions**，推送 `main` 后由 [`.github/workflows/api-docs.yml`](./.github/workflows/api-docs.yml) 部署。建议将 **About → Website** 设为上述 Pages URL。

---

## 📦 部署方式

MimirQ 提供多种部署方式，适应从开发到生产的各种场景：

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

常州政务 Dify 工作流接入前，先对控制台草稿做本地门禁和 dry-run 同步预览：

```bash
# 生成已清洗 workflow JSON（不写远程 Dify）
make changzhou-dify-workflow-lint

# 生成当前草稿备份和将要 POST 的 payload（默认不写远程 Dify）
make changzhou-dify-workflow-sync-dry-run

# 确认 payload 后才显式写入 Dify 草稿
make changzhou-dify-workflow-sync-apply
```

---

## 🗺 Roadmap

- [x] 混合检索（Vector + BM25 + SPLADE）
- [x] 可视化切片预览
- [x] 知识图谱（KG 抽取 + 可视化 + 搜索）
- [x] RAGAS 评测框架与回归门禁
- [x] 文档级 ACL（Security Trimming）
- [x] 文档版本管理（Pipeline Versions）
- [x] URL 连接器与批量导入
- [x] ColBERT / LTR 重排序
- [x] Evidence Capsule 溯源
- [ ] Agent 工作流编排
- [ ] 多语言跨语言检索
- [ ] 更多数据源连接器（Confluence / S3 / Notion）
- [ ] 可视化 RAG 工作流编辑器

> 完整 Roadmap 请参考 [docs/plans/](./docs/plans/)

---

## 🤝 参与贡献

我们欢迎任何形式的贡献！请参阅 [CONTRIBUTING.md](./CONTRIBUTING.md) 了解详情。

```bash
# Fork 后克隆
git clone https://github.com/<your-username>/MimirQ.git
cd MimirQ
make init

# 本地开发
make up-infra          # 启动基础设施
cd web && pnpm dev     # 前端开发
python main.py         # 后端开发

# 提交前自检
make enterprise-checks
```

---

## 📜 许可证

本项目采用 [MIT 许可证](LICENSE) — 自由使用、修改和分发。

---

## 🙏 致谢

MimirQ 构建于优秀的开源生态之上，感谢以下项目：

[FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

---

<div align="center">

**如果 MimirQ 对你有帮助，请给我们一个 ⭐ Star！**

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
