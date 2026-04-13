# PaddleOCR-VL (外部服务) 集成指南

MimirQ 支持把 **PaddleOCR-VL** 作为可选的 PDF OCR/版面解析后端，通过 **独立服务** 输出 Markdown（建议返回 ZIP：markdown + images + json）。
这样可以避免把 `paddlepaddle/paddleocr` 这类重依赖塞进 MimirQ 主后端镜像。

## 1) 启动 PaddleOCR-VL 服务（本仓库自带 Docker 服务）

本仓库 `docker/paddlevl` 封装了 PaddleOCR 的 `doc_parser`（默认 `v1.5`）并暴露两个接口：

- `GET /health`：返回 `{ ok, mode, pipeline_version, device }`
- `POST /convert`：上传 PDF（multipart/form-data，字段名 `file`），返回 `application/zip`
  - 额外表单字段（可选）：`pipeline_version`、`device`

启动方式（推荐）：

```bash
make up-paddlevl
# 等价：
# docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile paddlevl up -d --build
```

服务侧可配置环境变量（见 `docker/docker-compose.parsers.yml`）：

```bash
PADDLEOCR_PIPELINE_VERSION=v1.5
PADDLEOCR_DEVICE=gpu:0
```

备注：
- 当前 `docker/paddlevl` 默认使用官方 `paddleocr-vl:latest-nvidia-gpu` 基础镜像，并通过 Compose 的 `gpus: all` 暴露本机 GPU。
- 这条默认链路是 **GPU 优先** 的；如果你明确想切回 CPU，可把 `PADDLEOCR_DEVICE` 改为 `cpu`。
- Paddle 官方安装/镜像链路目前优先覆盖 CUDA 12.6 / 12.9 等已发布支持组合；若你强制要求精确的 CUDA 12.8，自定义基础镜像/轮子组合需要额外兼容性验证。

显存说明（当前仓库实测）：

- 当前验证流在 RTX A6000 上观测到 **约 8.2 GiB** 本地 GPU 峰值
- 实际部署建议至少预留 **10 GiB** 可用显存
- 如果同卡还有别的常驻进程，请按“现有占用 + 8.2 GiB + 安全余量”估算

## 2) 配置 MimirQ 后端

在 MimirQ 后端环境变量（`.env`）中启用：

```bash
PADDLE_VL_ENABLED=true
PADDLE_VL_API_URL=http://127.0.0.1:9030/convert
PADDLE_VL_TIMEOUT_SEC=600
```

## 3) 使用方式

- 解析预览：在「解析工作台」选择 `paddle_vl`（也兼容 `paddle-vl` / `paddleocr-vl` / `paddleocrvl`）。
- 入库解析：上传/导入文档时指定 `parser_backend=paddle_vl`，或在系统设置中把默认解析器切换为 `paddle_vl`（并确保已启用与配置 URL）。

## 4) 产物、图片与清理策略

当 PaddleOCR-VL 服务返回 ZIP 时：

- MimirQ 会把 ZIP 解压到 `.paddlevl/<run_id>/output/`，并将其 **归一化** 为稳定结构：
  - `result.md`
  - `images/`（可选）
- 当 `MINIO_ENABLED=true` 且存在 `dataset_id/document_id` 时，MimirQ 会上传 ZIP 内的图片到 MinIO，并把 Markdown 内的图片引用改写为可访问的 URL。
- 当 `MINIO_ENABLED=false` 时，为避免产物清理后出现死链，MimirQ 会在入库文本中移除 `![](...)` 和 `<img ...>` 引用（保留纯文本）。

清理策略：
- 默认会在流程结束后 best-effort 清理 `.paddlevl` 等解析器产物目录。
- 若需要保留产物用于排障，可临时开启 `MAGIC_PDF_KEEP_ARTIFACTS=true`（全局调试开关，会影响多个解析器）。

## 5) 排障建议

- `系统 → 设置 → 连接状态（/api/v1/settings/status）` 可以看到 `paddle_vl` 的可用性与 `/health` 探测结果（包含 pipeline_version）。
- 当前推荐让 PaddleOCR-VL 容器跑在 共享后端网络命名空间；后端容器通过 `http://127.0.0.1:9030/convert` 访问它。
