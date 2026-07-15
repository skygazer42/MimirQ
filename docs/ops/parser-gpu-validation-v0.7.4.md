# 文档解析 GPU 验证记录（v0.7.4）

## 范围

- 基线：`v0.7.3`（`0ee6b525b62bdcb2998527ff2c01804113377387`）。
- 发布目标：`v0.7.4`。
- 硬件：NVIDIA RTX A6000 48GB，Docker GPU runtime。
- 方法：每个后端至少处理一份真实上传的 PDF，并要求返回非空正文；服务后端同时验证原生 API 和 MimirQ `ParserFactory` 入口。GPU OCR 路径额外处理一份无字体、仅含扫描图像的 PDF。
- 隔离：测试镜像、容器、端口和目录均与既有部署隔离；验证结束后测试容器全部删除，既有服务未重启。

这是一轮运行可用性验证，不是解析准确率基准。字符数和耗时仅用于证明请求实际完成，不能跨文档比较模型质量。

## 修复结论

| 问题 | 根因 | 修复 | 验证 |
| --- | --- | --- | --- |
| ColPali 声明支持 PDF 但无法选择 | `ParserFactory` 缺少 `colpali` 路由 | 接入已有 `_get_colpali_parser()` | 工厂返回 `colpali` 视觉文档引用 |
| MagicPDF 健康检查假绿 | 长期运行进程缓存了旧 CUDA 状态 | 同时校验 PyTorch CUDA 与 `nvidia-smi -L` | 新镜像健康检查、CUDA 和真实转换同时通过 |
| MagicPDF 镜像重建失败 | `stringzilla` 解析到无可用 wheel 的版本 | 固定到 `4.6.1` binary wheel | 镜像 `07833f7a...` 构建成功 |
| MinerU pipeline 返回 409 | 程序漂移到 3.4.4，缓存仍按 OCRv4 文件判定就绪 | 固定 `mineru[core]==3.4.4`，按 OCRv6、布局、公式和表格文件判断就绪 | 最终镜像 pipeline 文本 PDF 与扫描 PDF 均通过 |
| MinerU VLM 仍指向旧模型仓库 | 3.4.4 已切换到 `MinerU2.5-Pro-2605-1.2B` | 更新仓库路径，并要求配置、权重和预处理配置完整 | 最终镜像 VLM 文本 PDF 与扫描 PDF 均通过 |

最终 MinerU 镜像为 `31f51a0f...`，镜像内版本确认为 `3.4.4`。

## 模型与缓存

| 用途 | 仓库/版本 | 已验证快照 |
| --- | --- | --- |
| MimirQ DeepDoc 本地模型包 | `qwqqwq/mimirq` | `118452f3ea3ccd09a41b2d39ea82d7de535e2908` |
| MinerU pipeline | `opendatalab/PDF-Extract-Kit-1.0` | `ed6b654c018d742e65a17671e379c5e6ecc87ec9` |
| MinerU VLM | `opendatalab/MinerU2.5-Pro-2605-1.2B` | `bff20d4ae2bf202df9f45284b4d43681555a97ed` |

修复后的启动检查对 pipeline 和 VLM 均返回 `True`。仓库继续不跟踪模型权重，部署时写入 Docker 模型卷。

## 后端矩阵

| 后端 | 结果 | 输出 | 耗时 | 验证路径 |
| --- | --- | ---: | ---: | --- |
| `basic` | 通过 | 437 字 | 1.7s | MimirQ API |
| `deepdoc` | 通过 | 534 字 | 13.9s | 下载模型包后的独立源码运行 |
| `docling` | 通过 | 544 字 | 26s | 独立源码运行；冷启动 API 首次为 323s |
| `markitdown` | 通过 | 373 字 | 1.1s | 独立源码运行 |
| `etl4llm` | 通过 | 398 字 | 0.6s | MimirQ 适配器 |
| `marker` | 通过 | 371 字 | 6.9s | 新镜像 + MimirQ 适配器 |
| `paddle_vl` | 通过 | 374 字 | 15.1s | CUDA `gpu:0` + MimirQ 适配器 |
| `olmocr` | 通过 | 371 字 | 251s | 7B FP8 模型 + MimirQ 适配器 |
| `qianfan_ocr` | 通过 | 400 字 | 4.3s | 新镜像 + MimirQ 适配器 |
| `textin` | 通过 | 374 字 | 6.5s | MimirQ 适配器 |
| `magicpdf` | 通过 | 428 字 | 19.2s | CUDA 新镜像 + MimirQ 适配器 |
| `mineru` pipeline | 通过 | 421 字 | 18s | 最终镜像原生 API；适配器另行通过 |
| `mineru` VLM HTTP | 通过 | 421 字 | 12s | 最终镜像原生 API；适配器另行通过 |
| `colpali` | 通过 | 视觉引用 | <1s | 路由与引用契约；该后端不是文本 OCR 推理器 |

## 扫描 PDF

扫描样本只有一张 920x1180 灰度图像，PDF 中无字体对象。三条最终 GPU 路径均识别出 `Mixed scan synthesis should appear after both columns` 和 `Escalate the Jakarta handoff on Tuesday` 等正文：

| 后端 | 状态 | 输出 | 耗时 |
| --- | --- | ---: | ---: |
| MinerU pipeline OCR | `completed` | 215 字 | 18s |
| MinerU VLM HTTP | `completed` | 213 字 | 11s |
| MagicPDF OCR/CUDA | HTTP 200 | 227 字 | 23s |

## 外部条件

- `deepseek_ocr` 请求已到达外部服务，但返回账户余额不足的 403；本轮无法声明该外部账号可用，也不属于本地模型故障。
- `glm_ocr` 未启用且未配置服务 URL，API 按设计返回 400；本轮不声明可用。
- 外部服务的凭据未写入源码、报告或测试产物。

## 证据与清理

远端原始证据位于 `/data/MimirQ-v0.7.3-gpu-test/artifacts/gpu-parser-validation/`，包括镜像构建日志、健康响应和各后端输出。验证结束状态：

- `mimirq-test-*` 容器数量为 0。
- GPU 无测试进程残留。
- 既有 MimirQ API、worker、数据库、对象存储和解析服务仍保持原运行状态。
