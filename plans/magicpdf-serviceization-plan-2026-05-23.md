# MagicPDF 服务化实施方案（2026-05-23）

## 背景

当前 `MagicPDF` 在 MimirQ 中是“本地 CLI 适配器”模式，而不是独立解析服务：

- 后端在 API/worker 进程内直接调用 `magic-pdf` CLI
- 运行时依赖 API 容器内的 Python 环境、`PATH`、模型目录、CLI 可执行文件同时正确
- 可用性检查主要基于：
  - `MAGIC_PDF_ENABLED`
  - `MAGIC_PDF_CLI`
  - `MAGIC_PDF_MODELS_DIR`

相关代码入口：

- [app/parsing/parsers/magic_pdf_parser.py](/data/temp34/MimirQ/app/parsing/parsers/magic_pdf_parser.py:115)
- [app/parsing/factory.py](/data/temp34/MimirQ/app/parsing/factory.py:246)
- [app/parsing/routing.py](/data/temp34/MimirQ/app/parsing/routing.py:67)
- [app/api/v1/pipeline.py](/data/temp34/MimirQ/app/api/v1/pipeline.py:1085)
- [app/api/v1/settings.py](/data/temp34/MimirQ/app/api/v1/settings.py:1817)

## 已验证问题

### 1. 当前部署边界不稳定

远程实测表明，`docker-mimirq-api-1` 默认 `python` 不是 app venv：

- `/usr/local/bin/python` 下找不到 `langchain_core`
- `/opt/venv/bin/python` 才是 app 正常运行时

这意味着 MagicPDF 现在受“容器默认 Python / PATH”影响，不是纯业务逻辑问题。

### 2. MagicPDF 当前部署态不可运行

在正确 venv 下补测后，真实失败原因是：

- `magic-pdf` CLI 不在 API 容器当前运行时 `PATH`
- 即使模型目录存在，仍会立即失败

证据：

- [plans/remote-test-ledger-2026-05-22.md](/data/temp34/MimirQ/plans/remote-test-ledger-2026-05-22.md:26)
- `artifacts/direct-parser-fixups-144/20260523-021914/magicpdf.log`

### 3. 当前解析器体系已经偏向“独立服务”

现有重型解析器基本都已服务化：

- `marker`
- `paddle_vl`
- `olmocr`
- `mineru`
- `etl4llm`
- `qianfan_ocr`

对应编排文件：

- [docker/docker-compose.parsers.yml](/data/temp34/MimirQ/docker/docker-compose.parsers.yml:1)

`MagicPDF` 继续保留为本地 CLI，是体系上的异类，也会持续制造部署、诊断、资源隔离问题。

## 目标

将 `MagicPDF` 改造成与 `marker / paddle_vl / olmocr` 同类的独立解析服务，要求：

1. API/worker 不再直接依赖本地 `magic-pdf` CLI
2. MagicPDF 模型、CLI、CUDA/CPU 依赖封装在独立镜像中
3. 设置页按“解析服务”方式配置
4. 保留当前 `magicpdf` 解析器名和 API 兼容性
5. 在迁移期兼容旧的本地 CLI 兜底模式

## 2026-05-23 实施进展

已完成第一阶段服务化接线：

- 新增 `docker/magicpdf/` FastAPI 服务，提供 `GET /health` 和 `POST /convert`，容器内调用 `magic-pdf` CLI。
- 新增 Docker profile：`mimirq-magicpdf`，服务地址为 `http://mimirq-magicpdf:2095/convert`。
- 服务镜像切到 CUDA PyTorch 运行时；GPU 服务器默认应使用 `MAGIC_PDF_DEVICE_MODE=cuda`，避免服务化后仍落到 CPU。
- 服务镜像进一步固定到 `torch 2.6.0 + CUDA 12.4`，因为 MagicPDF 1.3.x 官方兼容 `torch 2.2~2.6` 且排除 `2.5`；这也避免了构建时被 `pip` 拉起另一套 `cu13` torch 依赖。
- 服务镜像安装改为 `magic-pdf[full]==1.3.12`，避免只装 core 包时缺少 `cv2` / `doclayout_yolo` 相关运行依赖。
- `/health` 在 `cuda` 模式下检查 `torch.cuda.is_available()`，防止容器 healthy 但实际不可用 GPU。
- 新增配置项：`MAGIC_PDF_API_URL`、`MAGIC_PDF_REQUEST_TIMEOUT_SEC`、`MAGIC_PDF_MAX_CONCURRENT_JOBS`。
- 后端 `MagicPDFParser` 优先走 HTTP 服务模式；未配置服务 URL 时继续回退本地 CLI 模式。
- 工厂、自动路由、parse fallback、pipeline capabilities、settings/status 都已识别服务模式。
- 远程 parser service matrix 已把 requested/resolved backend mismatch 判为失败，避免 HTTP 200 但实际回落 `basic` 被误记为通过。
- `.env.example` 和部署/解析器文档已切到“独立服务优先，本地 CLI 兜底”的说明。

本地验证：

- `pytest -q tests/test_check_parsers_status.py tests/test_parsing_workspace_magicpdf_service.py tests/test_parser_factory_magicpdf.py tests/test_magicpdf_service_parser.py tests/test_magicpdf_service_server.py tests/test_magicpdf_formula_toggle.py tests/test_parsing_routing.py tests/test_settings_endpoints.py`（42 passed）
- `pytest -q tests/test_remote_parser_service_matrix.py tests/test_remote_pdf_parser_performance.py`（5 passed）
- `python -m ruff check ...`
- `git diff --check`
- `docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile magicpdf config --services`

尚未完成：

- 未在远程 GPU 服务器上构建并启动 `mimirq-magicpdf` 镜像。
- 未用真实 PDF 对新服务执行端到端解析测速。
- 图片产物跨容器共享仍按“服务返回 markdown 优先”处理，复杂图片引用场景需要远程实测后决定是否增加共享 artifact volume。

## 目标架构

### 目标模式

```text
MimirQ API/Worker
  -> HTTP 调用 MagicPDF Service
      -> 容器内执行 magic-pdf CLI
      -> 容器内管理模型目录与运行时
      -> 返回 markdown / 产物路径 / 元信息
```

### 服务接口建议

新服务目录建议：

- `docker/magicpdf/`
  - `Dockerfile`
  - `server.py`
  - 可选 `requirements.txt`

建议接口：

- `GET /health`
- `POST /convert`

`POST /convert` 请求字段建议：

- `file`
- `method`: `auto | ocr | txt`
- `lang`
- `debug`
- `device_mode`: `cpu | cuda`
- `keep_artifacts`
- `document_id`

响应建议：

- `markdown`
- `parser_backend=magicpdf`
- `artifact_dir`
- `asset_base_dir`
- `method`
- `elapsed_sec`
- 可选 `stdout_tail`

## 兼容策略

### 一阶段：双模式并存

新增：

- `MAGIC_PDF_API_URL`
- `MAGIC_PDF_REQUEST_TIMEOUT_SEC`
- `MAGIC_PDF_MAX_CONCURRENT_JOBS`

保留：

- `MAGIC_PDF_CLI`
- `MAGIC_PDF_MODELS_DIR`
- `MAGIC_PDF_METHOD`
- `MAGIC_PDF_LANG`
- `MAGIC_PDF_DEVICE_MODE`
- `MAGIC_PDF_KEEP_ARTIFACTS`

运行优先级建议：

1. 如果 `MAGIC_PDF_API_URL` 已配置，优先走 HTTP 服务
2. 否则回退到本地 CLI 模式
3. 如果两者都不可用，则报告 unavailable

### 二阶段：Docker 部署默认服务化

在 Docker 部署场景下：

- 默认启用 `mimirq-magicpdf` 服务 profile
- `MAGIC_PDF_API_URL=http://mimirq-magicpdf:<port>/convert`
- 仅保留 CLI 模式用于本机开发调试

### 三阶段：本地 CLI 降级为调试模式

后续可考虑：

- UI 默认不再暴露 CLI 路径配置
- CLI 模式只在文档或开发开关里保留

## 后端改造点

### 1. 新增 MagicPDF 服务

新增：

- `docker/magicpdf/Dockerfile`
- `docker/magicpdf/server.py`

要求：

- 服务容器内自带 `magic-pdf`
- 模型缓存通过 volume 挂载
- 支持 CPU/GPU 切换
- 支持超时控制
- 支持单服务并发限制

### 2. 后端解析器适配层改造

当前 [magic_pdf_parser.py](/data/temp34/MimirQ/app/parsing/parsers/magic_pdf_parser.py:115) 只有 CLI 模式。

建议改为：

- `MagicPDFParser`
  - 内部根据配置选择：
    - `service mode`
    - `cli mode`

或者拆分为：

- `MagicPDFServiceParser`
- `MagicPDFCliParser`

再由工厂统一封装。

建议优先拆分，原因：

- 责任更清晰
- 服务模式与 CLI 模式失败语义不同
- 测试更容易隔离

### 3. availability / diagnostics 改造

这些位置要一起改：

- [app/parsing/factory.py](/data/temp34/MimirQ/app/parsing/factory.py:246)
- [app/parsing/routing.py](/data/temp34/MimirQ/app/parsing/routing.py:67)
- [app/api/v1/pipeline.py](/data/temp34/MimirQ/app/api/v1/pipeline.py:1085)
- [app/api/v1/settings.py](/data/temp34/MimirQ/app/api/v1/settings.py:1817)

新的可用性判断应区分：

- `service configured`
- `service unreachable`
- `missing cli`
- `missing models`
- `disabled`

不要再把“CLI 和模型存在”当成唯一可用标准。

### 4. artifact / cleanup 复用现有行为

保留现在这套产物语义：

- `artifact_dir`
- `asset_base_dir`
- `MAGIC_PDF_KEEP_ARTIFACTS`

这样不用改下游文档预览、图片引用、入库清理逻辑。

## 前端与设置改造点

### 1. 设置页定位调整

当前 `MagicPDF` 更像“本地解析配置”，但服务化后应放到“高级解析/解析服务”区域。

建议新增字段：

- 服务地址
- 超时
- 设备模式
- 保留产物

`CLI` 路径和模型目录不再作为主配置展示。

### 2. 系统状态页表达调整

系统状态中 `magicpdf` 应区分：

- 已启用但服务不可达
- 已配置可用
- 本地 CLI 模式可用

不要只显示 `available=true/false`。

## Docker 编排改造点

在 [docker/docker-compose.parsers.yml](/data/temp34/MimirQ/docker/docker-compose.parsers.yml:1) 中新增：

- `mimirq-magicpdf`
- profile: `magicpdf`

要求与其它解析器一致：

- `hostname`
- `restart`
- `healthcheck`
- 可选 `gpus: all`
- 模型 cache volume

建议说明：

- `MAGIC_PDF_API_URL=http://mimirq-magicpdf:<port>/convert`
- Docker backend / worker 都走服务地址

## 验证标准

### 单元/集成

至少补这些测试：

1. `magicpdf` availability 在 service mode 下的判断
2. `magicpdf` availability 在 cli mode 下的判断
3. settings 读写 `MAGIC_PDF_API_URL`
4. parse-preview 指定 `magicpdf` 时服务模式能走通
5. 服务不可达时错误信息可读

### 远程实测

最少重新验证两类：

1. 小 PDF smoke
2. 144 页 PDF

验收重点：

- 是否真实返回 `magicpdf`，而不是 fallback 到 `basic`
- 是否能正确产出 markdown
- 是否保留 / 清理产物符合预期

## 资源策略建议

`MagicPDF` 服务化后，也不要默认进入“大 PDF 自动链路”的最高优先级。

建议默认顺序：

- 复杂长 PDF：`mineru / etl4llm / olmocr`
- `magicpdf` 作为可选高级后端
- 只有在实测证明其对目标文档族稳定后，才上升优先级

原因：

- 当前实测已经说明，单“服务化”不会自动解决所有性能问题
- 服务化解决的是部署边界与运维问题，不直接保证长文档吞吐

## 实施顺序

### Phase 1

- 新增 `docker/magicpdf` 服务
- 新增 `MAGIC_PDF_API_URL`
- 打通后端 service mode

### Phase 2

- settings / diagnostics / pipeline availability 改造
- 统一 UI 文案和状态表达

### Phase 3

- 补全测试
- 远程 2 页 / 144 页真实复测
- 更新部署文档

## 验收结论

只有满足以下条件，才能认为 `MagicPDF` 服务化完成：

1. Docker 部署下不再依赖 API 容器本地 `magic-pdf` CLI
2. settings 可配置服务地址并实时反映可用性
3. parse-preview / 入库流程可真实走到 `magicpdf`
4. 小 PDF smoke 通过
5. 144 页 PDF 至少给出明确、稳定、可重复的真实结果

在此之前，不应把当前 `MagicPDF` 视为“已可用解析器”。
