# MagicPDF（magic-pdf）解析器集成

MimirQ 支持将 **MagicPDF（PyPI: `magic-pdf`）** 作为可选 PDF 高级解析后端，输出 Markdown，适用于扫描件、复杂排版等场景。

> 生产部署推荐使用独立 `mimirq-magicpdf` 服务。旧的 API/worker 容器内本地 CLI 模式仍保留为开发/调试兜底，但不再是 Docker 推荐路径。

## 启用方式

### 推荐：独立服务模式

1. 启动 MagicPDF 服务：

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile magicpdf up -d --build
```

2. 配置根目录 `.env`：

```bash
MAGIC_PDF_ENABLED=true
MAGIC_PDF_API_URL=http://mimirq-magicpdf:2095/convert
MAGIC_PDF_REQUEST_TIMEOUT_SEC=600
MAGIC_PDF_MAX_CONCURRENT_JOBS=1
MAGIC_PDF_METHOD=auto   # auto / ocr / txt
MAGIC_PDF_LANG=         # 可选：例如中文 "ch"
MAGIC_PDF_DEVICE_MODE=cuda # GPU 服务器建议 cuda；无 GPU/本地调试改 cpu
MAGIC_PDF_PIPELINE_TIMEOUT_SEC=600
MAGIC_PDF_KEEP_ARTIFACTS=false
```

`mimirq-magicpdf` 镜像使用 CUDA PyTorch 运行时；如果服务器有 NVIDIA GPU，
不要把 `MAGIC_PDF_DEVICE_MODE` 留在 `cpu`，否则会复现“服务起来了但解析很慢”的问题。
`/health` 会在 `cuda` 模式下检查 `torch.cuda.is_available()`，CUDA 不可用时服务不会被标记为 healthy。
服务镜像当前固定到 `torch 2.6 + CUDA 12.4`，因为 MagicPDF 1.3.x 官方兼容区间是
`torch 2.2~2.6`，并明确排除了 `2.5`。
镜像安装的是 `magic-pdf[full]`，不是最小 core 包；否则 `doclayout_yolo` 路径会缺少
`cv2` 等运行依赖。
如果共享的 PDF-Extract-Kit cache 只有 `ch_PP-OCRv5_rec_infer.pth` 而没有
`ch_PP-OCRv4_rec_server_doc_infer.pth`，服务会在启动/执行时把 MagicPDF 的
`lang.ch` 资源映射自动切到现有 `v5` 识别模型。

3. 重启 API/worker，让它们读取新的服务 URL：

```bash
docker compose -f docker/docker-compose.yml up -d --build mimirq-api mimirq-worker
```

### 兜底：本地 CLI 模式

如果不配置 `MAGIC_PDF_API_URL`，后端会回退到 API/worker 本地 CLI 模式。此模式需要：

```bash
MAGIC_PDF_ENABLED=true
MAGIC_PDF_API_URL=
MAGIC_PDF_CLI=magic-pdf
MAGIC_PDF_TIMEOUT_SEC=600
MAGIC_PDF_MODELS_DIR=   # 可选；留空时自动查找 /opt/mimirq-model-cache 和 Hugging Face 缓存
MAGIC_PDF_DEVICE_MODE=cpu
```

本地 CLI 模式仍要求 `magic-pdf` CLI 与 PDF-Extract-Kit 模型缓存同时可用。

## 模型缓存

`docker/docker-compose.parsers.yml` 会把 `mineru_cache` 挂到 `mimirq-magicpdf` 的
`/opt/mimirq-model-cache:ro`。推荐先启动一次本地 MinerU 服务下载/填充 PDF-Extract-Kit 模型缓存，再启用 MagicPDF：

```bash
make up-mineru
docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile magicpdf up -d --build
```

MagicPDF 1.3.x 本地 CPU 解析至少需要模型目录中存在：

- `Layout/YOLO/doclayout_yolo_docstructbench_imgsz1280_2501.pt`
- `OCR/paddleocr_torch/ch_PP-OCRv3_det_infer.pth`
- `OCR/paddleocr_torch/ch_PP-OCRv5_rec_infer.pth`

4. 重启后端

```bash
make backend
```

如果宿主机文件监听额度较低、`uploads/` 目录较大导致热重载失败，可改用：

```bash
make backend-no-reload
```

## 诊断与验证

```bash
docker compose -f docker/docker-compose.yml exec -T -w /app mimirq-api python scripts/check_parsers.py
```

期望 MagicPDF 行为：

- `disabled`：未开启 `MAGIC_PDF_ENABLED`
- `configured (service)`：已配置 `MAGIC_PDF_API_URL`，API/worker 会调用独立服务
- `missing cli`：镜像/运行环境没有 `magic-pdf` 可执行文件
- `missing models`：CLI 存在，但没有挂载/配置完整 PDF-Extract-Kit 模型
- `configured (models: ...)`：本地 CLI 与模型都可用，可继续做真实上传解析验证

## 使用方式

- 解析预览：前端“解析工作台”选择解析器为 `magicpdf`（也兼容 `magic-pdf` / `magic_pdf`）。
- 入库解析：上传文档时指定 `parser_backend=magicpdf`，或在系统设置中将默认解析器切换为 `magicpdf`（并确保已启用）。

## 产物与清理

- 服务模式下，MagicPDF 服务会在容器内生成临时解析产物，并返回 Markdown 给 API/worker。
- 本地 CLI 模式会在上传文件同级目录下生成解析产物目录：`.magicpdf/<document_id>/...`。
- 默认会在解析完成后清理临时产物或由入库流程 best-effort 清理；如需保留用于排查问题，设置 `MAGIC_PDF_KEEP_ARTIFACTS=true`。
