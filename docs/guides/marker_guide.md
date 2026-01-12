# Marker（外部服务）解析器集成

MimirQ 支持将 **Marker** 作为可选 PDF 高级解析后端，通过 **独立服务** 输出 Markdown（可含图片引用）。这种方式不会把 `torch/ocr` 等重依赖塞进 MimirQ 主后端镜像。

## 启用方式

1. 启动 Marker 服务（独立容器/独立机器均可），并确认其提供一个“上传 PDF → 返回 Markdown/ZIP”的 HTTP 接口。

2. 配置后端环境变量（`.env` 或 `docker/.env`）：

```bash
MARKER_ENABLED=true
# 填 Marker 服务的“转换接口完整 URL”（以你的服务为准，常见是 /convert）
MARKER_API_URL=http://mimirq-marker:2080/convert
MARKER_TIMEOUT_SEC=600
```

3. 重启后端服务。

## 使用方式

- 解析预览：在解析工作台选择解析器为 `marker`（也兼容 `marker-pdf` / `marker_pdf`）。
- 入库解析：上传文档时指定 `parser_backend=marker`，或在系统设置中将默认解析器切换为 `marker`（并确保已启用）。

## 产物与清理

- 若 Marker 返回 ZIP（Markdown + images），后端会把产物解压到上传文件同级目录：`.marker/<document_id>/output/...`，并通过 `asset_base_dir` 支持后续图片处理。
- 默认会在预览/入库流程结束后 best-effort 清理 `.marker` 目录；如需保留排查问题，可临时设置 `MAGIC_PDF_KEEP_ARTIFACTS=true`（全局开关）。
