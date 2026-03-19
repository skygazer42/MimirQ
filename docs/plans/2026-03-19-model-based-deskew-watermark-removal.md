# 模型驱动的文档图像预处理：几何矫正 + 去水印

> 基于 2026-03-19 代码审计。聚焦解析管线的前处理阶段：用模型推理替代传统 OpenCV 算法做切边矫正、畸变校正、水印去除。

---

## 现状

经代码审计，MimirQ 目前的图像预处理能力非常有限：

| 能力 | 状态 | 位置 |
|------|------|------|
| 单文字框透视矫正 | 有（DeepDoc OCR 内部） | `app/deepdoc/vision/ocr.py` `get_rotate_crop_image()` |
| EXIF 方向处理 | 有 | `app/deepdoc/vision/operators.py` `DecodeImage` |
| **页面级几何矫正（deskew/dewarp）** | **无** | — |
| **水印去除（像素级）** | **无** | — |
| 水印标记去除（文本级） | 有（仅去 Markdown 图片标签） | `app/rag/preprocessing/images.py` `strip_images()` |
| **去噪/对比度增强** | **无** | — |
| **页面方向检测（0/90/180/270）** | **无** | — |

行业标杆表明，模型驱动的预处理可提升 OCR 准确率 15-30%。

---

## 为什么不用 OpenCV 传统算法

| 方面 | OpenCV 传统算法 | 模型推理 |
|------|----------------|---------|
| 倾斜矫正 | Hough Line 只能处理简单旋转，对弯曲/透视/非平面变形无效 | DocTr/GeoTr 学习像素级 displacement field，可处理弯曲、折叠、透视等复杂畸变 |
| 水印检测 | 基于颜色阈值，对半透明水印、与正文颜色接近的水印效果差 | Florence-2 开放词汇检测，能识别文字水印、logo 水印、半透明叠加层 |
| 水印去除 | `cv2.inpaint(TELEA)` 对大面积区域修复效果差，纹理不自然 | LaMa 使用快速傅里叶卷积，修复后纹理自然、分辨率鲁棒 |
| OCR 增强 | 自适应二值化对低质量图片反而引入噪声 | PaddleOCR-VL 1.5 内置 distortion-aware 数据增强，94.5% 准确率 |

---

## 模块 1: 几何矫正 -- DocTr/GeoTr + PaddleOCR

**新增文件**: `app/parsing/preprocess/deskew.py`

**模型选择（按优先级）：**

1. **首选 -- PaddleOCR 预处理管线**（如果已部署 PaddleOCR 服务）
   - PaddleOCR 3.x 自带 `doc_orientation_classify`（方向分类）+ `doc_unwarp`（畸变矫正，基于 UVDoc）
   - 与现有 PaddleOCR-VL 集成共享服务，无需额外部署

2. **备选 -- DocTr GeoTr**（独立部署）
   - 通过 OnnxTR（ONNX Runtime 推理），模型约 100MB
   - CER 从 35% 降低到 20%

3. **兜底 -- VLM 内置鲁棒性**
   - PaddleOCR-VL 1.5 在含倾斜/弯曲/光照场景下 92.05% 准确率
   - 轻微倾斜（< 5度）可依赖 VLM 不做矫正

---

## 模块 2: 水印检测与去除 -- Florence-2 + LaMa

**新增文件**: `app/parsing/preprocess/watermark.py`

**检测**: Florence-2-base (230M) open-vocabulary detection, prompt = "watermark"。也可用 VLM API（SiliconFlow/Ollama）免部署，或 fine-tuned YOLO v8 (30ms/image)。

**去除**: LaMa Inpainting (~196MB)，CPU 3-5秒/张，GPU 加速 40%+。

**原生 PDF 优化**: 先用 PyMuPDF 检测/删除 XObject/Annotation 层水印（零成本），仅对烘焙在内容层的水印走模型。

**跨页一致性**: 同一位置多页重复出现 → 高置信度水印 → 全页统一处理。

---

## 模块 3: 页面方向分类

**新增文件**: `app/parsing/preprocess/orientation.py`

PaddleOCR `doc_orientation_classify`（4 类: 0/90/180/270度）或 Tesseract OSD（无 GPU）。

---

## 模块 4: 模型加载与管理

**新增文件**: `app/parsing/preprocess/model_loader.py`

按需加载 + singleton 缓存 + ONNX Runtime 推理 + 支持外部 API 端点。

---

## 模块 5: Pipeline 集成

**新增文件**: `app/parsing/preprocess/image_preprocess.py`

插入位置: `FilePreprocessStage → ImagePreprocessStage(新增) → ParsingStage → ...`

智能跳过: 高质量原生 PDF (score >= 0.8, not scanned) 跳过全部预处理。

---

## 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `IMAGE_PREPROCESS_ENABLED` | `True` | 总开关 |
| `DESKEW_ENABLED` | `True` | 几何矫正 |
| `DESKEW_BACKEND` | `"auto"` | `auto` / `paddle` / `doctr` / `skip` |
| `DESKEW_PADDLE_URL` | `""` | PaddleOCR 预处理服务地址 |
| `DESKEW_DOCTR_MODEL` | `"fh2019ustc/DocTr"` | DocTr 模型路径/ID |
| `DESKEW_MIN_VARIANCE` | `0.01` | displacement 方差阈值 |
| `ORIENTATION_ENABLED` | `True` | 页面方向检测 |
| `WATERMARK_REMOVAL_ENABLED` | `False` | 水印去除（默认关闭） |
| `WATERMARK_DETECTOR` | `"florence2"` | `florence2` / `yolo` / `vlm_api` |
| `WATERMARK_DETECTOR_MODEL` | `"microsoft/Florence-2-base"` | 检测模型 |
| `WATERMARK_INPAINTER` | `"lama"` | 修复模型 |
| `WATERMARK_INPAINTER_MODEL` | `"advimman/lama"` | LaMa 模型路径 |
| `WATERMARK_VLM_API_URL` | `""` | VLM API 做水印检测（免部署） |
| `PREPROCESS_SKIP_HIGH_QUALITY` | `True` | 高质量 PDF 跳过 |
| `PREPROCESS_SAMPLE_PAGES` | `3` | 采样检测页数 |

水印去除默认关闭：水印可能是有意义的标记（"机密"/"草稿"）。

---

## 依赖

所有模型依赖可选：`pip install mimirq[preprocess]`

| 依赖 | 用途 | 大小 |
|------|------|------|
| `onnxruntime` | DocTr/LaMa ONNX 推理 | ~50MB |
| `transformers` + Florence-2 | 水印检测 | ~500MB |
| `lama-cleaner` | 水印修复 | ~196MB |
| `opencv-python` | 基础图像操作 | 已有 |
| `PyMuPDF` | PDF 渲染/重组 | 已有 |

---

## 质量评分增强

`score_pdf_quality` 增加 `preprocess_info` 字段：skew_angle / orientation / watermark_detected / watermark_regions / geometric_distortion。路由决策可利用这些信息。

---

## 涉及文件汇总

**新增**: `app/parsing/preprocess/deskew.py`, `watermark.py`, `orientation.py`, `image_preprocess.py`, `model_loader.py`

**修改**: `app/parsing/processors/processor.py`, `app/core/config.py`, `app/parsing/quality/scorer.py`

---

## 建议实施顺序

**Phase 1 (1 周)**: 方向分类 + 几何矫正 + Pipeline 集成框架 + 配置项

**Phase 2 (1 周)**: 水印检测(Florence-2/VLM API) + 去除(LaMa) + PyMuPDF 优化路径

**Phase 3 (3-5 天)**: 模型加载管理 + 质量评分增强 + 智能跳过优化
