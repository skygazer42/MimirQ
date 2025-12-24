"""
PDF 质量评分工具：用于决定解析分流（干净 PDF 走 MarkItDown/基础解析，复杂 PDF 走 DeepDoc/MinerU）。
简单启发式，0-1 分，越高越干净。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import math
import re

import pdfplumber  # type: ignore


def score_pdf_quality(file_path: Path) -> Dict[str, float]:
    """
    对 PDF 做轻量评分，返回 dict：score(0-1), text_ratio, ocr_noise_ratio, page_count.
    评分越高表示文本提取越干净。
    """
    score = 0.0
    text_ratio = 0.0
    ocr_noise_ratio = 0.0
    page_count = 0

    try:
        with pdfplumber.open(str(file_path)) as pdf:
            page_count = len(pdf.pages)
            total_chars = 0
            total_text_chars = 0
            noise_chars = 0

            # 最多抽样前 10 页
            for page in pdf.pages[:10]:
                text = page.extract_text() or ""
                total_text_chars += len(text)
                # 简单噪声估计：不可见字符 + 连续标点/随机符号
                noise_chars += len(re.findall(r"[^\x20-\x7E\u4e00-\u9fff]", text))
                noise_chars += len(re.findall(r"[#@]{4,}|[.,]{6,}", text))

                # 页面原始字符量估计：用宽度/高度粗估，每行 80 字，30 行
                total_chars += max(len(text), 80 * 30)

            if total_chars > 0:
                text_ratio = total_text_chars / total_chars
            if total_text_chars > 0:
                ocr_noise_ratio = noise_chars / total_text_chars

            # 基础得分：文本占比权重 0.7，噪声占比权重 0.3（噪声越高扣分）
            score = 0.7 * text_ratio + 0.3 * max(0.0, 1.0 - ocr_noise_ratio)
            score = max(0.0, min(1.0, score))

            # 如果文本少但页数多，适当扣分（可能是扫描件）
            if total_text_chars < 500 and page_count >= 3:
                score *= 0.6

            # 平滑处理，避免极端值
            score = float(round(score, 3))
            text_ratio = float(round(text_ratio, 3))
            ocr_noise_ratio = float(round(ocr_noise_ratio, 3))
    except Exception:
        # 解析失败时返回低分，促使走鲁棒流程
        score = 0.0

    return {
        "score": score,
        "text_ratio": text_ratio,
        "ocr_noise_ratio": ocr_noise_ratio,
        "page_count": float(page_count),
    }

