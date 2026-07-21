<div align="center">

<img src="./images/logo.png" alt="MimirQ" width="100%"/>

<h3>企业级知识库</h3>

<p><b>不是又一个黑盒 RAG</b>——从文档怎么被切、检索命中了什么、答案凭什么这么答，每一步都摊开给你看、让你调。</p>

<p>深度文档理解 · 混合检索 · 知识图谱 · 可视化切片 · 评测治理 · Dify 集成 · 企业级安全</p>

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

## 🤔 我为什么做 MimirQ？

MimirQ 最开始不是为了再造一个 RAG 框架，也不是为了把当时流行的模型、Agent 和 GraphRAG 全塞进同一个仓库。它起源于一个很具体的政务智能问答项目：知识库已经建起来，问题也能回答，但只要答案不对，团队就很难说清楚到底错在哪里。是扫描件没有解析完整，是切块把办理条件和例外说明拆开了，是召回漏掉了新版本文件，是重排把真正的依据挤到了后面，还是大模型拿到了证据却没有按证据回答？系统通常只给出最后一句答案，排查只能靠反复改参数、重新入库、再问一次。

这种黑盒在政务知识里尤其麻烦。同一事项可能同时存在市级和区级版本，政策会更新，旧文件会被替代，表格、附件和扫描页里又藏着关键条件。用户问的往往不是文件标题，而是“我这种情况能不能办”“还缺什么材料”“哪个部门负责”。一个看起来通顺但引用了旧政策的答案，比直接回答不知道更危险。真正需要解决的也就不只是“让模型说得更像人”，而是让系统能够回答：原文是否被正确读出来，哪些内容进入了索引，为什么召回这些证据，证据是否在用户权限范围内，最终答案又对应原文哪一句。

我试过用现成平台把链路拼起来。它们各有所长：有的擅长工作流，有的擅长文档解析，有的适合快速搭建 Agent。但在实际排障时，解析、切块、索引、召回、重排、引用和评测往往散落在不同组件里。某个指标变差后，很难沿着一次请求把原因追回去；为了提高召回再叠一层检索或模型调用，又可能直接把延迟和成本推高。我不想再做一套通用节点画布，也不想靠不断增加在线调用来换效果，所以把重点放回 RAG 链路本身：尽可能把计算前移到入库阶段，在现有候选集里完成融合和治理，同时把每一步留下可检查的结果。

这就是 MimirQ 后来形成的样子。上传文档时可以看到解析结果和切块边界；入库后可以检查元数据、版本与权限；提问时可以回看各路召回、融合、重排和逐句引用；知识图谱不是单独摆着看的页面，而是补充实体关系与多跳证据；评测也不是发布前跑一次的分数，而是每次修改后都能拿同一批问题做回归。项目看起来覆盖得比较宽，不是因为我想做一个“什么都有”的平台，而是因为一次错误答案的根因本来就可能跨过整条链路。

我选择把它开源，也是希望保留一份可以真正运行和拆解的参考实现。公开仓库不会包含生产知识库和内部环境，只保留经过裁剪的政务插件样例、可复现的处理流程以及必要的测试。你可以直接把它当成完整系统使用，也可以只取解析、切块、检索调试、Dify 外部知识库或 KG 中的一部分。它不承诺在所有数据上天然优于其他项目，但希望做到一件更朴素的事：效果变好时知道为什么，效果变差时也找得到原因。

> **MimirQ 想解决的不是“RAG 能不能跑”，而是“这套 RAG 为什么值得被相信”。**

---

## 📑 目录

- [我为什么做 MimirQ？](#-我为什么做-mimirq)
- [MimirQ 是什么](#-mimirq-是什么)
- [产品界面](#-产品界面)
- [接入 Dify](#-接入-dify)
- [快速开始](#-快速开始)
- [核心功能对比](#-核心功能对比)
- [已在真实场景验证](#-已在真实场景验证)
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

Dify 标准外部知识库端点为 `POST /api/v1/integrations/dify/retrieval`；可选用 `POST /api/v1/integrations/dify/conversation-turns` 回传答案、引用与会话标识，在 MimirQ 中留存完整链路。配置项见 [`.env.example`](./.env.example)，部署前可使用 [Dify / MimirQ readiness gate](./scripts/README.md) 校验知识库映射、检索质量与工作流 Trace；实测结果见 [Dify 四路质量横评](#dify-四路质量横评)。

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

Docker 首次构建会下载并校验固定版本的 DeepDoc 模型包；本地源码运行解析器前执行 `make models`。代理仅监听 Linux 宿主机回环地址时，应先在本机 Docker 配置代理，再运行 `DOCKER_BUILD_NETWORK=host make up-web`；不要把代理地址写进仓库。

| 场景 | 需要修改 | 是否必填 |
|:---|:---|:---:|
| 默认硅基流动 LLM + Embedding | `LLM_API_KEY` | **是** |
| 更换聊天供应商或模型 | `LLM_API_BASE`、`LLM_MODEL` | 否 |
| Embedding 使用不同供应商 | `EMBEDDING_API_KEY`、`EMBEDDING_API_BASE`、`EMBEDDING_MODEL` | 否；留空地址和密钥会复用 LLM |
| 硅基流动 Reranker | `ENABLE_RERANKER=true` | 否；默认关闭以避免增加检索时延，密钥复用 LLM |
| MinerU 在线 PDF 解析 | `MINERU_ENABLED=true`、`MINERU_API_TOKEN` | 否；启用后上传时选择 `mineru` |
| 其他 `.env` 参数 | 无需修改 | 否；保持默认 |

模型名必须来自硅基流动 `/v1/models`。当前实测可用的聊天模型包括 `Qwen/Qwen3-32B`、`Qwen/Qwen3-8B`，Embedding 包括 `BAAI/bge-m3`、`Qwen/Qwen3-Embedding-0.6B`，Reranker 为 `BAAI/bge-reranker-v2-m3`。更换 Embedding 模型后必须重建已有知识库索引，不能混用旧向量。

请在[硅基流动控制台](https://cloud.siliconflow.cn/account/ak)和 [MinerU](https://mineru.net/) 创建凭证；真实密钥只放本地 `.env`，不要提交。

### 运行政务插件样例

仓库内置常州政务服务知识插件，并为事项知识、一件事、常见问题、专题问答、部门问答和区县问答六类来源各保留少量公开演示数据。无需启动数据库即可验证治理、切块、KG 和 Golden 草稿：

```bash
make changzhou-gov-plugin-test-report
make changzhou-gov-plugin-chunk-report
```

报告写入 `/tmp/changzhou_gov_plugin_*`，不会写入数据库、向量库或 KG。样例目录、插件引用和真实语料闭环命令见[插件说明](./plugins/pipelines/changzhou-gov-service-knowledge/README.md)。

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

## 🧭 核心功能对比

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

---

## 📍 已在真实场景验证

MimirQ 不是实验室 Demo——它已用于**市级政务智能问答助手**，覆盖 7 个区级 + 市级真实知识库。验证分为两层：先用同一题集比较四种实际接入链路，再对升级前后的同一条 Dify HTTP 链路做严格配对。

### Dify 四路质量横评

<!-- 数据来源：artifacts/changzhou_dify_4way_partial/summary_for_sharing.md；complete_4way_1100=true，生成时间 2026-07-09T22:30:03Z。 -->

| 链路 | 实际调用路径 | 题数 | 回答可用率 | 回答证据覆盖 |
|:---|:---|---:|---:|---:|
| **MimirQ 检索直连** | 客户端 → MimirQ External Knowledge 检索 API（无 LLM 生成） | 1100 | **88.9%** | **88.7%** |
| **Dify External → MimirQ** | Dify 负责生成；MimirQ 作为 External Knowledge 检索源 | 1100 | 67.4% | 65.9% |
| **Dify HTTP → MimirQ** | Dify Workflow HTTP 节点调用 MimirQ 检索 API，再由 Dify 生成答案 | 1100 | 69.6% | 67.9% |
| **Dify 原生知识库** | Dify 原生入库、检索与生成 | 1100 | 50.6% | 49.7% |

1100 题由 800 道模拟用户问题、200 道事项直问和 100 道精确问答组成，统一使用确定性证据条款匹配，不使用 LLM judge。检索直连以 Top-3 证据文本作为输出，其余链路评估生成答案。四路工作量不同，因此不做延迟横向比较。延迟指标将在统一环境、固定并发和固定缓存状态下重新测试后发布。

### Dify HTTP 升级前后同参复测

<!-- 数据来源：artifacts/dify_3way_benchmark_ab_overlap_20260713/；固定同一 app、输入 SHA、truth SHA 和 687 个共同成功 case。 -->

| 指标（2026-07-13） | 升级前 | 最终版 | 变化 |
|:---|---:|---:|---:|
| 完整执行 | 687 / 800 | **800 / 800** | +113 题 |
| 配对答案条款覆盖率 | **84.4%** | 80.5% | -3.9pp |
| 配对答案可用率 | **91.8%** | 86.5% | -5.4pp |
| 最终完整 800 题 | — | 80.2% 条款覆盖 / 86.4% 可用 | — |
| 延迟指标 | — | 待统一环境重测 | — |

> 📝 **诚实说明**：同路复测证明了**完成率改善**，但不能证明整体答案质量提升。7 个区级知识库的条款覆盖合计 +3.0pp，市级知识库因输出变短而 -15.7pp，抵消了区级收益。每个版本只完整运行一次且 Dify 生成未固定随机种子，因此这是一组同参观测，不是统计显著性声明；延迟结论待统一环境重测后补充。完整逐题产物保存在本机 `artifacts/`，未随公开仓库发布；公开可复现测试见[中文评测指南](./docs/guides/public_benchmarks_zh.md)。

### 本地三模型 800 题复测

<!-- 数据来源：artifacts/changzhou_local_3model_800_20260721/summary.json；输入 SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2；生成时间 2026-07-21T04:56:32Z。 -->

2026-07-21 使用同一套固定 800 题，在局域网部署的 `bge-m3`、`bge-reranker-large` 和 `Qwen3-30B-A3B-Instruct-2507-FP16` 上重新测试完整链路：MimirQ External Knowledge 检索 Top-5 证据，再由本地 Qwen 生成答案。

| 指标 | 结果 |
|:---|---:|
| 完整执行 | **800 / 800**（0 失败） |
| 准确 / 部分准确 / 证据不足 | 717 / 68 / 15 |
| 答案准确率 / 可用率 | 89.6% / **98.1%** |
| 答案条款覆盖 / 证据覆盖 | **95.4%** / 97.6% |
| 答案受证据支持率 / 错误证据率 | 97.4% / 5.4% |
| 端到端平均 / P50 / P95 | 13.67s / 9.08s / 44.88s |
| 检索平均 / 生成平均 | 11.47s / 2.20s |

评分继续使用确定性证据条款匹配，不使用 LLM judge；固定并发为 6，单次运行保留了首批预热和复杂检索长尾。该链路改为本地 Qwen 生成答案，与上面的历史 Dify 生成链路不是同一实验条件，因此结果用于验证本地三模型链路的完整性和当前基线，不作升级前后的直接因果比较。

### 本地化四路 800 题复测

<!-- 数据来源：artifacts/changzhou_dify_4way_800_20260721/comparison_report.json；输入 SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2；生成时间 2026-07-21T04:56:03Z。 -->

同一套固定 800 题也重新跑完四种实际接入方式。MimirQ 使用局域网部署的 `bge-m3`、`bge-reranker-large` 和 `Qwen3-30B-A3B-Instruct-2507-FP16`；三个 Dify 应用按各自发布工作流调用相同的本地模型服务。

| 链路 | 成功执行 | 准确率 / 可用率 | 答案条款覆盖 | 答案受证据支持 | 错误证据率 | 平均 / P50 / P95 |
|:---|---:|---:|---:|---:|---:|---:|
| **MimirQ 检索直连** | **800 / 800** | **95.9% / 96.9%** | **96.3%** | **96.6%** | 5.4% | 12.10s / 7.47s / 36.05s |
| **Dify External → MimirQ** | 798 / 800 | 60.5% / 88.5% | 81.6% | 93.3% | 7.0% | 11.57s / 7.68s / 40.16s |
| **Dify HTTP → MimirQ** | **800 / 800** | 62.6% / 90.3% | 82.0% | 92.2% | 5.9% | **4.75s / 4.56s / 6.73s** |
| **Dify 原生知识库** | **800 / 800** | 38.9% / 76.8% | 67.3% | 87.1% | 79.1% | 10.61s / 8.52s / 27.65s |

2393 个必答条款中，四路共同未召回的只有 4 个；低分不是大面积知识源缺失。External 与 HTTP 的主要损失是证据已经召回、生成答案却未按必答字段完整输出；原生知识库还存在地区路由和 Top-K 噪声，已召回但未答出的条款占 19.8%，召回与答案均未匹配占 12.6%。这里的“错误证据率”表示返回记录中未命中本题严格条款的比例，不等于事实错误率。MimirQ 检索直连把 Top-3 证据文本直接作为输出，也不能与三条生成链路视为同等答案任务。

本次复核还修正了两个确定性评分问题：无结构化子问题时不再把非空答案记为 0 分，并让证据匹配读取已有的 `metadata.service_name`。Dify External 的两道失败题在多轮低并发重试后仍由 Dify 前置 Nginx 返回 `504 Gateway Time-out`，报告按无答案计入 800 题分母；Dify 原生知识库首轮暴露的新北区 reranker provider 配置错误已改为 `xinference`，发布后复测为 800 / 800。评分不使用 LLM judge；四路工作量不同，延迟不应视为严格同条件性能对比。

接入方式、真实工作流截图与部署前校验见[接入 Dify](#-接入-dify)。

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

[Dify](https://github.com/langgenius/dify) · [RAGFlow](https://github.com/infiniflow/ragflow) · [FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

感谢[硅基流动](https://siliconflow.cn/)为 MimirQ 的公开联调提供 50 元 API 体验额度支持。

---

<div align="center">

**如果 MimirQ 帮你把 RAG 从"能跑"做到了"敢上生产"，请给我们一个 ⭐ Star！**

每一个 Star 都是我们把黑盒继续打开的动力。

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
