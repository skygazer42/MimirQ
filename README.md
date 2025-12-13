<div align="center">

# 🔮 MimirQ

### 🚀 新一代智能知识库问答系统 | Next-Gen AI Knowledge Base

*基于 RAG (Retrieval-Augmented Generation) 的企业级知识管理平台*
<br/>
*可视化切片 • 混合检索 • 多模态解析*

[English](./README_EN.md) | [简体中文](./README.md)

<p align="center">
  <a href="#-核心亮点">亮点</a> •
  <a href="#-功能清单">功能</a> •
  <a href="#-快速开始">开始</a> •
  <a href="#-技术架构">架构</a> •
  <a href="#-部署指南">部署</a> •
  <a href="#-文档">文档</a>
</p>

<!-- Tech Stack Badges -->
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 14](https://img.shields.io/badge/Next.js-14-black)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688.svg)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/🦜_LangChain-0.3-green)](https://langchain.com/)
[![Milvus](https://img.shields.io/badge/Milvus-2.3-00a1e0)](https://milvus.io/)

<!-- Social/Stats Badges -->
[![Docker Pulls](https://img.shields.io/docker/pulls/yourusername/mimirq?style=flat-square&color=blue)](https://hub.docker.com/r/yourusername/mimirq)
[![GitHub stars](https://img.shields.io/github/stars/yourusername/mimirq?style=flat-square&color=yellow)](https://github.com/yourusername/mimirq)
[![Discord](https://img.shields.io/discord/1234567890?logo=discord&label=Discord&color=5865F2)](https://discord.gg/yourinvite)

</div>

---

## 🌟 核心亮点

<table>
  <tr>
    <td width="25%" align="center">
      <img src="./docs/images/icon-chat.svg" alt="对话界面" width="64" />
      <br/><br/>
      <strong>智能对话</strong>
      <br/>
      <span style="font-size: 12px; color: grey">流式响应 + 引用展示</span>
    </td>
    <td width="25%" align="center">
      <img src="./docs/images/icon-document.svg" alt="文档管理" width="64" />
      <br/><br/>
      <strong>文档管理</strong>
      <br/>
      <span style="font-size: 12px; color: grey">实时处理状态监控</span>
    </td>
    <td width="25%" align="center">
      <img src="./docs/images/icon-search.svg" alt="知识检索" width="64" />
      <br/><br/>
      <strong>混合检索</strong>
      <br/>
      <span style="font-size: 12px; color: grey">向量 + BM25 双引擎</span>
    </td>
    <td width="25%" align="center">
      <img src="./docs/images/icon-citation.svg" alt="引用溯源" width="64" />
      <br/><br/>
      <strong>答案溯源</strong>
      <br/>
      <span style="font-size: 12px; color: grey">文档片段 + 页码标注</span>
    </td>
  </tr>
</table>

---

## 🛠️ 功能清单

<table>
<tr>
<td width="33%" valign="top">

### 📁 智能文档管理
- ✅ 支持 PDF / Markdown / TXT 多格式
- ✅ 拖拽上传 + 批量处理
- ✅ 实时进度展示
- ✅ 自动分块索引 (LangChain)
- ✅ 支持文档更新和版本管理

</td>
<td width="33%" valign="top">

### 🤖 RAG 智能问答
- ✅ 混合检索 (向量 + BM25)
- ✅ 流式响应 (打字机效果)
- ✅ 对话记忆 (PostgreSQL 持久化)
- ✅ 多轮对话上下文理解
- ✅ 引用溯源 (文档 + 页码)

</td>
<td width="33%" valign="top">

### 🚀 企业级架构
- ✅ LangChain Runnable/Retriever 编排
- ✅ Milvus 十亿级向量检索
- ✅ OpenAI 兼容接口 (支持自部署)
- ✅ Docker Compose 一键部署
- ✅ PostgreSQL 持久化存储

</td>
</tr>
</table>

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户界面 (Next.js 14)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ 文档管理     │  │ 智能对话     │  │ 引用展示     │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ RESTful API / SSE
┌──────────────────────────▼──────────────────────────────────────┐
│                   FastAPI 后端服务                                │
│  ┌────────────────────────────────────────────────────────┐     │
│  │           LangChain RAG 编排引擎                       │     │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │     │
│  │  │ Chat Model   │  │ Hybrid       │  │ Runnable     │ │     │
│  │  │ (OpenAI/...) │  │ Retriever    │  │ (Prompt)     │ │     │
│  │  └──────────────┘  └──────────────┘  └──────────────┘ │     │
│  └────────────────────────────────────────────────────────┘     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ 文档解析     │  │ 混合检索     │  │ Embedding    │           │
│  │ (PyMuPDF)    │  │ (Vector+BM25)│  │ (BGE/OpenAI) │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  PostgreSQL  │  │    Milvus    │  │  BM25 Index  │
│ (对话/文档)   │  │ (向量检索)    │  │ (关键词检索)  │
└──────────────┘  └──────────────┘  └──────────────┘
                   │
            ┌──────┴──────┐
            ▼             ▼
       ┌────────┐    ┌────────┐
       │  Etcd  │    │ MinIO  │
       │(元数据) │    │(对象)   │
       └────────┘    └────────┘
```

### 技术栈详情

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| **前端** | Next.js 14 (App Router) + TypeScript | 现代化 React 框架 |
| **UI 组件** | Tailwind CSS + Shadcn/ui | 极简设计系统 |
| **后端** | FastAPI 0.109 + Python 3.11 | 高性能异步框架 |
| **AI 编排** | LangChain 1.x (Runnable + Retriever) | 纯 LangChain RAG 链路 |
| **向量数据库** | Milvus 2.3 + Etcd + MinIO | 十亿级向量检索 |
| **关系数据库** | PostgreSQL 15 | 文档/对话持久化 |
| **Embedding** | BGE-large-zh-v1.5 (本地) | 中文向量模型 |
| **LLM** | OpenAI 兼容接口 | GPT-4 / 自部署模型 |
| **检索策略** | Hybrid Search (Vector + BM25) | 混合检索算法 |
| **分词器** | Jieba | 中文分词支持 |

---

## 📂 项目结构

```bash
MimirQ/
├── backend/             # FastAPI 后端服务
│   ├── app/             # 应用核心代码
│   │   ├── api/         # API 路由
│   │   ├── core/        # 核心配置与数据库
│   │   ├── models/      # 数据模型 (Pydantic/SQLModel)
│   │   ├── services/    # 业务逻辑 (RAG/Milvus/LangChain)
│   │   └── deepdoc/     # 深度文档解析模块
│   └── Dockerfile       # 后端构建文件
├── frontend/            # Next.js 前端界面
│   ├── app/             # 页面路由
│   ├── components/      # UI 组件
│   ├── lib/             # 工具函数与 API 客户端
│   └── public/          # 静态资源
├── docs/                # 项目文档
├── docker-compose.yml   # 容器编排配置
└── README.md            # 项目说明
```

---

## 🚀 快速开始

### 前置要求

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| Docker | 20.10+ | 容器化部署 |
| Docker Compose | 2.0+ | 服务编排 |
| Node.js | 20+ | 前端开发 (可选) |
| Python | 3.11+ | 后端开发 (可选) |

### 一键部署 (Docker Compose)

只需三步，即可快速启动：

**1. 初始化环境**

```bash
# 克隆项目
git clone https://github.com/yourusername/MimirQ.git
cd MimirQ

# 配置环境变量 (使用默认模板)
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
```

**2. 配置模型密钥 (可选)**

编辑 `backend/.env` 文件，填入您的 API Key：

```bash
# 推荐使用 vim 或 nano 编辑
vim backend/.env

# 关键配置项:
# LLM_API_KEY=sk-xxxx
# LLM_API_BASE=https://api.openai.com/v1
```

**3. 启动服务**

```bash
# 拉取并启动所有服务 (首次运行可能需要几分钟下载镜像)
docker-compose up -d

# 检查服务状态
docker-compose ps
```

### 访问服务

等待约 1 分钟服务完全启动后，访问：

---

## 📚 使用指南

### 1️⃣ 上传文档

<details>
<summary>点击展开详细步骤</summary>

1. 访问前端界面 http://localhost:3000
2. 点击左侧边栏 **"上传文档"** 按钮
3. 拖拽或选择文件 (支持 PDF / Markdown / TXT)
4. 等待文档处理完成 (实时显示进度)
5. 处理完成后文档出现在列表中

**处理流程**:
```
上传文件 → 解析文本 → 分块 (1000字符/块) → 生成 Embedding → 存入 Milvus → 完成
```

</details>

### 2️⃣ 智能问答

<details>
<summary>点击展开详细步骤</summary>

1. 在右侧对话框输入问题
2. 点击发送或按 `Enter` 键
3. 系统自动检索相关文档
4. AI 流式生成回答 (打字机效果)
5. 查看引用来源 (文档名 + 页码)

**检索策略**:
- **向量检索 (60%)**: 语义相似度匹配
- **BM25 检索 (40%)**: 关键词精确匹配
- **混合排序**: RRF 算法融合结果

</details>

### 3️⃣ 对话管理

<details>
<summary>点击展开详细步骤</summary>

- **新建对话**: 点击顶部 **"新建对话"** 按钮
- **切换对话**: 左侧边栏选择历史对话
- **清空对话**: 点击对话标题旁的垃圾桶图标
- **对话记忆**: 系统自动记住最近 5 轮对话 (10 条消息)

**技术实现**:
- PostgreSQL 持久化对话与消息
- 仅保留最近 5 轮历史供 LLM 使用
- LangChain Runnable 链路（Retriever → Prompt → LLM）

</details>

---

## 🛠️ 本地开发

### 后端开发

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动 PostgreSQL + Milvus (Docker)
docker-compose up -d postgres etcd minio milvus

# 启动后端服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build
```

---

## 📖 文档

### 核心文档

- [快速入门](./docs/quickstart.md) - 本地开发、Docker Compose、环境检查
- [Milvus 向量数据库指南](./docs/guides/milvus_guide.md) - 索引类型、性能调优、GPU 加速
- [RAG 优化指南](./docs/guides/rag_optimization.md) - 对话历史、混合检索、Rerank
- [LangChain RAG 架构文档](./docs/guides/langchain_agent_migration.md) - Retriever/Runnable 链路
- [依赖说明](./docs/guides/dependencies.md) - 不同解析及 Embedding 模式的依赖组合
- [MinerU 集成](./docs/integrations/mineru_integration.md) - 高级 PDF 解析配置
- [ChromaDB → Milvus 迁移](./docs/integrations/migration_chromadb_to_milvus.md) - 架构选择、数据迁移脚本

### API 文档

完整 API 文档请访问: http://localhost:8000/docs

**快速参考**:

#### 上传文档
```bash
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@document.pdf"
```

#### 流式对话
```bash
curl -X POST "http://localhost:8000/api/v1/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "什么是 RAG？",
    "conversation_id": "uuid",
    "stream": true
  }'
```

---

## 🎯 高级特性

### 1. 混合检索 (Hybrid Search)

结合向量检索和关键词检索，提升准确率:

```python
from app.services.hybrid_retriever import hybrid_retriever

# LangChain 1.x Retriever 混合检索
retriever = hybrid_retriever.model_copy(update={"k": 10, "alpha": 0.6})
docs = retriever.invoke(query)
```

**适用场景**:
- ✅ 专有名词检索 (如 "项目代号A123")
- ✅ 代码片段搜索
- ✅ 数字、日期等精确匹配

### 2. 对话记忆

对话与消息由 PostgreSQL 持久化，前端请求携带最近历史；后端保留最近 5 轮作为 prompt 的 history 输入。

### 3. OpenAI 兼容接口

支持任何 OpenAI 兼容的 LLM 服务:

| 服务 | 配置示例 |
|------|---------|
| OpenAI | `LLM_API_BASE=https://api.openai.com/v1` |
| DeepSeek | `LLM_API_BASE=https://api.deepseek.com/v1` |
| 通义千问 | `LLM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 本地 Ollama | `LLM_API_BASE=http://localhost:11434/v1` |

---

## 🚢 部署指南

### Docker Compose (推荐)

```bash
# 生产环境部署
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 扩容后端服务
docker-compose up -d --scale backend=3
```

### Kubernetes

```bash
# 使用 Helm Chart 部署
helm install mimirq ./k8s/helm/mimirq

# 或使用 kubectl
kubectl apply -f k8s/manifests/
```

### 环境变量配置

<details>
<summary>完整环境变量列表</summary>

```bash
# === LLM 配置 ===
LLM_API_KEY=sk-your-api-key
LLM_API_BASE=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo-preview
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=60
LLM_MAX_RETRIES=3

# === Embedding 配置 ===
EMBEDDING_PROVIDER=local  # local | openai_compatible
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DEVICE=cuda  # cpu | cuda
EMBEDDING_API_KEY=  # 留空则使用 LLM_API_KEY
EMBEDDING_API_BASE=  # 留空则使用 LLM_API_BASE

# === 数据库配置 ===
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/mimirq

# === Milvus 配置 ===
MILVUS_HOST=milvus
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=knowledge_base

# === RAG 参数 ===
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
RETRIEVAL_TOP_K=5
SIMILARITY_THRESHOLD=0.7

### 解析 / 切块能力开关

| 变量 | 说明 | 默认 |
|------|------|------|
| `DEFAULT_PARSER_BACKEND` | `auto/basic/mineru/deepdoc/markitdown`，控制未指定时使用的解析器 | `auto` |
| `DEEPDOC_ENABLED` | 启用 DeepDoc 解析。需要将 DeepDoc 包放在 `backend/deepdoc` 或通过 `pip install deepdoc` 安装 | `false` |
| `MARKITDOWN_ENABLED` | 开启微软 MarkItDown 解析，配合 `MARKITDOWN_USE_PLUGINS` 等配置 | `false` |
| `MINERU_ENABLED` | 开启 MinerU 在线解析（需 `MINERU_API_TOKEN`） | `false` |
| `DEFAULT_CHUNK_STRATEGY` | 默认切块策略：`langchain_recursive` 或 `llama_index` | `langchain_recursive` |
| `LLAMA_INDEX_ENABLED` | 允许调用 LlamaIndex SentenceSplitter；为 `true` 前端才可选择该切块方式 | `false` |


# === 应用配置 ===
UPLOAD_DIR=/app/uploads
MAX_UPLOAD_SIZE=10485760  # 10MB
ALLOWED_EXTENSIONS=pdf,md,txt
```

</details>

---

## 📊 性能基准

| 指标 | 数值 | 说明 |
|------|------|------|
| **文档处理速度** | ~100 页/分钟 | PDF 解析 + 分块 + Embedding |
| **检索延迟** | <100ms | Milvus 向量检索 (IVF_FLAT) |
| **LLM 首字延迟** | ~500ms | 包含检索 + LLM 初始化 |
| **流式输出速度** | ~50 tokens/s | GPT-4 Turbo 平均速度 |
| **并发支持** | 100+ QPS | 单机 FastAPI + Milvus |
| **向量容量** | 10 亿+ | Milvus 集群模式 |

**测试环境**: 4 vCPU / 16 GB RAM / SSD

---

## 🗺️ Roadmap

- [x] ✅ 基础 RAG 对话功能
- [x] ✅ Milvus 向量数据库集成
- [x] ✅ 混合检索 (Vector + BM25)
- [x] ✅ LangChain Runnable/Retriever 架构
- [x] ✅ PostgreSQL 对话记忆
- [ ] 🚧 MinerU 2.5 高级 PDF 解析 (进行中)
- [ ] 📅 多模态支持 (图片、表格理解)
- [ ] 📅 知识图谱可视化
- [ ] 📅 团队协作 (多用户、权限管理)
- [ ] 📅 API 认证 (NextAuth.js / Clerk)
- [ ] 📅 Webhook 集成 (Slack / 飞书)
- [ ] 📅 移动端适配 (React Native)

---

## 🤝 贡献指南

我们欢迎所有形式的贡献！

### 如何贡献

1. Fork 本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

### 开发规范

- Python: 遵循 PEP 8 规范
- TypeScript: 遵循 Airbnb 规范
- 提交信息: 使用 [Conventional Commits](https://www.conventionalcommits.org/)

---

## 🙏 致谢

MimirQ 基于以下优秀开源项目构建:

- [LangChain](https://github.com/langchain-ai/langchain) - LLM 应用框架
- [Milvus](https://github.com/milvus-io/milvus) - 向量数据库
- [FastAPI](https://github.com/tiangolo/fastapi) - 现代化 Python 框架
- [Next.js](https://github.com/vercel/next.js) - React 全栈框架
- [Shadcn/ui](https://ui.shadcn.com/) - 高质量 UI 组件

特别感谢 [Dify](https://github.com/langgenius/dify) 提供的设计灵感。

---

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE)

---

## 💬 社区与支持

- 📧 邮箱: support@mimirq.com
- 💬 Discord: [加入我们](https://discord.gg/yourinvite)
- 🐦 Twitter: [@MimirQ](https://twitter.com/mimirq)
- 📖 文档: https://docs.mimirq.com

---

<div align="center">

**如果这个项目对你有帮助，请给我们一个 ⭐ Star!**

Made with ❤️ by MimirQ Team

</div>
