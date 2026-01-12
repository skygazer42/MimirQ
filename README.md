<div align="center">

<img src="./docs/images/cover.png" alt="MimirQ" width="100%" />

<p>
  <a href="https://github.com/YOUR_USERNAME/MimirQ/wiki"><b>文档</b></a> ·
  <a href="#快速开始"><b>快速开始</b></a> ·
  <a href="https://github.com/YOUR_USERNAME/MimirQ/issues"><b>反馈</b></a>
</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker Pulls](https://img.shields.io/docker/pulls/YOUR_USERNAME/mimirq?color=blue)](https://hub.docker.com/r/YOUR_USERNAME/mimirq)
[![GitHub stars](https://img.shields.io/github/stars/YOUR_USERNAME/MimirQ?color=yellow)](https://github.com/YOUR_USERNAME/MimirQ)
[![GitHub issues](https://img.shields.io/github/issues/YOUR_USERNAME/MimirQ)](https://github.com/YOUR_USERNAME/MimirQ/issues)

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
git clone https://github.com/YOUR_USERNAME/MimirQ.git
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

## 使用方式

- **Self-hosting**
  使用 [快速开始](#快速开始) 指南在本地部署，详细配置参考 [文档](./docs/quickstart.md)。

- **企业版**
  如需企业级功能支持，请 [联系我们](mailto:support@mimirq.com)。

## 高级配置

如需自定义配置，请参考 [.env.example](docker/.env.example) 中的注释修改 `.env` 文件。完整环境变量说明见 [配置文档](./docs/guides/dependencies.md)。

### Kubernetes 部署

```bash
helm install mimirq ./k8s/helm/mimirq
# 或
kubectl apply -f k8s/manifests/
```

## 贡献

欢迎参与贡献！请查看 [贡献指南](CONTRIBUTING.md)。

> 我们正在寻找翻译贡献者，如有兴趣请在 [Discord](https://discord.gg/YOUR_INVITE) 联系我们。

## 社区

- [GitHub Discussions](https://github.com/YOUR_USERNAME/MimirQ/discussions) - 分享反馈和提问
- [GitHub Issues](https://github.com/YOUR_USERNAME/MimirQ/issues) - Bug 报告和功能建议
- [Discord](https://discord.gg/YOUR_INVITE) - 交流讨论

**贡献者**

<a href="https://github.com/YOUR_USERNAME/MimirQ/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=YOUR_USERNAME/MimirQ" />
</a>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=YOUR_USERNAME/MimirQ&type=Date)](https://star-history.com/#YOUR_USERNAME/MimirQ&Date)

## 许可证

本项目采用 [MIT 许可证](LICENSE)。
