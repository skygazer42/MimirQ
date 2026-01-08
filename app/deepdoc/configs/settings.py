"""
DeepDoc settings.

Copied from the upstream DeepDoc project and lightly extended with a few
backwards-compatible aliases so the vendored parsers keep working in this
repo without relying on extra sys.path tweaks.
"""


import os
from pathlib import Path

# ======== Model path configuration ========

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Allow env override; default to resources/models inside the repo for images/mounts.
MODEL_BASE_DIR = os.getenv(
    "MODEL_BASE_DIR",
    str(_PROJECT_ROOT / "resources" / "models"),
)
# Backwards compatible alias used by some older modules.
MODEL_BASE = MODEL_BASE_DIR

# OCR model path
MODEL_OCR_PATH = os.path.join(MODEL_BASE_DIR, "ocr")

# Layout recognition model path
MODEL_LAYOUT_PATH = os.path.join(MODEL_BASE_DIR, "layout")

# Table recognition model path
MODEL_TABLE_PATH = os.path.join(MODEL_BASE_DIR, "table")

# Ensure model directories exist
os.makedirs(MODEL_OCR_PATH, exist_ok=True)
os.makedirs(MODEL_LAYOUT_PATH, exist_ok=True)
os.makedirs(MODEL_TABLE_PATH, exist_ok=True)

# ======== Hugging Face configuration ========

HF_MODEL_REPO = os.getenv("HF_MODEL_REPO", "InfiniFlow/deepdoc")
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://huggingface.co")

# ======== OCR configuration ========

OCR_DET_THRESHOLD = float(os.getenv("OCR_DET_THRESHOLD", "0.3"))
OCR_REC_THRESHOLD = float(os.getenv("OCR_REC_THRESHOLD", "0.5"))

# ======== PDF processing configuration ========

PDF_DPI = int(os.getenv("PDF_DPI", "200"))
LIGHTEN = int(os.getenv("LIGHTEN", "0"))

# ======== Resource path configuration ========

RESOURCE_DIR = os.path.join(str(_PROJECT_ROOT), "resources")
TOKENIZER_DICT_PATH = os.path.join(RESOURCE_DIR, "data_parser", "qieci")

# Some utilities cache intermediate artifacts here.
DATA_PARSER_DATA = os.getenv("DATA_PARSER_DATA", str(_PROJECT_ROOT / "data"))
os.makedirs(DATA_PARSER_DATA, exist_ok=True)

# ======== Concurrency configuration ========

PARALLEL_DEVICES = int(os.getenv("PARALLEL_DEVICES", "0"))

# ======== Logging configuration ========

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ======== Other configuration ========

TEMP_DIR = os.path.join(os.path.expanduser("~"), ".cache", "deepdoc", "temp")
os.makedirs(TEMP_DIR, exist_ok=True)
