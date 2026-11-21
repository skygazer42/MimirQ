#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

"""Merge text, image, and DOCX sections while preserving overlap and position tags."""

import re

from app.infrastructure.tokens import num_tokens_from_string
from app.rag.ingestion.parsing.enrich.image_understanding import concat_images


def naive_merge(sections: str | list, chunk_token_num=128, delimiter="\n。；！？", overlapped_percent=0):
    if not sections:
        return []
    sections = _normalize_merge_sections(sections)
    custom_pattern = _custom_delimiter_pattern(delimiter)
    if custom_pattern:
        return _split_text_chunks_by_custom_delimiter(sections, custom_pattern)
    return _merge_text_sections(sections, chunk_token_num, overlapped_percent)


def _normalize_merge_sections(sections):
    if isinstance(sections, str):
        sections = [sections]
    if isinstance(sections[0], str):
        return [(section, "") for section in sections]
    return sections


def _custom_delimiter_pattern(delimiter):
    custom_delimiters = [match.group(1) for match in re.finditer(r"`([^`]+)`", delimiter)]
    if not custom_delimiters:
        return ""
    unique_delimiters = sorted(set(custom_delimiters), key=len, reverse=True)
    return "|".join(re.escape(text) for text in unique_delimiters)


def _split_text_chunks_by_custom_delimiter(sections, custom_pattern):
    chunks = []
    for section, pos in sections:
        for sub_section in _split_custom_segments(section, custom_pattern):
            text = "\n" + sub_section
            chunks.append(_append_position(text, pos))
    return chunks


def _split_custom_segments(text, custom_pattern):
    return [
        segment
        for segment in re.split(r"(%s)" % custom_pattern, text, flags=re.DOTALL)
        if not re.fullmatch(custom_pattern, segment or "")
    ]


def _append_position(text, pos):
    local_pos = pos if num_tokens_from_string(text) >= 8 else ""
    if local_pos and text.find(local_pos) < 0:
        return text + local_pos
    return text


def _merge_text_sections(sections, chunk_token_num, overlapped_percent):
    from app.rag.ingestion.parsing.utils.block_schema import remove_pdf_position_tags

    chunks = [""]
    token_counts = [0]
    for section, pos in sections:
        text = "\n" + section
        _append_text_chunk(
            chunks,
            token_counts,
            text,
            pos,
            chunk_token_num,
            overlapped_percent,
            remove_pdf_position_tags,
        )
    return chunks


def _append_text_chunk(chunks, token_counts, text, pos, chunk_token_num, overlapped_percent, remove_tag):
    token_count = num_tokens_from_string(text)
    pos = "" if token_count < 8 else (pos or "")
    if _starts_new_chunk(chunks[-1], token_counts[-1], chunk_token_num, overlapped_percent):
        text = _prefixed_overlapped_text(chunks, text, overlapped_percent, remove_tag)
        chunks.append(_append_position_suffix(text, pos))
        token_counts.append(token_count)
        return
    chunks[-1] += _append_position_suffix(text, pos, base_text=chunks[-1])
    token_counts[-1] += token_count


def _starts_new_chunk(last_chunk, last_token_count, chunk_token_num, overlapped_percent):
    threshold = chunk_token_num * (100 - overlapped_percent) / 100.0
    return last_chunk == "" or last_token_count > threshold


def _prefixed_overlapped_text(chunks, text, overlapped_percent, remove_tag):
    if not chunks:
        return text
    overlapped = remove_tag(chunks[-1])
    start = int(len(overlapped) * (100 - overlapped_percent) / 100.0)
    return overlapped[start:] + text


def _append_position_suffix(text, pos, base_text=""):
    if pos and base_text.find(pos) < 0 and text.find(pos) < 0:
        return text + pos
    return text


def naive_merge_with_images(texts, images, chunk_token_num=128, delimiter="\n。；！？", overlapped_percent=0):
    if len(texts) != len(images):
        raise ValueError("Text sections and section images must have matching lengths")
    if not texts:
        return [], []
    custom_pattern = _custom_delimiter_pattern(delimiter)
    if custom_pattern:
        return _split_image_chunks_by_custom_delimiter(texts, images, custom_pattern)
    return _merge_image_sections(texts, images, chunk_token_num, overlapped_percent)


def _split_image_chunks_by_custom_delimiter(texts, images, custom_pattern):
    chunks = []
    result_images = []
    for text, image in zip(texts, images, strict=True):
        text_str, text_pos = _unpack_text_with_position(text)
        for sub_section in _split_custom_segments(text_str, custom_pattern):
            chunks.append(_append_position("\n" + sub_section, text_pos))
            result_images.append(image)
    return chunks, result_images


def _unpack_text_with_position(text):
    if isinstance(text, tuple):
        return text[0], text[1] if len(text) > 1 else ""
    return text, ""


def _merge_image_sections(texts, images, chunk_token_num, overlapped_percent):
    from app.rag.ingestion.parsing.utils.block_schema import remove_pdf_position_tags

    chunks = [""]
    result_images = [None]
    token_counts = [0]
    for text, image in zip(texts, images, strict=True):
        text_str, text_pos = _unpack_text_with_position(text)
        _append_image_chunk(
            chunks,
            result_images,
            token_counts,
            "\n" + text_str,
            image,
            text_pos,
            chunk_token_num,
            overlapped_percent,
            remove_pdf_position_tags,
        )
    return chunks, result_images


def _append_image_chunk(
    chunks,
    result_images,
    token_counts,
    text,
    image,
    pos,
    chunk_token_num,
    overlapped_percent,
    remove_tag,
):
    token_count = num_tokens_from_string(text)
    pos = "" if token_count < 8 else (pos or "")
    if _starts_new_chunk(chunks[-1], token_counts[-1], chunk_token_num, overlapped_percent):
        text = _prefixed_overlapped_text(chunks, text, overlapped_percent, remove_tag)
        chunks.append(_append_position_suffix(text, pos))
        result_images.append(image)
        token_counts.append(token_count)
        return
    chunks[-1] += _append_position_suffix(text, pos, base_text=chunks[-1])
    result_images[-1] = image if result_images[-1] is None else concat_images(result_images[-1], image)
    token_counts[-1] += token_count


def naive_merge_docx(sections, chunk_token_num=128, delimiter="\n。；！？"):
    if not sections:
        return [], []
    custom_pattern = _custom_delimiter_pattern(delimiter)
    if custom_pattern:
        return _split_docx_chunks_by_custom_delimiter(sections, custom_pattern)
    return _merge_docx_sections(sections, chunk_token_num)


def _split_docx_chunks_by_custom_delimiter(sections, custom_pattern):
    chunks = []
    images = []
    for section, image in sections:
        for sub_section in _split_custom_segments(section, custom_pattern):
            if not sub_section:
                continue
            chunks.append("\n" + sub_section)
            images.append(image)
    return chunks, images


def _merge_docx_sections(sections, chunk_token_num):
    chunks = []
    images = []
    token_counts = []
    for section, image in sections:
        _append_docx_chunk(chunks, images, token_counts, "\n" + section, image, chunk_token_num)
    return chunks, images


def _append_docx_chunk(chunks, images, token_counts, text, image, chunk_token_num):
    token_count = num_tokens_from_string(text)
    if not chunks or token_counts[-1] > chunk_token_num:
        chunks.append(text)
        images.append(image)
        token_counts.append(token_count)
        return
    chunks[-1] += text
    images[-1] = concat_images(images[-1], image)
    token_counts[-1] += token_count


__all__ = ["naive_merge", "naive_merge_with_images", "naive_merge_docx"]
