<div align="center">

<img src="./docs/images/cover.png" alt="MimirQ" width="100%" />

<p>
  <a href="https://github.com/YOUR_USERNAME/MimirQ/wiki"><b>文档</b></a> ·
  <a href="#-快速开始"><b>快速开始</b></a> ·
  <a href="https://github.com/YOUR_USERNAME/MimirQ/issues"><b>反馈</b></a>
</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 14](https://img.shields.io/badge/Next.js-14-black)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688.svg)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-0.3-green)](https://langchain.com/)
[![Milvus](https://img.shields.io/badge/Milvus-2.3-00a1e0)](https://milvus.io/)

[![GitHub stars](https://img.shields.io/github/stars/YOUR_USERNAME/MimirQ?color=yellow)](https://github.com/YOUR_USERNAME/MimirQ)
[![Docker Pulls](https://img.shields.io/docker/pulls/YOUR_USERNAME/mimirq?color=blue)](https://hub.docker.com/r/YOUR_USERNAME/mimirq)
[![GitHub issues](https://img.shields.io/github/issues/YOUR_USERNAME/MimirQ)](https://github.com/YOUR_USERNAME/MimirQ/issues)

[![English](https://img.shields.io/badge/English-d9d9d9)](./README_EN.md)
[![简体中文](https://img.shields.io/badge/简体中文-d9d9d9)](./README.md)

</div>

MimirQ 是一个开源的 RAG 知识库问答平台，专注于**可视化**和**可控性**。它将切片预览、混合检索、多模态解析、评测框架整合在一起，让你在构建知识库时不再是"黑盒操作"。

## 为什么选择 MimirQ

| 特性 | MimirQ | 传统方案 |
|------|--------|----------|
| **切片预览** | 实时可视化分块效果 | 黑盒处理，效果靠猜 |
| **检索引擎** | 向量 + BM25 混合检索 | 仅向量，专有名词丢失 |
| **中文支持** | Jieba 分词 + BGE 向量 | 需额外配置 |
| **效果评测** | 内置 RAGAS 评测 | 需自行集成 |
| **部署方式** | Docker 一键启动 | 组件分散，配置繁琐 |

## 🚀 快速开始

> 最低要求：CPU >= 2 核，RAM >= 4 GB

```bash
git clone https://github.com/YOUR_USERNAME/MimirQ.git
cd MimirQ

# 1) 初始化环境变量
cp docker/.env.example docker/.env

# 2) 启动后端 + 依赖（Postgres/Milvus/Redis/MinIO）
docker compose -f docker/docker-compose.yml up -d --build

# 3) （可选）启动前端 UI
docker compose -f docker/docker-compose.yml -f docker/docker-compose.web.yml up -d --build
```

启动后访问：
- API 文档：http://localhost:8000/docs
- 前端界面：http://localhost:3000（需启动 `docker-compose.web.yml`）

> 详细配置和本地开发请参考 [快速入门文档](./docs/quickstart.md)

## 🐳 Docker Compose 部署（类似 Dify）

默认后端栈在 `docker/docker-compose.yml`，前端 UI 在 `docker/docker-compose.web.yml`（按需叠加）。

### 一键启动（后端 + 依赖）

```bash
cp docker/.env.example docker/.env
docker compose -f docker/docker-compose.yml up -d --build
```

### 一键启动（后端 + 依赖 + 前端 UI）

```bash
cp docker/.env.example docker/.env
docker compose -f docker/docker-compose.yml -f docker/docker-compose.web.yml up -d --build
```

### 停止/更新

```bash
# 停止
docker compose -f docker/docker-compose.yml down

# 更新镜像/重建并重启
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml up -d --build
```

## 核心功能

<table>
<tr>
<td width="50%" valign="top">

### 📄 文档处理
- 支持 PDF / Markdown / Office / HTML
- 多解析后端：PyMuPDF、MinerU、ETL4LLM
- **可视化切片预览**，实时调整参数
- 自动分块 + 向量索引

</td>
<td width="50%" valign="top">

### 🔍 智能检索
- 向量检索 + BM25 **混合检索**
- RRF 算法融合排序
- 支持 Rerank 重排序
- 引用溯源（文档 + 页码）

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 💬 RAG 对话
- 流式响应（打字机效果）
- 多轮对话记忆
- LangChain Runnable 架构
- OpenAI 兼容接口

</td>
<td width="50%" valign="top">

### 📊 评测 & 运维
- **内置 RAGAS 评测**
- Faithfulness / Relevancy 指标
- Milvus 十亿级向量支持
- Docker / Kubernetes 部署

</td>
</tr>
</table>

## 🏗️ 技术架构

```
┌────────────────────────────────────────────────────────────┐
│                    Next.js 14 前端                          │
└───────────────────────────┬────────────────────────────────┘
                            │ REST / SSE
┌───────────────────────────▼────────────────────────────────┐
│                    FastAPI 后端                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ 文档解析    │  │ RAG 引擎    │  │ 评测框架    │        │
│  │ PyMuPDF     │  │ LangChain   │  │ RAGAS       │        │
│  │ MinerU      │  │ Retriever   │  │             │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└───────────────────────────┬────────────────────────────────┘
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
   ┌───────────┐     ┌───────────┐      ┌───────────┐
   │ PostgreSQL│     │  Milvus   │      │   Redis   │
   │  对话/文档 │     │ 向量检索  │      │  任务队列 │
   └───────────┘     └───────────┘      └───────────┘
```

## 📖 文档

| 文档 | 说明 |
|------|------|
| [快速入门](./docs/quickstart.md) | 本地开发、Docker 部署 |
| [技术架构](./docs/architecture.md) | 完整架构、环境变量、性能基准 |
| [Milvus 指南](./docs/guides/milvus_guide.md) | 索引优化、GPU 加速 |
| [RAG 优化](./docs/guides/rag_optimization.md) | 检索调优、Rerank |

## 高级部署

<details>
<summary>Kubernetes 部署</summary>

```bash
helm install mimirq ./k8s/helm/mimirq
# 或
kubectl apply -f k8s/manifests/
```

</details>

<details>
<summary>环境变量配置</summary>

```bash
# LLM
LLM_API_KEY=sk-xxx
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo-preview

# Embedding
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5

# RAG
CHUNK_SIZE=1000
RETRIEVAL_TOP_K=5
```

完整配置见 [docker/.env.example](docker/.env.example) 和 [架构文档](./docs/architecture.md)

</details>

## 🤝 贡献

欢迎参与贡献！请查看 [贡献指南](CONTRIBUTING.md)。

## 社区

- [GitHub Discussions](https://github.com/YOUR_USERNAME/MimirQ/discussions) - 问题讨论
- [GitHub Issues](https://github.com/YOUR_USERNAME/MimirQ/issues) - Bug 反馈
- [Discord](https://discord.gg/YOUR_INVITE) - 交流群

## 致谢

MimirQ 基于以下优秀项目构建：[LangChain](https://github.com/langchain-ai/langchain) · [Milvus](https://github.com/milvus-io/milvus) · [FastAPI](https://github.com/tiangolo/fastapi) · [Next.js](https://github.com/vercel/next.js)

同时参考了 [Dify](https://github.com/langgenius/dify)、[RAGFlow](https://github.com/infiniflow/ragflow)、[Bisheng](https://github.com/dataelement/bisheng) 的设计经验。

---

<div align="center">

**贡献者**

<a href="https://github.com/YOUR_USERNAME/MimirQ/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=YOUR_USERNAME/MimirQ" />
</a>

**Star History**

[![Star History Chart](https://api.star-history.com/svg?repos=YOUR_USERNAME/MimirQ&type=Date)](https://star-history.com/#YOUR_USERNAME/MimirQ&Date)

[MIT License](LICENSE)

</div>
