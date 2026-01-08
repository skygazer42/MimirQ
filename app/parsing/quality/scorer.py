"""
PDF 质量评分工具：用于决定解析分流

评分维度（前 3 页抽样）：
- 文本提取质量（50%）：文本量、可读性、OCR 噪声
- 格式一致性（30%）：字体、行距、段落结构
- 表格完整性（20%）：表格识别率、对齐度

综合得分 0-1，越高越干净；低分倾向走 OCR/结构化流程。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import re

import pdfplumber  # type: ignore

from app.parsing.quality.ocr_validator import rapid_ocr_service
from app.rag.core.logging import get_logger


logger = get_logger("parsing.quality.scorer")


def score_pdf_quality(
    file_path: Path,
    sample_pages: int = 3,
    use_ocr_validation: bool = False
) -> Dict[str, float]:
    """
    对 PDF 做轻量评分（前 sample_pages 页抽样）。
    
    评分维度：
    - 文本提取质量（50%）：文本量、可读性、OCR噪声、扫描件检测
    - 格式一致性（30%）：字体多样性、行距离散度、段落结构
    - 表格完整性（20%）：表格识别率、对齐度
    
    返回字段：
    - score: 综合得分 0-1，越高越干净
    - text_quality_score: 文本提取质量分（0-1）
    - format_consistency_score: 格式一致性分（0-1）
    - table_quality_score: 表格完整性分（0-1）
    - is_scanned: 是否扫描件
    - page_count: 总页数
    
    经验阈值：score >= 0.8 → 干净可复制；<= 0.5 → 疑似扫描/手写
    
    Args:
        file_path: PDF 文件路径
        sample_pages: 抽样页数（默认 3）
        use_ocr_validation: 是否启用 RapidOCR 验证
    """
    page_count = 0
    text_quality_score = 0.0
    format_consistency_score = 0.0
    table_quality_score = 0.0
    is_scanned = False

    try:
        with pdfplumber.open(str(file_path)) as pdf:
            page_count = len(pdf.pages)
            sampled_pages = max(1, min(sample_pages, page_count))
            pages_data = pdf.pages[:sampled_pages]

            # 维度1：文本提取质量（50%）
            text_quality_score, is_scanned = _score_text_quality(
                pages_data, file_path, use_ocr_validation
            )

            # 维度2：格式一致性（30%）
            format_consistency_score = _score_format_consistency(pages_data)

            # 维度3：表格完整性（20%）
            table_quality_score = _score_table_quality(pages_data)

    except Exception as e:
        logger.warning("PDF quality scoring failed: %s", e)
        # 失败时返回低分
        text_quality_score = 0.0
        format_consistency_score = 0.0
        table_quality_score = 0.0

    # 加权求和：文本50% + 格式30% + 表格20%
    final_score = (
        0.50 * text_quality_score +
        0.30 * format_consistency_score +
        0.20 * table_quality_score
    )
    final_score = max(0.0, min(1.0, final_score))

    return {
        "score": round(final_score, 3),
        "text_quality_score": round(text_quality_score, 3),
        "format_consistency_score": round(format_consistency_score, 3),
        "table_quality_score": round(table_quality_score, 3),
        "is_scanned": is_scanned,
        "page_count": float(page_count),
    }


def _score_text_quality(
    pages: List,
    file_path: Path,
    use_ocr_validation: bool
) -> Tuple[float, bool]:
    """
    评估文本提取质量（0-1）。
    指标：文本密度、噪声比、可读性、扫描件检测。
    """
    total_text_chars = 0
    total_expected_chars = 0
    noise_chars = 0
    is_scanned = False

    for page in pages:
        text = page.extract_text() or ""
        total_text_chars += len(text)
        
        # 噪声估计：不可见字符 + 连续异常符号
        noise_chars += len(re.findall(r"[^\x20-\x7E\u4e00-\u9fff]", text))
        noise_chars += len(re.findall(r"[#@]{4,}|[.,]{6,}|_{10,}", text))
        
        # 预期字符数（粗估）：按页面尺寸
        total_expected_chars += 2400  # 假设每页约2400字符（80字/行 × 30行）

    # 文本密度
    text_density = total_text_chars / max(1, total_expected_chars)
    text_density = min(1.0, text_density)  # 截断到1
    
    # 噪声比
    noise_ratio = noise_chars / max(1, total_text_chars)
    clean_ratio = max(0.0, 1.0 - noise_ratio)
    
    # 基础得分：密度70% + 清洁度30%
    score = 0.70 * text_density + 0.30 * clean_ratio

    # OCR 验证：文本少时触发
    if use_ocr_validation and (text_density < 0.3 or total_text_chars < 200 * len(pages)):
        try:
            logger.info("RapidOCR validation enabled for scanned detection")
            _, ocr_chars = rapid_ocr_service.ocr_pdf_pages(
                file_path,
                max_pages=min(2, len(pages))
            )
            
            ocr_gain = (ocr_chars - total_text_chars) / max(1, total_text_chars)
            
            if ocr_gain > 0.5:
                # OCR增益>50% → 扫描件
                is_scanned = True
                score *= 0.4
                logger.info("Detected scanned PDF (ocr_gain=%.2f)", ocr_gain)
            elif ocr_gain > 0.1:
                # OCR增益>10% → 部分扫描
                score *= 0.7
                logger.info("Detected mixed/partial scan (ocr_gain=%.2f)", ocr_gain)
        except Exception as e:
            logger.warning("RapidOCR validation failed: %s", e)

    # 文本极少 → 按扫描件处理
    if total_text_chars < 500 and len(pages) >= 2:
        is_scanned = True
        score *= 0.5

    return max(0.0, min(1.0, score)), is_scanned


def _score_format_consistency(pages: List) -> float:
    """
    评估格式一致性（0-1）。
    指标：字体多样性、行距离散度、段落结构规律性。
    """
    font_sizes = []
    line_heights = []
    paragraph_count = 0
    
    for page in pages:
        try:
            # 提取字符元数据
            chars = page.chars or []
            if chars:
                # 字体大小
                font_sizes.extend([c.get("size", 0) for c in chars if c.get("size")])
                
                # 行高（按y坐标聚合）
                y_coords = sorted(set(c.get("top", 0) for c in chars))
                if len(y_coords) > 1:
                    heights = [y_coords[i+1] - y_coords[i] for i in range(len(y_coords)-1)]
                    line_heights.extend(heights)
            
            # 段落计数（按空行分割）
            text = page.extract_text() or ""
            paragraph_count += len(re.findall(r"\n\n+", text)) + 1
        except Exception:
            pass

    if not font_sizes:
        # 无法提取字体信息 → 默认中等分
        return 0.5

    # 字体大小一致性（标准差越小越好）
    import statistics
    try:
        font_std = statistics.stdev(font_sizes) if len(font_sizes) > 1 else 0
        font_consistency = max(0.0, 1.0 - min(1.0, font_std / 10.0))  # 归一化
    except Exception:
        font_consistency = 0.5

    # 行高一致性
    try:
        if line_heights:
            line_std = statistics.stdev(line_heights) if len(line_heights) > 1 else 0
            line_consistency = max(0.0, 1.0 - min(1.0, line_std / 20.0))
        else:
            line_consistency = 0.5
    except Exception:
        line_consistency = 0.5

    # 段落结构（有段落分隔 → 更规范）
    para_per_page = paragraph_count / max(1, len(pages))
    para_score = min(1.0, para_per_page / 5.0)  # 假设每页5段为理想

    # 综合：字体40% + 行高40% + 段落20%
    score = 0.40 * font_consistency + 0.40 * line_consistency + 0.20 * para_score
    return max(0.0, min(1.0, score))


def _score_table_quality(pages: List) -> float:
    """
    评估表格完整性（0-1）。
    指标：表格识别率、单元格对齐度。
    """
    total_tables = 0
    well_formed_tables = 0
    
    for page in pages:
        try:
            tables = page.find_tables() or []
            total_tables += len(tables)
            
            for table in tables:
                # 表格行列数
                rows = len(table.rows) if hasattr(table, "rows") and table.rows else 0
                cells = table.cells if hasattr(table, "cells") and table.cells else []
                
                # 判断是否"完整"：至少2行2列，且单元格数合理
                if rows >= 2 and len(cells) >= 4:
                    well_formed_tables += 1
        except Exception:
            pass

    if total_tables == 0:
        # 无表格 → 默认满分（不扣分）
        return 1.0

    # 完整表格占比
    table_ratio = well_formed_tables / max(1, total_tables)
    return max(0.0, min(1.0, table_ratio))
