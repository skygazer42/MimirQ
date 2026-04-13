# Qianfan-OCR（外部 OCR 服务）解析器集成

MimirQ 支持将 **Qianfan-OCR** 作为可选 PDF OCR 解析后端，通过 **独立服务** 输出 Markdown。
该模式将模型推理与主后端解耦，避免把 `vllm/torch/transformers` 等重依赖塞进 MimirQ 主镜像。

> `docker/qianfanocr` 是一个轻量包装服务：负责 PDF 分页渲染、调用上游 OpenAI-compatible 视觉接口并汇总 Markdown。实际模型推理在你配置的上游服务中完成。

资源说明（当前仓库实测）：

- 本地 `qianfanocr` 容器本身没有观测到本地 GPU 分配
- 它主要承担 **PDF 分页 + 请求编排 + Markdown 汇总**
- 真正的显存压力在你配置的**上游视觉推理服务**，请按上游模型单独评估

## 启用方式

1. 启动 Qianfan-OCR 包装服务（独立容器/独立机器均可）。
   - 使用本项目 Docker Compose：`make up-qianfanocr`
   - 等价命令：

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile qianfanocr up -d --build
```

2. 配置包装服务上游（写在 `docker/.env`）：

```bash
# 上游 OpenAI-compatible 视觉推理地址（示例）
QIANFAN_OCR_SERVER_URL=http://host.docker.internal:8000/v1
QIANFAN_OCR_SERVER_API_KEY=
QIANFAN_OCR_MODEL=baidu/Qianfan-OCR
```

3. 配置 MimirQ 后端解析器（`.env` 或 `docker/.env`）：

```bash
QIANFAN_OCR_ENABLED=true
QIANFAN_OCR_API_URL=http://mimirq-qianfanocr:2090/convert
QIANFAN_OCR_TIMEOUT_SEC=1800
# 可选：请求 Layout-as-Thought 模式
QIANFAN_OCR_LAYOUT_AS_THOUGHT=false
```

4. 重启后端服务。

## 使用方式

- 解析预览：在解析工作台选择 `qianfan_ocr`（也兼容 `qianfan-ocr` / `qianfanocr`）。
- 入库解析：上传文档时指定 `parser_backend=qianfan_ocr`，或在系统设置中将默认解析器切换为 `qianfan_ocr`（并确保已启用）。

## Layout-as-Thought 说明

- 包装服务支持通过 `layout_as_thought=true` 请求该模式。
- 若模型需要特殊触发 token，请在服务侧设置：

```bash
QIANFAN_OCR_LAYOUT_TRIGGER=
```

- 为避免模型版本差异导致行为不一致，默认不强制注入固定 token。

## 服务侧可选参数（`docker/.env`）

```bash
QIANFAN_OCR_MAX_CONCURRENT_JOBS=1
QIANFAN_OCR_PAGE_CONCURRENCY=1
QIANFAN_OCR_REQUEST_TIMEOUT_SEC=120
QIANFAN_OCR_PDF_DPI=200
QIANFAN_OCR_PROMPT=
```

## 产物与清理

- 后端会将本次解析结果 best-effort 落盘在上传文件同级目录：`.qianfan_ocr/<document_id>/result.md`（用于排障/复现）。
- 入库流程会对解析器产物目录做 best-effort 清理；如需保留排查问题，可临时设置 `MAGIC_PDF_KEEP_ARTIFACTS=true`（全局开关）。
