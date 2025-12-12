"""
DeepDoc settings.

Copied from the upstream DeepDoc project and lightly extended with a few
backwards-compatible aliases so the vendored parsers keep working in this
repo without relying on extra sys.path tweaks.
"""

from __future__ import annotations

import os
from pathlib import Path

# ======== 模型路径配置 ========

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 允许通过环境变量覆盖，默认写到仓库内的 resources/models，便于镜像/挂载
MODEL_BASE_DIR = os.getenv(
    "MODEL_BASE_DIR",
    str(_PROJECT_ROOT / "resources" / "models"),
)
# Backwards compatible alias used by some older modules.
MODEL_BASE = MODEL_BASE_DIR

# OCR 模型路径
MODEL_OCR_PATH = os.path.join(MODEL_BASE_DIR, "ocr")

# 布局识别模型路径
MODEL_LAYOUT_PATH = os.path.join(MODEL_BASE_DIR, "layout")

# 表格识别模型路径
MODEL_TABLE_PATH = os.path.join(MODEL_BASE_DIR, "table")

# 确保模型目录存在
os.makedirs(MODEL_OCR_PATH, exist_ok=True)
os.makedirs(MODEL_LAYOUT_PATH, exist_ok=True)
os.makedirs(MODEL_TABLE_PATH, exist_ok=True)

# ======== Hugging Face 配置 ========

HF_MODEL_REPO = os.getenv("HF_MODEL_REPO", "InfiniFlow/deepdoc")
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://huggingface.co")

# ======== OCR 配置 ========

OCR_DET_THRESHOLD = float(os.getenv("OCR_DET_THRESHOLD", "0.3"))
OCR_REC_THRESHOLD = float(os.getenv("OCR_REC_THRESHOLD", "0.5"))

# ======== PDF 处理配置 ========

PDF_DPI = int(os.getenv("PDF_DPI", "200"))
LIGHTEN = int(os.getenv("LIGHTEN", "0"))

# ======== 资源路径配置 ========

RESOURCE_DIR = os.path.join(str(_PROJECT_ROOT), "resources")
TOKENIZER_DICT_PATH = os.path.join(RESOURCE_DIR, "data_parser", "qieci")

# Some utilities cache intermediate artifacts here.
DATA_PARSER_DATA = os.getenv("DATA_PARSER_DATA", str(_PROJECT_ROOT / "data"))
os.makedirs(DATA_PARSER_DATA, exist_ok=True)

# ======== 并发配置 ========

PARALLEL_DEVICES = int(os.getenv("PARALLEL_DEVICES", "0"))

# ======== 日志配置 ========

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ======== 其他配置 ========

TEMP_DIR = os.path.join(os.path.expanduser("~"), ".cache", "deepdoc", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

