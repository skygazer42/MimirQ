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

"""Build tokenized chunk records, position fields, and neighboring media context."""

import copy
import logging
import re

from app.infrastructure.tokens import num_tokens_from_string


def tokenize(d, txt, eng):
    from app.rag.ingestion.parsing.utils import tokenizer as rag_tokenizer

    _ = eng
    d["content_with_weight"] = txt
    t = re.sub(r"</?(table|td|caption|tr|th)( [^<>]{0,12})?>", " ", txt)
    d["content_ltks"] = rag_tokenizer.tokenize(t)
    d["content_sm_ltks"] = rag_tokenizer.fine_grained_tokenize(d["content_ltks"])


def _append_tokenized_chunk(
    records: list[dict], record: dict, text: str, english: bool, child_delimiters_pattern: str | None
) -> None:
    if not record.get("position_int"):
        record["geometry_unavailable_reason"] = "source_positions_unavailable"
    if not child_delimiters_pattern:
        tokenize(record, text, english)
        records.append(record)
        return

    record["mom_with_weight"] = text
    for child_text in re.split(r"(%s)" % child_delimiters_pattern, text, flags=re.DOTALL):
        child_record = copy.deepcopy(record)
        tokenize(child_record, child_text, english)
        records.append(child_record)


def tokenize_chunks(chunks, doc, eng, pdf_parser=None, child_delimiters_pattern=None):
    res = []
    # wrap up as es documents
    for ii, ck in enumerate(chunks):
        if len(ck.strip()) == 0:
            continue
        logging.debug("Tokenizing text chunk index=%s chars=%s", ii, len(ck))
        d = copy.deepcopy(doc)
        if pdf_parser:
            try:
                d["image"], poss = pdf_parser.crop(ck, need_position=True)
                add_positions(d, poss)
                ck = pdf_parser.remove_tag(ck)
            except NotImplementedError:
                pass
        _append_tokenized_chunk(res, d, ck, eng, child_delimiters_pattern)
    return res


def tokenize_chunks_with_images(chunks, doc, eng, images, child_delimiters_pattern=None):
    res = []
    # wrap up as es documents
    for ii, (ck, image) in enumerate(zip(chunks, images, strict=True)):
        if len(ck.strip()) == 0:
            continue
        logging.debug("Tokenizing image chunk index=%s chars=%s", ii, len(ck))
        d = copy.deepcopy(doc)
        d["image"] = image
        _append_tokenized_chunk(res, d, ck, eng, child_delimiters_pattern)
    return res


def tokenize_table(tbls, doc, eng, batch_size=10):
    res = []
    # add tables
    for (img, rows), poss in tbls:
        if not rows:
            continue
        if isinstance(rows, str):
            d = copy.deepcopy(doc)
            tokenize(d, rows, eng)
            d["content_with_weight"] = rows
            d["doc_type_kwd"] = "table"
            if img:
                d["image"] = img
                d["doc_type_kwd"] = "image"
            if poss:
                add_positions(d, poss)
            res.append(d)
            continue
        de = "; " if eng else "； "
        for i in range(0, len(rows), batch_size):
            d = copy.deepcopy(doc)
            r = de.join(rows[i : i + batch_size])
            tokenize(d, r, eng)
            d["doc_type_kwd"] = "table"
            if img:
                d["image"] = img
                d["doc_type_kwd"] = "image"
            add_positions(d, poss)
            res.append(d)
    return res


def attach_media_context(chunks, table_context_size=0, image_context_size=0):
    """
    Attach surrounding text chunk content to media chunks (table/image).
    Use positional ordering only when every chunk has comparable page/top/left
    coordinates. Otherwise preserve the actual input order for context.
    """
    from app.rag.ingestion.parsing.utils import tokenizer as rag_tokenizer

    if not chunks or (table_context_size <= 0 and image_context_size <= 0):
        return chunks

    ordered_indices, has_complete_positions = _ordered_chunk_indices(chunks)
    for sorted_pos, idx in enumerate(ordered_indices):
        ck = chunks[idx]
        token_budget = _media_context_budget(ck, table_context_size, image_context_size)
        if token_budget <= 0:
            continue
        prev_ctx = _collect_neighbor_context(chunks, ordered_indices, sorted_pos, token_budget, -1)
        next_ctx = _collect_neighbor_context(chunks, ordered_indices, sorted_pos, token_budget, 1)
        if not prev_ctx and not next_ctx:
            continue
        combined = "\n".join(_media_context_pieces(prev_ctx, _chunk_text(ck), next_ctx))
        original = _replace_chunk_text(ck, combined)
        if combined != original:
            _refresh_chunk_tokens(ck, combined, rag_tokenizer)
    if has_complete_positions:
        chunks[:] = [chunks[i] for i in ordered_indices]

    return chunks


def _is_image_chunk(ck):
    if ck.get("doc_type_kwd") == "image":
        return True
    text_val = ck.get("content_with_weight") if isinstance(ck.get("content_with_weight"), str) else ck.get("text")
    has_text = isinstance(text_val, str) and text_val.strip()
    return bool(ck.get("image")) and not has_text


def _is_table_chunk(ck):
    return ck.get("doc_type_kwd") == "table"


def _is_text_chunk(ck):
    return not _is_image_chunk(ck) and not _is_table_chunk(ck)


def _chunk_text(ck):
    if isinstance(ck.get("content_with_weight"), str):
        return ck["content_with_weight"]
    if isinstance(ck.get("text"), str):
        return ck["text"]
    return ""


def _split_context_sentences(text):
    pattern = r"([.。！？!?；;：:\n])"
    parts = re.split(pattern, text)
    sentences = []
    buf = ""
    for part in parts:
        if not part:
            continue
        if re.fullmatch(pattern, part):
            buf += part
            sentences.append(buf)
            buf = ""
            continue
        buf += part
    if buf:
        sentences.append(buf)
    return sentences


def _trim_context_to_tokens(text, token_budget, from_tail=False):
    if token_budget <= 0 or not text:
        return ""
    sentences = _split_context_sentences(text)
    if not sentences:
        return ""
    collected = []
    remaining = token_budget
    sequence = reversed(sentences) if from_tail else sentences
    for sentence in sequence:
        tks = num_tokens_from_string(sentence)
        if tks <= 0:
            continue
        collected.append(sentence)
        if tks > remaining:
            break
        remaining -= tks
    if from_tail:
        collected.reverse()
    return "".join(collected)


def _chunk_position(ck):
    pn = None
    top = None
    left = None
    try:
        if ck.get("page_num_int"):
            pn = ck["page_num_int"][0]
        elif ck.get("page_number") is not None:
            pn = ck.get("page_number")
        if ck.get("top_int"):
            top = ck["top_int"][0]
        elif ck.get("top") is not None:
            top = ck.get("top")
        if ck.get("position_int"):
            left = ck["position_int"][0][1]
        elif ck.get("x0") is not None:
            left = ck.get("x0")
    except (IndexError, KeyError, TypeError):
        return None, None, None
    return pn, top, left


def _ordered_chunk_indices(chunks):
    positioned = []
    for idx, ck in enumerate(chunks):
        pn, top, left = _chunk_position(ck)
        if pn is None or top is None or left is None:
            return list(range(len(chunks))), False
        if any(isinstance(value, bool) for value in (pn, top, left)):
            return list(range(len(chunks))), False
        try:
            positioned.append((idx, int(pn), int(top), int(left)))
        except (OverflowError, TypeError, ValueError):
            return list(range(len(chunks))), False
    if not positioned:
        return list(range(len(chunks))), False
    positioned.sort(key=lambda item: (item[1], item[2], item[3], item[0]))
    return [idx for idx, _, _, _ in positioned], True


def _media_context_budget(ck, table_context_size, image_context_size):
    if _is_image_chunk(ck):
        return image_context_size
    if _is_table_chunk(ck):
        return table_context_size
    return 0


def _collect_neighbor_context(chunks, ordered_indices, sorted_pos, token_budget, step):
    context = []
    remaining = token_budget
    stop = len(ordered_indices) if step > 0 else -1
    for pos in range(sorted_pos + step, stop, step):
        if remaining <= 0:
            break
        neighbor = chunks[ordered_indices[pos]]
        if not _is_text_chunk(neighbor):
            break
        txt, tks = _fit_context_text(_chunk_text(neighbor), remaining, step < 0)
        if not txt:
            continue
        context.append(txt)
        remaining -= tks
    if step < 0:
        context.reverse()
    return context


def _fit_context_text(text, token_budget, from_tail):
    if not text:
        return "", 0
    tks = num_tokens_from_string(text)
    if tks <= 0:
        return "", 0
    if tks > token_budget:
        text = _trim_context_to_tokens(text, token_budget, from_tail=from_tail)
        tks = num_tokens_from_string(text)
    return text, tks


def _media_context_pieces(prev_ctx, self_text, next_ctx):
    pieces = [*prev_ctx]
    if self_text:
        pieces.append(self_text)
    pieces.extend(next_ctx)
    return pieces


def _replace_chunk_text(ck, combined):
    original = ck.get("content_with_weight")
    if "content_with_weight" in ck:
        ck["content_with_weight"] = combined
        return original
    if "text" in ck:
        original = ck.get("text")
        ck["text"] = combined
    return original


def _refresh_chunk_tokens(ck, combined, rag_tokenizer):
    content_tokens = ck.get("content_ltks")
    if "content_ltks" in ck:
        content_tokens = rag_tokenizer.tokenize(combined)
        ck["content_ltks"] = content_tokens
    if "content_sm_ltks" in ck:
        if content_tokens is None:
            content_tokens = rag_tokenizer.tokenize(combined)
        ck["content_sm_ltks"] = rag_tokenizer.fine_grained_tokenize(content_tokens)


def add_positions(d, poss):
    if not poss:
        return
    page_num_int = []
    position_int = []
    top_int = []
    for pn, left, right, top, bottom in poss:
        page_num_int.append(int(pn + 1))
        top_int.append(int(top))
        position_int.append((int(pn + 1), int(left), int(right), int(top), int(bottom)))
    d["page_num_int"] = page_num_int
    d["position_int"] = position_int
    d["top_int"] = top_int


def build_chunk_document(filename):
    """Build the filename and title-token fields shared by document chunking strategies."""
    from app.rag.ingestion.parsing.utils import tokenizer as rag_tokenizer

    doc = {"docnm_kwd": filename, "title_tks": rag_tokenizer.tokenize(re.sub("\\.[a-zA-Z]+$", "", filename))}
    doc["title_sm_tks"] = rag_tokenizer.fine_grained_tokenize(doc["title_tks"])
    return doc


__all__ = [
    "tokenize_chunks",
    "tokenize_chunks_with_images",
    "tokenize_table",
    "attach_media_context",
    "build_chunk_document",
]
