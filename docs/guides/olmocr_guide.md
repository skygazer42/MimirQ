# olmOCR（外部 OCR 服务）解析器集成

MimirQ 支持将 **olmOCR** 作为可选 PDF OCR 解析后端，通过 **独立服务** 输出 Markdown。这种方式避免把 `vllm/torch` 等重依赖塞进 MimirQ 主后端镜像。

> olmOCR 通常需要 NVIDIA GPU；模型体积较大，首次启动会有明显下载/预热时间。

显存说明（当前仓库实测）：

- 当前验证流在 RTX A6000 上观测到 **约 43.7 GiB** 本地 GPU 峰值
- 实际部署建议至少预留 **44 GiB** 可用显存
- 基本可以视为 **48G 级单卡独占** 场景，不建议与其它重 parser 混跑
- 当前 rebuilt runtime 验证里，单次 preview 级请求耗时约 **151 秒**

## 启用方式

1. 启动 olmOCR 服务（独立容器/独立机器均可），并确认其提供一个“上传 PDF → 返回 Markdown”的 HTTP 接口（示例：`/convert`）。
   - 使用本项目 Docker Compose：`make up-olmocr`（等价于 `docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile olmocr up -d --build`）

2. 配置后端环境变量（`.env` 或 `docker/.env`）：

```bash
OLMOCR_ENABLED=true
# 填 olmOCR 服务的“转换接口完整 URL”（以你的服务为准，常见是 /convert）
OLMOCR_API_URL=http://127.0.0.1:2085/convert
OLMOCR_TIMEOUT_SEC=1800
```

3. 重启后端服务。

## 使用方式

- 解析预览：在解析工作台选择解析器为 `olmocr`（也兼容 `olm-ocr` / `olmocr-pdf` / `olmocr_pdf`）。
- 入库解析：上传文档时指定 `parser_backend=olmocr`，或在系统设置中将默认解析器切换为 `olmocr`（并确保已启用）。

## 服务侧配置（可选）

`docker/docker-compose.parsers.yml` 的 `olmocr` profile 支持以下可选环境变量（写在 `docker/.env`）：

```bash
# 服务侧并发（单卡建议 1）
OLMOCR_MAX_CONCURRENT_JOBS=1
# 单次 pipeline 超时（秒）
OLMOCR_PIPELINE_TIMEOUT_SEC=1800

# 可选：使用外部 OpenAI-compatible 推理服务（例如 vLLM 在另一台机器上），避免容器内起 vLLM
OLMOCR_SERVER_URL=
OLMOCR_API_KEY=
OLMOCR_MODEL=
```

## 产物与清理

- 后端会将本次解析结果 best-effort 落盘在上传文件同级目录：`.olmocr/<document_id>/result.md`（用于排障/复现）。
- 入库流程会对解析器产物目录做 best-effort 清理；如需保留排查问题，可临时设置 `MAGIC_PDF_KEEP_ARTIFACTS=true`（全局开关）。
