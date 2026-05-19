# MagicPDF（magic-pdf）解析器集成

MimirQ 支持将 **MagicPDF（PyPI: `magic-pdf`）** 作为可选 PDF 高级解析后端，输出 Markdown（可含图片引用），适用于扫描件、复杂排版等场景。

> 注意：`magic-pdf` 依赖较重。Docker backend 镜像会安装 CLI，但本地解析仍需要
> PDF-Extract-Kit 模型缓存。未挂载模型时，系统会明确报告 `missing models`，不会把
> MagicPDF 标成可用。

## 启用方式

1. 安装 `magic-pdf`（源码/本机运行示例；Docker backend 已内置）

```bash
pip install magic-pdf
```

2. 配置后端环境变量（`.env` / `docker/.env`）

```bash
MAGIC_PDF_ENABLED=true
MAGIC_PDF_CLI=magic-pdf
MAGIC_PDF_METHOD=auto   # auto / ocr / txt
MAGIC_PDF_LANG=         # 可选：例如中文 "ch"
MAGIC_PDF_TIMEOUT_SEC=600
MAGIC_PDF_MODELS_DIR=   # 可选；留空时自动查找 /opt/mimirq-model-cache 和 Hugging Face 缓存
MAGIC_PDF_DEVICE_MODE=cpu  # cpu / cuda
MAGIC_PDF_KEEP_ARTIFACTS=false
```

3. Docker 部署时挂载模型缓存

`docker/docker-compose.yml` 会把 `mineru_cache` 挂到 API / worker 的
`/opt/mimirq-model-cache:ro`。推荐先启动一次本地 MinerU 服务下载/填充
PDF-Extract-Kit 模型缓存，再启用 MagicPDF：

```bash
make up-mineru
docker compose -f docker/docker-compose.yml up -d --build mimirq-api mimirq-worker
```

MagicPDF 1.3.x 本地 CPU 解析至少需要模型目录中存在：

- `Layout/YOLO/doclayout_yolo_docstructbench_imgsz1280_2501.pt`
- `OCR/paddleocr_torch/ch_PP-OCRv3_det_infer.pth`
- `OCR/paddleocr_torch/ch_PP-OCRv5_rec_infer.pth`

4. 重启后端

```bash
uvicorn app.main:app --reload
```

## 诊断与验证

```bash
docker compose -f docker/docker-compose.yml exec -T -w /app mimirq-api python scripts/check_parsers.py
```

期望 MagicPDF 行为：

- `disabled`：未开启 `MAGIC_PDF_ENABLED`
- `missing cli`：镜像/运行环境没有 `magic-pdf` 可执行文件
- `missing models`：CLI 存在，但没有挂载/配置完整 PDF-Extract-Kit 模型
- `configured (models: ...)`：CLI 与模型都可用，可继续做真实上传解析验证

## 使用方式

- 解析预览：前端“解析工作台”选择解析器为 `magicpdf`（也兼容 `magic-pdf` / `magic_pdf`）。
- 入库解析：上传文档时指定 `parser_backend=magicpdf`，或在系统设置中将默认解析器切换为 `magicpdf`（并确保已启用）。

## 产物与清理

- MagicPDF 会在上传文件同级目录下生成解析产物目录：`.magicpdf/<document_id>/...`（用于临时读取解析出的图片等资源）。
- 默认会在入库流程完成后 best-effort 清理该目录；如需保留用于排查问题，设置 `MAGIC_PDF_KEEP_ARTIFACTS=true`。
