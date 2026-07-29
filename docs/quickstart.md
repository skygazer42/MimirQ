# MimirQ 快速入门指南

## 🚀 5 分钟快速启动

### 1. 克隆项目
```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
```

### 2. 启动完整 Web 栈

```bash
# 生成 .env、随机 JWT SECRET_KEY 和前端图片代理密钥
make init
```

`.env` 是高级配置参考，不需要逐项填写。默认使用硅基流动 `Qwen/Qwen3-32B` 和 `BAAI/bge-m3`；完成真实知识库闭环时，最少先确认这几项：

| 变量 | 必填 | 说明 |
|:---|:---|:---|
| `LLM_API_KEY` | 是 | 默认对话与基础抽取凭证 |
| `LLM_API_BASE` / `LLM_MODEL` | 否 | 默认值已可用于硅基流动 |
| `EMBEDDING_API_KEY` / `EMBEDDING_API_BASE` | 否 | 为空时复用 `LLM_*` |
| `ENABLE_RERANKER=true` | 否 | 默认关闭，避免额外时延 |
| `INITIAL_ADMIN_*` | 否 | 可选但推荐，首次启动自动创建第一个 `owner` |

如果你希望首次进入系统时就自动拥有第一个本地管理员，可以额外配置：

```env
INITIAL_ADMIN_EMAIL=owner@example.com
INITIAL_ADMIN_USERNAME=owner
INITIAL_ADMIN_PASSWORD=<strong-password>
```

管理员密码也可改用 `INITIAL_ADMIN_PASSWORD_FILE`，与明文密码二选一。LLM、Embedding 与 Reranker 使用不同服务时，必须分别填写对应地址、Key 与模型；Reranker 地址是完整请求端点。完整模板、Docker/主机地址差异和首次管理员规则见[模型服务与首次管理员配置](./guides/model_services.md)。然后启动：

```bash
make up-web
make api-ping
```

打开 [http://localhost:3000](http://localhost:3000)。若未配置 `INITIAL_ADMIN_*`，先在页面中创建第一个本地账户。不要在人工注册前使用 `CORE_E2E_BOOTSTRAP_REGISTER=1`，否则 smoke 测试会先创建一个随机 owner 并关闭首次设置。

首次构建会下载并校验固定版本的解析模型。代理仅监听 Linux 宿主机回环地址时，先在本机 Docker 配置代理，再运行 `DOCKER_BUILD_NETWORK=host make up-web`；不要把个人代理地址提交到配置模板。

### 3. 其他启动方式

```bash
# 仅启动后端 + 标准基础设施
make up

# 查看标准栈状态
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

# 或直接使用 docker compose（从仓库根目录执行，并固定项目名）
docker compose --project-name mimirq --env-file .env -f docker/docker-compose.yml up -d --build
docker compose --project-name mimirq --env-file .env -f docker/docker-compose.yml ps

# 本地前端开发（热更新）
# cd web; pnpm install; pnpm dev
```

> 本地源码运行后端需要 Python 3.11+（项目包含 `match/case` 等语法与依赖约束）。如果你只想快速跑起来，优先使用 Docker。
>
> 如果你要本地源码调试完整 Web 栈，请先启动依赖服务，再启动 API 和前端，不要手写全局 `uvicorn` / `arq` 命令：
>
> ```bash
> make setup-host
> ```
>
> 默认 `TASK_QUEUE_ENABLED=false`，后台文档任务由 API 进程内有界处理；分别打开两个终端运行：
>
> ```bash
> # 终端 1：FastAPI（热更新）
> make backend
>
> # 终端 2：Next.js（热更新）
> make web
> ```
>
> 需要独立队列时，在 `.env` 设置 `TASK_QUEUE_ENABLED=true` 并重启 API，再于第三个终端运行 `make worker`；随后可用 `make worker-check` 检查 Redis 存活标记。Docker 一键启动默认已启用队列。
>
> 若宿主机文件监听额度较低、`uploads/` 又比较大，API 进程优先改用：
>
> ```bash
> make backend-no-reload
> ```

主机源码启动后，执行一条最小闭环验收：

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 make web-api-ping
```

在页面完成首次设置后，将同一账号配置为 `MIMIRQ_SMOKE_IDENTIFIER` 与 `MIMIRQ_SMOKE_PASSWORD`，再运行 `make core-e2e`。

#### retrieval-dev 资源与时延预期（经验值）

- 推荐机器：4 vCPU / 8 GB RAM（最低可在 2 vCPU / 4 GB RAM 运行，但索引与查询明显更慢）。
- 冷启动（首次 build）：约 3-8 分钟，取决于网络与镜像缓存。
- 热启动（镜像已缓存）：通常 20-60 秒即可达到 `api-ping` 全绿。
- 该模式默认关闭重解析路径，适合做召回/排序离线对比，不适合高并发生产压测。

> Docker 前端默认通过同源 `/api/*` 代理访问后端；浏览器地址由 `NEXT_PUBLIC_API_URL_DOCKER=/` 控制，SSR 容器内地址由 `API_INTERNAL_URL_DOCKER=http://mimirq-api:8000` 控制。`make up-web` 会启动完整 Docker Web 栈，不是“只起前端”；本地热更新前端请使用 `make web`。不要把 Docker 内部主机名暴露给浏览器。

以下解析器都是可选 profile，默认不会启动。请按文档类型选择一个；完整选择矩阵、资源要求和最小 `.env` 配置见根目录 [README](../README.md#可选按文档类型启用解析器)。

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
PADDLE_VL_API_URL=http://mimirq-paddlevl:9030/convert
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
# 包装服务上游（百度千帆在线 OCR）
QIANFAN_OCR_SERVER_URL=https://qianfan.baidubce.com/v2
QIANFAN_OCR_MODEL=deepseek-ocr
QIANFAN_OCR_SERVER_API_KEY=your-qianfan-api-key
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

### (可选) 启用 MagicPDF（独立服务优先）

生产部署建议用 `mimirq-magicpdf` 独立服务，不再依赖 API / worker 镜像内的本地
`magic-pdf` CLI。服务会复用 `mineru_cache` 里的 PDF-Extract-Kit 模型缓存。

```env
MAGIC_PDF_ENABLED=true
MAGIC_PDF_API_URL=http://mimirq-magicpdf:2095/convert
MAGIC_PDF_METHOD=auto
MAGIC_PDF_LANG=ch
MAGIC_PDF_DEVICE_MODE=cuda
MAGIC_PDF_MAX_CONCURRENT_JOBS=1
```

诊断：

```bash
make up-magicpdf
docker compose -f docker/docker-compose.yml exec -T -w /app mimirq-api python scripts/check_parsers.py
```

MagicPDF 在状态为 `configured (service)` 时会通过独立服务解析。默认 API / worker
镜像不会安装依赖版本冲突的 `magic-pdf` CLI；不配置 `MAGIC_PDF_API_URL` 时会显示
`missing cli`。仅自定义镜像或宿主机显式安装了兼容 CLI 与模型时，才使用本地调试兜底。

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
| `magicpdf` | 独立 `mimirq-magicpdf` 服务 + PDF-Extract-Kit 缓存模型 | CUDA 模式需按真实 PDF 单独量测 | 建议独立容器运行并设置 `MAGIC_PDF_DEVICE_MODE=cuda`；本地 CLI 仅作为调试兜底 |
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
make setup-host
make backend-no-reload
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
- 详细依赖状态（需管理员权限）: http://localhost:8000/api/v1/health/details

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

### 使用 Claude / 其他模型替代 OpenAI

MimirQ 通过 **OpenAI 兼容接口** 统一接入所有 LLM，**无需改代码**。将 `LLM_API_BASE` 指向目标模型的 OpenAI 兼容端点（自建网关或第三方兼容服务），并设置 `LLM_MODEL` / `LLM_API_KEY` 即可：

```bash
# .env / 环境变量
LLM_API_BASE=https://your-openai-compatible-gateway/v1
LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=sk-...
```

:::note
MimirQ 不内置 native Anthropic / Gemini SDK，所有模型经 OpenAI 兼容协议接入。若目标服务无兼容端点，需在前置网关（如 LiteLLM、One-API）做协议转换。
:::

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

编辑 `app/core/constants.py`（Milvus 索引/搜索参数集中于此）:

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
