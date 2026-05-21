# MimirQ 快速入门指南

## 🚀 5 分钟快速启动

### 1. 克隆项目
```bash
git clone https://github.com/skygazer42/MimirQ.git
cd MimirQ
```

### 2. 配置模型 API Key

初始化并编辑 `.env` 文件，填入你的模型配置（OpenAI-compatible）：

```env
LLM_API_KEY=sk-your-api-key-here
# 可选：自定义 Base URL（OpenAI-compatible）
# LLM_API_BASE=https://api.openai.com/v1
# LLM_MODEL=gpt-4o-mini
```

> 小贴士：可以先运行 `make init`，它会在缺失时自动从模板创建：
> - `.env`（来自 `.env.example`）
> - `web/.env.local`（来自 `web/.env.local.example`）
>
> 根目录 `.env.example` 已包含解析、RAG、KG、可观测性等环境变量；本地按需复制到 `.env` 后修改即可。

### 3. 启动服务

```bash
# 推荐：一键生成本地 env（不会覆盖已有文件）
make init

# 推荐：使用 Makefile 一键启动/查看状态
make up
make ps

# (可选) 低资源模式（lite：不启动 Milvus/MinIO，默认使用 Chroma 本地向量库）
# 适合：笔记本 / 小内存机器 / 快速试跑（更省资源）
make up-lite
make ps-lite

# (推荐给检索质量实验) 最小 retrieval-dev 组合：
# 仅启动 postgres + redis + api，不启用重解析服务；默认 LLM_MOCK_ENABLED=true
make up-retrieval-dev
make ps-retrieval-dev
make api-ping

# 或直接使用 docker compose（从仓库根目录执行）
docker compose --env-file .env -f docker/docker-compose.yml up -d --build
docker compose --env-file .env -f docker/docker-compose.yml ps

# (可选) 启动前端（两种方式二选一）
# 1) Docker（生产构建；推荐用于“一键部署”）
make up-web
# 2) 本地开发（热更新更快）
# cd web; pnpm install; pnpm dev
```

> 本地源码运行后端需要 Python 3.11+（项目包含 `match/case` 等语法与依赖约束）。如果你只想快速跑起来，优先使用 Docker。
>
> 如果你要本地源码调后端，请直接使用项目虚拟环境入口，不要调用系统全局 `uvicorn`：
>
> ```bash
> make backend
> ```
>
> 若宿主机文件监听额度较低、`uploads/` 又比较大，优先改用：
>
> ```bash
> make backend-no-reload
> ```

#### retrieval-dev 资源与时延预期（经验值）

- 推荐机器：4 vCPU / 8 GB RAM（最低可在 2 vCPU / 4 GB RAM 运行，但索引与查询明显更慢）。
- 冷启动（首次 build）：约 3-8 分钟，取决于网络与镜像缓存。
- 热启动（镜像已缓存）：通常 20-60 秒即可达到 `api-ping` 全绿。
- 该模式默认关闭重解析路径，适合做召回/排序离线对比，不适合高并发生产压测。

> Docker 启动前端时：`NEXT_PUBLIC_API_URL` 是给浏览器用的（默认 `http://localhost:8000`）；如需 SSR 在容器内访问后端，请设置 `API_INTERNAL_URL_DOCKER=http://mimirq-api:8000`（不要把 `NEXT_PUBLIC_API_URL` 改成 Docker 内部地址）。

### (可选) 启用 ETL4LLM（Bisheng Unstructured）版面解析

MimirQ 已内置 `etl4llm` 解析器（并兼容 `bisheng` / `bisheng-unstructured` 别名），你只需要把服务跑起来并配置好 API URL：

```bash
# 启动 etl4llm 服务（Docker profile）
make up-etl4llm
```

然后在 `.env` 里配置：
```env
ETL4LLM_ENABLED=true
ETL4LLM_API_URL=http://mimirq-etl4llm:10001/v1/etl4llm/predict
```

### (可选) 启用 Marker（启发式服务 PDF→Markdown）

Marker 建议以独立容器/服务运行（重依赖不进入 MimirQ 主镜像），然后在解析时指定 `parser_backend=marker`。

```bash
make up-marker
```

然后在 `.env` 里配置：
```env
MARKER_ENABLED=true
MARKER_API_URL=http://mimirq-marker:2080/convert
```

### (可选) 启用 PaddleOCR-VL（外部 OCR/版面解析）

PaddleOCR-VL 建议以独立容器/服务运行（重依赖不进入 MimirQ 主镜像），然后在解析时指定 `parser_backend=paddle_vl`。

```bash
make up-paddlevl
```

然后在 `.env` 里配置：
```env
PADDLE_VL_ENABLED=true
PADDLE_VL_API_URL=http://127.0.0.1:9030/convert
PADDLEOCR_DEVICE=gpu:0
```

### (可选) 启用 Qianfan-OCR（外部 OCR）

Qianfan-OCR 建议以独立容器/服务运行，MimirQ 通过包装服务调用上游 OpenAI-compatible 视觉推理接口。

```bash
make up-qianfanocr
```

然后在 `.env` 里配置：
```env
QIANFAN_OCR_ENABLED=true
QIANFAN_OCR_API_URL=http://mimirq-qianfanocr:2090/convert
# 包装服务上游（示例）
QIANFAN_OCR_SERVER_URL=http://host.docker.internal:8000/v1
QIANFAN_OCR_MODEL=baidu/Qianfan-OCR
```

### (可选) 启用 TextIn xParse（外部 API 文档解析）

TextIn xParse 通过官方 API 直接返回 Markdown/结构化结果，适合把 PDF / Office / 图片等
文档解析能力接入到 MimirQ，而无需自建重型 OCR/版面服务。

然后在 `.env` 里配置：

```env
TEXTIN_ENABLED=true
TEXTIN_API_URL=https://api.textin.com/ai/service/v1/pdf_to_markdown
TEXTIN_APP_ID=your-app-id
TEXTIN_SECRET_CODE=your-secret-code
TEXTIN_TIMEOUT_SEC=180
TEXTIN_PARSE_MODE=auto
TEXTIN_TABLE_FLAVOR=html
TEXTIN_APPLY_DOCUMENT_TREE=true
TEXTIN_MARKDOWN_DETAILS=true
```

说明：

- 前端设置页会暴露 TextIn 的开关和凭证配置
- 后端会把它作为 `parser_backend=textin` 接入
- 这是**外部 API parser**，不属于本地模型部署

### (可选) 启用 MinerU（本地 FastAPI ZIP 模式）

MinerU 建议以独立容器运行（依赖/模型较重），MimirQ 通过 HTTP 调用其 `/file_parse` 接口拿到 ZIP（Markdown + images）。

```bash
make up-mineru
```

然后在 `.env` 里配置（后端跑在 Docker 时）：
```env
MINERU_ENABLED=true
MINERU_MODEL_SOURCE=local
MINERU_LOCAL_SERVER_URL=http://mimirq-mineru:8000
```

如果你是“本地跑后端 + Docker 跑 MinerU”，可用：
```env
MINERU_ENABLED=true
MINERU_MODEL_SOURCE=local
MINERU_LOCAL_SERVER_URL=http://localhost:30001
```

### (可选) 启用 MagicPDF（本地 magic-pdf CLI）

MagicPDF 在 MimirQ API / worker 镜像内通过 `magic-pdf` CLI 调用。CLI 已随 Docker backend
安装，但真实本地解析还需要挂载 PDF-Extract-Kit 模型缓存；核心 compose 会把
`mineru_cache` 只读挂到 `/opt/mimirq-model-cache`，可复用 MinerU 下载的模型。

```env
MAGIC_PDF_ENABLED=true
MAGIC_PDF_CLI=magic-pdf
MAGIC_PDF_METHOD=auto
MAGIC_PDF_LANG=ch
MAGIC_PDF_MODELS_DIR=
MAGIC_PDF_DEVICE_MODE=cpu
```

诊断：

```bash
docker compose -f docker/docker-compose.yml exec -T -w /app mimirq-api python scripts/check_parsers.py
```

MagicPDF 只有在状态为 `configured (models: ...)` 时才会被自动路由/能力接口标记为可用；
如果显示 `missing cli` 或 `missing models`，需要先修镜像或模型挂载。

### (可选) 启用 Pandoc/LibreOffice（Office/HTML 高质量转 Markdown）

适用于：`doc/docx/ppt/pptx/xls/xlsx/html/htm`（图片/表格保真更好）。

在 `.env` 里配置：
```env
PANDOC_ENABLED=true
# 旧格式（.doc/.ppt/.xls）需要 LibreOffice 辅助转换
LIBREOFFICE_ENABLED=true
```

### 可选解析器部署 / 显存要求（基于当前仓库实测）

下表是本仓库在 **2026-04-13** 这轮 rebuilt runtime 验证里，对同一份 `runs/deepseek_ocr_smoke.pdf`
逐个 parser 单独部署 / 单独触发时记录到的结果。它描述的是**当前这套镜像、当前这条调用链**
下的观测值，不代表所有硬件/驱动/模型配置下的绝对上限。

| 解析器 | 本地模型/推理形态 | 实测本地 GPU 峰值 | 部署建议 |
|---|---|---:|---|
| `marker` | CPU-only 本地服务 | ~0 GiB | 无需 GPU；建议独立容器运行 |
| `etl4llm` | CPU / 无本地 GPU 分配 | ~0 GiB | 无需 GPU；建议独立容器运行 |
| `textin` | 外部 TextIn xParse API | ~0 GiB | 本地无模型；必须配置 `TEXTIN_APP_ID` / `TEXTIN_SECRET_CODE` 后才可真实解析 |
| `qianfan_ocr` | 本地轻量 wrapper，实际推理在上游视觉服务 | ~0 GiB | 本地容器无需 GPU；上游服务显存单独评估 |
| `mineru`（`backend=pipeline` / `file_parse`） | 本地 `mineru-api` + 本地缓存模型 | 当前验证流未观测到独立 GPU 峰值 | 建议单独部署；若切换不同 backend / 模型链路，需重新量测 |
| `magicpdf` | API/worker 内本地 `magic-pdf` CLI + PDF-Extract-Kit 缓存模型 | CPU 模式 ~0 GiB；CUDA 模式需单独量测 | CPU 可用但慢；建议复用 `mineru_cache`，显式检查 `configured (models: ...)` |
| `paddle_vl` | 本地 GPU 推理（`gpu:0`） | ~8.2 GiB | 建议至少预留 **10 GiB** 可用显存 |
| `olmocr` | 本地 GPU 重模型推理 | ~43.7 GiB | 建议至少预留 **44 GiB** 可用显存，基本等同 48G 级别单卡独占 |

补充说明：

- 以上显存数据来自 `runs/parser_checks/vram-measurements.json`
- rebuilt runtime 下的 parser 解析成功证据见：`runs/parser_checks/20260413T071030Z-rebuilt/`
- 如果同一张卡上还有别的长驻进程，请按“**外部占用 + parser 峰值 + 安全余量**”一起估算
- `olmocr` 明显比其余 parser 慢，当前验证里单次 preview 级请求耗时约 **151 秒**

### 生产部署（推荐）

生产部署使用 `docker/docker-compose.yml`（默认不暴露 Postgres/Milvus/Redis/MinIO 端口）：

```bash
cd docker
cp .env.example .env
docker compose up -d --build
docker compose -f docker-compose.yml -f docker-compose.web.yml up -d --build   # 可选：启用前端
```

根目录 `.env.example` 已包含本地启动和高级能力配置；未启用的能力保持默认关闭即可。

可选：本地启动后端（Python），依赖服务仍用 Docker：
```bash
cd docker
cp .env.example .env
docker compose -f docker-compose.infra.yml up -d

cd ..
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
python main.py
```

启动后建议做一次快速校验：
```bash
make verify
```

### 4. 访问应用

打开浏览器访问:
- 后端 API 文档: http://localhost:8000/docs
- 前端界面 (需启动前端): http://localhost:3000
- 健康检查: http://localhost:8000/api/v1/health
- 就绪探针: http://localhost:8000/api/v1/health/ready
- 详细依赖状态: http://localhost:8000/health

> 提示：如需查看/回滚文档的 `pipeline_hash` 版本，可在「知识库」打开文档详情弹窗后点击“版本”。详见：[docs/guides/document_versions.md](./guides/document_versions.md)。

> 说明：聊天接口同时支持 LangChain 与 LangGraph 两条路径。当前端开启 RAG 设置里的 `use_graph` 时，会收到额外的 `graph` 事件用于展示更细的“思考路径/步骤”。

---

## 📖 使用流程

### Step 1: 上传文档
1. 点击左侧 "上传文档" 按钮
2. 选择 PDF / Office / HTML / Markdown / TXT 文件
3. 等待文档处理完成（进度条会实时显示）

### Step 2: 开始对话
1. 在右侧输入框输入问题
2. 按 Enter 发送（Shift + Enter 换行）
3. AI 会基于你上传的文档内容回答

### Step 3: 查看引用
- AI 回答下方会显示参考的文档片段
- 包含文件名、页码和相似度分数

---

## 🎯 功能示例

### 示例 1: 法律文档问答
```
上传: 《劳动合同法》PDF
提问: "试用期最长可以是多久？"
AI 回答: 基于《劳动合同法》第19条，试用期最长不得超过...
```

### 示例 2: 技术文档查询
```
上传: React 官方文档 Markdown
提问: "如何使用 useEffect Hook？"
AI 回答: 根据文档，useEffect 是一个用于处理副作用的 Hook...
```

### 示例 3: 公司内部知识库
```
上传: 公司规章制度.pdf、员工手册.pdf
提问: "年假申请流程是什么？"
AI 回答: 根据员工手册第3章...
```

---

## ⚙️ 高级配置

### 修改 RAG 参数

编辑 `app/core/config.py`:

```python
# 文本切片大小
CHUNK_SIZE: int = 1000  # 增大可减少切片数量

# 检索相关片段数量
RETRIEVAL_TOP_K: int = 5  # 增加可获得更多上下文

# 相似度阈值
SIMILARITY_THRESHOLD: float = 0.7  # 提高可过滤低质量结果
```

### 切换 LLM 模型

编辑 `app/core/config.py`:

```python
# 使用轻量模型（更便宜）
LLM_MODEL: str = "gpt-4o-mini"

# 使用更强模型
LLM_MODEL: str = "gpt-4o"
```

### 使用 Claude 替代 OpenAI

编辑 `app/rag/engine.py`:

```python
from langchain_anthropic import ChatAnthropic

self.llm = ChatAnthropic(
    model="claude-3-sonnet-20240229",
    api_key=settings.ANTHROPIC_API_KEY,
    streaming=True
)
```

---

## 🐛 常见问题

### Q1: 文档上传后一直显示 "处理中"？

**原因**:
1. Embedding 模型首次加载较慢（需下载 1.5GB）
2. Milvus 初次启动需要创建 Collection

**解决**:
- 等待 2-5 分钟
- 查看后端日志: `docker compose logs -f mimirq-api`
- 查看 Milvus 状态: `curl http://localhost:9091/healthz`

### Q2: AI 回答"没有找到相关资料"？

**原因**:
1. 文档还在处理中
2. 问题与文档内容不相关
3. 相似度阈值过高

**解决**:
- 确认文档状态为 "已完成"
- 降低 `SIMILARITY_THRESHOLD` 到 0.5
- 重新表述问题

### Q3: Docker 启动失败？

**检查**:
```bash
# 查看服务状态
cd docker
docker compose ps

# 查看错误日志
docker compose logs

# 重启服务
docker compose restart
```

### Q4: 前端无法连接后端？

**检查 CORS 配置**:

编辑 `app/core/config.py`:
```python
CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
```

---

## 📊 性能优化

### 1. 生产环境部署

**使用 Gunicorn** (backend):
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

**Next.js 生产构建** (frontend):
```bash
pnpm build
pnpm start
```

### 2. Milvus 性能优化

**使用 HNSW 索引（更高精度）**:

编辑 `app/services/milvus_store.py`:

```python
index_params = {
    "metric_type": "COSINE",
    "index_type": "HNSW",
    "params": {"M": 16, "efConstruction": 200}
}
```

**详细指南**: [guides/milvus_guide.md](./guides/milvus_guide.md)

### 3. 文档解析升级

集成 MinerU 2.5:

```yaml
# docker-compose.yml
mineru:
  image: opendatalab/mineru:2.5
  ports:
    - "8080:8080"
```

---

## 📚 参考资源

- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [LangChain 文档](https://python.langchain.com/)
- [Next.js 文档](https://nextjs.org/docs)
- [ChromaDB 文档](https://docs.trychroma.com/)

---

## 💡 技术支持

遇到问题？

1. 查看 [README.md](./README.md) 完整文档
2. 查看后端日志: `docker compose logs -f mimirq-api`
3. 访问 API 文档: http://localhost:8000/docs
4. 提交 Issue: [GitHub Issues](https://github.com/skygazer42/MimirQ/issues)

---

**Enjoy MimirQ! 🎉**
