<div align="center">

<img src="./images/logo.png" alt="MimirQ" width="600" />

<p>
  <a href="https://github.com/skygazer42/MimirQ/wiki"><b>文档</b></a> ·
  <a href="#快速开始"><b>快速开始</b></a> ·
  <a href="https://github.com/skygazer42/MimirQ/issues"><b>反馈</b></a>
</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 14](https://img.shields.io/badge/Next.js-14-black)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688.svg)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-0.3-green)](https://langchain.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![Milvus](https://img.shields.io/badge/Milvus-2.3-00a1e0)](https://milvus.io/)

[![GitHub stars](https://img.shields.io/github/stars/skygazer42/MimirQ?color=yellow)](https://github.com/skygazer42/MimirQ)
[![GitHub issues](https://img.shields.io/github/issues/skygazer42/MimirQ)](https://github.com/skygazer42/MimirQ/issues)

[![README in English](https://img.shields.io/badge/English-d9d9d9)](./README_EN.md)
[![简体中文文档](https://img.shields.io/badge/简体中文-d9d9d9)](./README.md)

</div>

MimirQ 是一个开源的 RAG 知识库问答平台。它将可视化切片预览、混合检索、多模态解析、评测框架等功能整合在一起，帮助你快速构建企业级知识库应用。

## 快速开始

> 开始前请确保机器满足最低要求：
> - CPU >= 2 核
> - RAM >= 4 GB

启动 MimirQ 最简单的方式是使用 [Docker Compose](docker/docker-compose.yml)。运行前请确保已安装 [Docker](https://docs.docker.com/get-docker/) 和 [Docker Compose](https://docs.docker.com/compose/install/)：

```bash
git clone https://github.com/skygazer42/MimirQ.git
cd MimirQ/docker
cp .env.example .env
docker compose up -d
```

启动后访问 [http://localhost:8000/docs](http://localhost:8000/docs) 查看 API 文档，或启动前端访问 [http://localhost:3000](http://localhost:3000)。

> 如需从源码部署或本地开发，请参考 [开发文档](./docs/quickstart.md)

## 核心功能

**1. 可视化切片预览**
实时预览文档分块效果，告别黑盒处理，精确调整切片参数。

**2. 混合检索**
向量检索 + BM25 关键词检索双引擎，RRF 算法融合排序，兼顾语义理解和精确匹配。

**3. 多模态解析**
支持 PDF、Markdown、TXT 等格式，集成 PyMuPDF、MinerU、ETL4LLM 等多种解析后端。

**4. RAG 智能问答**
流式响应、引用溯源、多轮对话记忆，基于 LangChain Runnable/Retriever 架构。

**5. RAGAS 评测**
内置评测框架，支持 Faithfulness、Relevancy、Context Precision 等指标。

**6. 企业级架构**
Milvus 十亿级向量检索、PostgreSQL 持久化、OpenAI 兼容接口、Docker 一键部署。

## 高级配置

如需自定义配置，请参考 [.env.example](docker/.env.example) 中的注释修改 `.env` 文件。完整环境变量说明见 [配置文档](./docs/guides/dependencies.md)。


## 许可证

本项目采用 [MIT 许可证](LICENSE)。
