# PaddleOCR-VL（外部服务）解析器集成

MimirQ 支持将 **PaddleOCR-VL** 作为可选 PDF OCR/版面解析后端，通过 **独立服务** 输出 Markdown（建议返回 ZIP：Markdown + JSON + images）。这种方式避免把 `paddlepaddle/paddleocr` 等重依赖塞进 MimirQ 主后端镜像。

## 启用方式

1. 启动 PaddleOCR-VL 服务（独立容器/独立机器均可），并确认其提供一个“上传 PDF → 返回 Markdown/ZIP”的 HTTP 接口（示例：`/convert`）。
   - 使用本项目 Docker Compose：`make up-paddlevl`（等价于 `docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile paddlevl up -d --build`）

2. 配置后端环境变量（`.env` 或 `docker/.env`）：

```bash
PADDLE_VL_ENABLED=true
# 填 PaddleOCR-VL 服务的“转换接口完整 URL”（以你的服务为准，常见是 /convert）
PADDLE_VL_API_URL=http://mimirq-paddlevl:9030/convert
PADDLE_VL_TIMEOUT_SEC=600
```

3. 重启后端服务。

## 使用方式

- 解析预览：在解析工作台选择解析器为 `paddle_vl`（也兼容 `paddle-vl` / `paddleocr-vl` / `paddleocrvl`）。
- 入库解析：上传文档时指定 `parser_backend=paddle_vl`，或在系统设置中将默认解析器切换为 `paddle_vl`（并确保已启用）。

## 产物与清理

- 若服务返回 ZIP，后端会把产物解压到上传文件同级目录：`.paddlevl/<document_id>/output/...`，并对 PaddleOCR-VL 的输出做标准化（统一 `images/`、合并 `result.json`、重写图片引用等）。
- 默认会在预览/入库流程结束后 best-effort 清理 `.paddlevl` 目录；如需保留排查问题，可临时设置 `MAGIC_PDF_KEEP_ARTIFACTS=true`（全局开关）。
