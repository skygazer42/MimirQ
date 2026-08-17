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

import copy
import logging
import random
import re
from collections import Counter

import chardet
from cn2an import cn2an
from PIL import Image
from word2number import w2n

from app.third_party.integrated_pipeline.common.token_utils import num_tokens_from_string


def _roman_to_int(text: str) -> int:
    """
    Minimal Roman numeral parser (I/V/X/L/C/D/M).

    Upstream Integrated pipeline depends on `roman_numbers`, which isn't a hard dependency here.
    Keep this small and local so the chunking pipeline remains importable.
    """
    raw = str(text or "").strip().upper()
    raw = re.sub(r"[^IVXLCDM]", "", raw)
    if not raw:
        raise ValueError("not_roman")
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(raw):
        val = values.get(ch)
        if val is None:
            raise ValueError("not_roman")
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    if total <= 0:
        raise ValueError("not_roman")
    return total


__all__ = ["rag_tokenizer"]

all_codecs = [
    "utf-8",
    "gb2312",
    "gbk",
    "utf_16",
    "ascii",
    "big5",
    "big5hkscs",
    "cp037",
    "cp273",
    "cp424",
    "cp437",
    "cp500",
    "cp720",
    "cp737",
    "cp775",
    "cp850",
    "cp852",
    "cp855",
    "cp856",
    "cp857",
    "cp858",
    "cp860",
    "cp861",
    "cp862",
    "cp863",
    "cp864",
    "cp865",
    "cp866",
    "cp869",
    "cp874",
    "cp875",
    "cp932",
    "cp949",
    "cp950",
    "cp1006",
    "cp1026",
    "cp1125",
    "cp1140",
    "cp1250",
    "cp1251",
    "cp1252",
    "cp1253",
    "cp1254",
    "cp1255",
    "cp1256",
    "cp1257",
    "cp1258",
    "euc_jp",
    "euc_jis_2004",
    "euc_jisx0213",
    "euc_kr",
    "gb18030",
    "hz",
    "iso2022_jp",
    "iso2022_jp_1",
    "iso2022_jp_2",
    "iso2022_jp_2004",
    "iso2022_jp_3",
    "iso2022_jp_ext",
    "iso2022_kr",
    "latin_1",
    "iso8859_2",
    "iso8859_3",
    "iso8859_4",
    "iso8859_5",
    "iso8859_6",
    "iso8859_7",
    "iso8859_8",
    "iso8859_9",
    "iso8859_10",
    "iso8859_11",
    "iso8859_13",
    "iso8859_14",
    "iso8859_15",
    "iso8859_16",
    "johab",
    "koi8_r",
    "koi8_t",
    "koi8_u",
    "kz1048",
    "mac_cyrillic",
    "mac_greek",
    "mac_iceland",
    "mac_latin2",
    "mac_roman",
    "mac_turkish",
    "ptcp154",
    "shift_jis",
    "shift_jis_2004",
    "shift_jisx0213",
    "utf_32",
    "utf_32_be",
    "utf_32_le",
    "utf_16_be",
    "utf_16_le",
    "utf_7",
    "windows-1250",
    "windows-1251",
    "windows-1252",
    "windows-1253",
    "windows-1254",
    "windows-1255",
    "windows-1256",
    "windows-1257",
    "windows-1258",
    "latin-2",
]


def find_codec(blob):
    detected = chardet.detect(blob[:1024])
    if detected["confidence"] > 0.5:
        if detected["encoding"] == "ascii":
            return "utf-8"

    for c in all_codecs:
        try:
            blob[:1024].decode(c)
            return c
        except Exception as exc:
            logging.debug("Codec %s failed sample decode: %s", c, exc)
        try:
            blob.decode(c)
            return c
        except Exception as exc:
            logging.debug("Codec %s failed full decode: %s", c, exc)

    return "utf-8"


QUESTION_PATTERN = [
    r"第([零一二三四五六七八九十百0-9]+)问",
    r"第([零一二三四五六七八九十百0-9]+)条",
    r"[\(（]([零一二三四五六七八九十百]+)[\)）]",
    r"第(\d+)问",
    r"第(\d+)条",
    r"(\d{1,2})[\. 、]",
    r"([零一二三四五六七八九十百]+)[ 、]",
    r"[\(（](\d{1,2})[\)）]",
    r"QUESTION (ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)",
    r"QUESTION (I+V?|VI*|XI|IX|X)",
    r"QUESTION (\d+)",
]


def has_qbullet(reg, box, last_box, last_index, last_bull, bull_x0_list):
    section, last_section = box["text"], last_box["text"]
    has_bull = re.match(reg + r"(\w|\W)*?(?:？|\?|\n|$)+", section)
    if not has_bull:
        return None, last_index
    _fill_missing_box_position(last_box, box)
    if _misaligned_qbullet(box, last_box, last_bull, bull_x0_list):
        return None, last_index
    index = index_int(has_bull.group(1))
    if last_section[-1] in ":：":
        return None, last_index
    if _accept_qbullet_index(section, box, reg, index, last_index):
        bull_x0_list.append(box["x0"])
        return has_bull, index
    return None, last_index


def _fill_missing_box_position(last_box, box):
    if "x0" not in last_box:
        last_box["x0"] = box["x0"]
    if "top" not in last_box:
        last_box["top"] = box["top"]


def _misaligned_qbullet(box, last_box, last_bull, bull_x0_list):
    if last_bull and box["x0"] - last_box["x0"] > 10:
        return True
    if not last_bull and box["x0"] >= last_box["x0"] and box["top"] - last_box["top"] < 20:
        return True
    avg_bull_x0 = sum(bull_x0_list) / len(bull_x0_list) if bull_x0_list else box["x0"]
    return box["x0"] - avg_bull_x0 > 10


def _accept_qbullet_index(section, box, reg, index, last_index):
    if not last_index or index >= last_index:
        return True
    if section[-1] in "?？":
        return True
    if box["layout_type"] == "title":
        return True
    return _question_has_interrogative_lead(section, reg)


def _question_has_interrogative_lead(section, reg):
    matched = re.match(reg, section)
    if not matched:
        return False
    pure_section = section.lstrip(matched.group()).lower()
    ask_reg = r"(what|when|where|how|why|which|who|whose|为什么|为啥|哪)"
    return bool(re.match(ask_reg, pure_section))


def index_int(index_str):
    res = -1
    try:
        res = int(index_str)
    except ValueError:
        try:
            res = w2n.word_to_num(index_str)
        except Exception:
            try:
                res = cn2an(index_str)
            except Exception:
                try:
                    res = _roman_to_int(index_str)
                except ValueError:
                    return -1
    return res


def qbullets_category(sections):
    global QUESTION_PATTERN
    hits = [0] * len(QUESTION_PATTERN)
    for i, pro in enumerate(QUESTION_PATTERN):
        for sec in sections:
            if re.match(pro, sec) and not not_bullet(sec):
                hits[i] += 1
                break
    maximum = 0
    res = -1
    for i, h in enumerate(hits):
        if h <= maximum:
            continue
        res = i
        maximum = h
    return res, QUESTION_PATTERN[res]


BULLET_PATTERN = [
    [
        r"第[零一二三四五六七八九十百0-9]+(分?编|部分)",
        r"第[零一二三四五六七八九十百0-9]+章",
        r"第[零一二三四五六七八九十百0-9]+节",
        r"第[零一二三四五六七八九十百0-9]+条",
        r"[\(（][零一二三四五六七八九十百]+[\)）]",
    ],
    [
        r"第\d+章",
        r"第\d+节",
        r"\d{,2}[\. 、]",
        r"\d{,2}\.\d{,2}[^a-zA-Z/%~-]",
        r"\d{,2}\.\d{,2}\.\d{,2}",
        r"\d{,2}\.\d{,2}\.\d{,2}\.\d{,2}",
    ],
    [
        r"第[零一二三四五六七八九十百0-9]+章",
        r"第[零一二三四五六七八九十百0-9]+节",
        r"[零一二三四五六七八九十百]+[ 、]",
        r"[\(（][零一二三四五六七八九十百]+[\)）]",
        r"[\(（]\d{,2}[\)）]",
    ],
    [
        r"PART (ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)",
        r"Chapter (I+V?|VI*|XI|IX|X)",
        r"Section \d+",
        r"Article \d+",
    ],
    [
        r"^#[^#]",
        r"^##[^#]",
        r"^###.*",
        r"^####.*",
        r"^#####.*",
        r"^######.*",
    ],
]


def random_choices(arr, k):
    k = min(len(arr), k)
    return random.choices(arr, k=k)


def not_bullet(line):
    patt = [r"0", r"\d+ +[0-9~个只-]", r"\d+\.{2,}"]
    return any(re.match(r, line) for r in patt)


def bullets_category(sections):
    global BULLET_PATTERN
    hits = [0] * len(BULLET_PATTERN)
    for i, pro in enumerate(BULLET_PATTERN):
        for sec in sections:
            sec = sec.strip()
            for p in pro:
                if re.match(p, sec) and not not_bullet(sec):
                    hits[i] += 1
                    break
    maximum = 0
    res = -1
    for i, h in enumerate(hits):
        if h <= maximum:
            continue
        res = i
        maximum = h
    return res


def is_english(texts):
    if not texts:
        return False

    pattern = re.compile(r"[`a-zA-Z0-9\s.,':;/\"?<>!\(\)\-]")

    if isinstance(texts, str):
        texts = list(texts)
    elif isinstance(texts, list):
        texts = [t for t in texts if isinstance(t, str) and t.strip()]
    else:
        return False

    if not texts:
        return False

    eng = sum(1 for t in texts if pattern.fullmatch(t.strip()))
    return (eng / len(texts)) > 0.8


def is_chinese(text):
    if not text:
        return False
    chinese = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            chinese += 1
    if chinese / len(text) > 0.2:
        return True
    return False


def tokenize(d, txt, eng):
    from . import rag_tokenizer

    _ = eng
    d["content_with_weight"] = txt
    t = re.sub(r"</?(table|td|caption|tr|th)( [^<>]{0,12})?>", " ", txt)
    d["content_ltks"] = rag_tokenizer.tokenize(t)
    d["content_sm_ltks"] = rag_tokenizer.fine_grained_tokenize(d["content_ltks"])


def tokenize_chunks(chunks, doc, eng, pdf_parser=None, child_delimiters_pattern=None):
    res = []
    # wrap up as es documents
    for ii, ck in enumerate(chunks):
        if len(ck.strip()) == 0:
            continue
        logging.debug("-- {}".format(ck))
        d = copy.deepcopy(doc)
        if pdf_parser:
            try:
                d["image"], poss = pdf_parser.crop(ck, need_position=True)
                add_positions(d, poss)
                ck = pdf_parser.remove_tag(ck)
            except NotImplementedError:
                pass
        else:
            add_positions(d, [[ii] * 5])

        if child_delimiters_pattern:
            d["mom_with_weight"] = ck
            for txt in re.split(r"(%s)" % child_delimiters_pattern, ck, flags=re.DOTALL):
                dd = copy.deepcopy(d)
                tokenize(dd, txt, eng)
                res.append(dd)
            continue

        tokenize(d, ck, eng)
        res.append(d)
    return res


def tokenize_chunks_with_images(chunks, doc, eng, images, child_delimiters_pattern=None):
    res = []
    # wrap up as es documents
    for ii, (ck, image) in enumerate(zip(chunks, images, strict=False)):
        if len(ck.strip()) == 0:
            continue
        logging.debug("-- {}".format(ck))
        d = copy.deepcopy(doc)
        d["image"] = image
        add_positions(d, [[ii] * 5])
        if child_delimiters_pattern:
            d["mom_with_weight"] = ck
            for txt in re.split(r"(%s)" % child_delimiters_pattern, ck, flags=re.DOTALL):
                dd = copy.deepcopy(d)
                tokenize(dd, txt, eng)
                res.append(dd)
            continue
        tokenize(d, ck, eng)
        res.append(d)
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
    Best-effort ordering: if positional info exists on any chunk, use it to
    order chunks before collecting context; otherwise keep original order.
    """
    from . import rag_tokenizer

    if not chunks or (table_context_size <= 0 and image_context_size <= 0):
        return chunks

    ordered_indices, has_positioned_chunks = _ordered_chunk_indices(chunks)
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
    if has_positioned_chunks:
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
    except Exception:
        return None, None, None
    return pn, top, left


def _ordered_chunk_indices(chunks):
    positioned = []
    unpositioned = []
    for idx, ck in enumerate(chunks):
        pn, top, left = _chunk_position(ck)
        if pn is not None and top is not None:
            positioned.append((idx, pn, top, left if left is not None else 0))
            continue
        unpositioned.append(idx)
    if not positioned:
        return list(range(len(chunks))), False
    positioned.sort(key=lambda item: (int(item[1]), int(item[2]), int(item[3]), item[0]))
    return [idx for idx, _, _, _ in positioned] + unpositioned, True


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


def remove_contents_table(sections, eng=False):
    i = 0
    while i < len(sections):
        if not _is_contents_heading(_section_text(sections[i])):
            i += 1
            continue
        sections.pop(i)
        if i >= len(sections):
            break
        prefix = _consume_empty_contents_entries(sections, i, eng)
        if i >= len(sections):
            break
        sections.pop(i)
        if i >= len(sections) or not prefix:
            break
        _drop_prefixed_contents_entries(sections, i, prefix)


def _section_text(section):
    return (section if isinstance(section, str) else section[0]).strip()


def _is_contents_heading(text):
    normalized = re.sub(r"( | |\u3000)+", "", text.split("@@")[0], flags=re.IGNORECASE)
    return bool(re.match(r"(contents|目录|目次|table of contents|致谢|acknowledge)$", normalized))


def _consume_empty_contents_entries(sections, index, eng):
    while index < len(sections):
        prefix = _contents_prefix(_section_text(sections[index]), eng)
        if prefix:
            return prefix
        sections.pop(index)
    return ""


def _contents_prefix(text, eng):
    return " ".join(text.split()[:2]) if eng else text[:3]


def _drop_prefixed_contents_entries(sections, index, prefix):
    for end in range(index, min(index + 128, len(sections))):
        if not re.match(prefix, _section_text(sections[end])):
            continue
        del sections[index:end]
        break


def make_colon_as_title(sections):
    if not sections:
        return []
    if isinstance(sections[0], type("")):
        return sections
    i = 0
    while i < len(sections):
        txt, _layout = sections[i]
        i += 1
        txt = txt.split("@")[0].strip()
        if not txt:
            continue
        if txt[-1] not in ":：":
            continue
        txt = txt[::-1]
        arr = re.split(r"([。？！!?;；]| \.)", txt)
        if len(arr) < 2 or len(arr[1]) < 32:
            continue
        sections.insert(i - 1, (arr[0][::-1], "title"))
        i += 1


def title_frequency(bull, sections):
    bullets_size = len(BULLET_PATTERN[bull])
    levels = [bullets_size + 1 for _ in range(len(sections))]
    if not sections or bull < 0:
        return bullets_size + 1, levels

    for i, (txt, layout) in enumerate(sections):
        for j, p in enumerate(BULLET_PATTERN[bull]):
            if re.match(p, txt.strip()) and not not_bullet(txt):
                levels[i] = j
                break
        else:
            if re.search(r"(title|head)", layout) and not not_title(txt.split("@")[0]):
                levels[i] = bullets_size
    most_level = bullets_size + 1
    for level, c in sorted(Counter(levels).items(), key=lambda x: x[1] * -1):
        if level <= bullets_size:
            most_level = level
            break
    return most_level, levels


def not_title(txt):
    if re.match(r"第[零一二三四五六七八九十百0-9]+条", txt):
        return False
    if len(txt.split()) > 12 or (txt.find(" ") < 0 and len(txt) >= 32):
        return True
    return re.search(r"[,;，。；！!]", txt)


def tree_merge(bull, sections, depth):
    if not sections or bull < 0:
        return sections
    normalized_sections = _normalize_structured_sections(sections)
    lines, sorted_levels = _tree_lines(bull, normalized_sections)
    target_level = _tree_target_level(sorted_levels, bull, depth)
    root = Node(level=0, depth=target_level, texts=[])
    root.build_tree(lines)
    return [element for element in root.get_tree() if element]


def _normalize_structured_sections(sections):
    if isinstance(sections[0], str):
        sections = [(section, "") for section in sections]
    return [
        (text, layout)
        for text, layout in sections
        if text and len(text.split("@")[0].strip()) > 1 and not re.match(r"\d+$", text.split("@")[0].strip())
    ]


def _tree_section_level(bull, section):
    text, layout = section
    text = re.sub(r"\u3000", " ", text).strip()
    for level, title in enumerate(BULLET_PATTERN[bull], start=1):
        if re.match(title, text.strip()):
            return level, text
    if re.search(r"(title|head)", layout) and not not_title(text):
        return len(BULLET_PATTERN[bull]) + 1, text
    return len(BULLET_PATTERN[bull]) + 2, text


def _tree_lines(bull, sections):
    level_set = set()
    lines = []
    for section in sections:
        level, text = _tree_section_level(bull, section)
        if not text.strip("\n"):
            continue
        lines.append((level, text))
        level_set.add(level)
    return lines, sorted(level_set)


def _tree_target_level(sorted_levels, bull, depth):
    target_level = sorted_levels[depth - 1] if depth <= len(sorted_levels) else sorted_levels[-1]
    if target_level == len(BULLET_PATTERN[bull]) + 2:
        return sorted_levels[-2] if len(sorted_levels) > 1 else sorted_levels[0]
    return target_level


def hierarchical_merge(bull, sections, depth):
    if not sections or bull < 0:
        return []
    normalized_sections = _normalize_structured_sections(sections)
    level_groups, section_texts = _hierarchical_level_groups(bull, normalized_sections)
    cks = _hierarchical_chunk_indices(level_groups, depth, len(section_texts))
    if not cks:
        return cks
    rendered_chunks = _render_hierarchical_chunks(cks, section_texts)
    return _pack_hierarchical_chunks(rendered_chunks)


def _hierarchical_level_groups(bull, sections):
    bullets_size = len(BULLET_PATTERN[bull])
    levels = [[] for _ in range(bullets_size + 2)]
    for index, (text, layout) in enumerate(sections):
        levels[_hierarchical_section_level(bull, text, layout)].append(index)
    return levels, [text for text, _ in sections]


def _hierarchical_section_level(bull, text, layout):
    for level, pattern in enumerate(BULLET_PATTERN[bull]):
        if re.match(pattern, text.strip()):
            return level
    if re.search(r"(title|head)", layout) and not not_title(text):
        return len(BULLET_PATTERN[bull])
    return len(BULLET_PATTERN[bull]) + 1


def _binary_search_floor(arr, target):
    if not arr:
        return -1
    if target > arr[-1]:
        return len(arr) - 1
    if target < arr[0]:
        return -1
    start, end = 0, len(arr)
    while end - start > 1:
        middle = (end + start) // 2
        if target > arr[middle]:
            start = middle
        elif target < arr[middle]:
            end = middle
        else:
            raise AssertionError
    return start


def _hierarchical_chunk_indices(levels, depth, section_count):
    readed = [False] * section_count
    chunks = []
    reversed_levels = levels[::-1]
    for level_index, entries in enumerate(reversed_levels[:depth]):
        for section_index in entries:
            if readed[section_index]:
                continue
            chunk = _hierarchical_chunk_path(reversed_levels, level_index, section_index)
            chunks.append(chunk)
            for item in chunk:
                readed[item] = True
    return chunks


def _hierarchical_chunk_path(levels, level_index, section_index):
    chunk = [section_index]
    if level_index + 1 == len(levels) - 1:
        return chunk
    for next_level in range(level_index + 1, len(levels)):
        floor_index = _binary_search_floor(levels[next_level], section_index)
        if floor_index < 0:
            continue
        candidate = levels[next_level][floor_index]
        if candidate > chunk[-1]:
            chunk.pop()
        chunk.append(candidate)
    return chunk


def _render_hierarchical_chunks(chunk_indices, section_texts):
    rendered = []
    for chunk in chunk_indices:
        texts = [section_texts[index] for index in reversed(chunk)]
        logging.debug("\n* ".join(texts))
        rendered.append(texts)
    return rendered


def _pack_hierarchical_chunks(chunks):
    result = [[]]
    token_counts = [0]
    for chunk in chunks:
        if len(chunk) > 1:
            result.append(chunk)
            token_counts.append(218)
            continue
        text = chunk[0]
        token_count = num_tokens_from_string(re.sub(r"@@\d+.*", "", text))
        if token_count + token_counts[-1] < 218:
            result[-1].append(text)
            token_counts[-1] += token_count
            continue
        result.append(chunk)
        token_counts.append(token_count)
    return result


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
    from app.deepdoc.parser.pdf_parser import IntegratedPipelinePdfParser

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
            IntegratedPipelinePdfParser.remove_tag,
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
    if not texts or len(texts) != len(images):
        return [], []
    custom_pattern = _custom_delimiter_pattern(delimiter)
    if custom_pattern:
        return _split_image_chunks_by_custom_delimiter(texts, images, custom_pattern)
    return _merge_image_sections(texts, images, chunk_token_num, overlapped_percent)


def _split_image_chunks_by_custom_delimiter(texts, images, custom_pattern):
    chunks = []
    result_images = []
    for text, image in zip(texts, images, strict=False):
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
    from app.deepdoc.parser.pdf_parser import IntegratedPipelinePdfParser

    chunks = [""]
    result_images = [None]
    token_counts = [0]
    for text, image in zip(texts, images, strict=False):
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
            IntegratedPipelinePdfParser.remove_tag,
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
    result_images[-1] = image if result_images[-1] is None else concat_img(result_images[-1], image)
    token_counts[-1] += token_count


def docx_question_level(p, bull=-1):
    txt = re.sub(r"\u3000", " ", p.text).strip()
    if p.style.name.startswith("Heading"):
        return int(p.style.name.split(" ")[-1]), txt
    else:
        if bull < 0:
            return 0, txt
        for j, title in enumerate(BULLET_PATTERN[bull]):
            if re.match(title, txt):
                return j + 1, txt
    return len(BULLET_PATTERN[bull]) + 1, txt


def concat_img(img1, img2):
    if img1 and not img2:
        return img1
    if not img1 and img2:
        return img2
    if not img1 and not img2:
        return None

    if img1 is img2:
        return img1

    if isinstance(img1, Image.Image) and isinstance(img2, Image.Image):
        pixel_data1 = img1.tobytes()
        pixel_data2 = img2.tobytes()
        if pixel_data1 == pixel_data2:
            return img1

    width1, height1 = img1.size
    width2, height2 = img2.size

    new_width = max(width1, width2)
    new_height = height1 + height2
    new_image = Image.new("RGB", (new_width, new_height))

    new_image.paste(img1, (0, 0))
    new_image.paste(img2, (0, height1))
    return new_image


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
    images[-1] = concat_img(images[-1], image)
    token_counts[-1] += token_count


def extract_between(text: str, start_tag: str, end_tag: str) -> list[str]:
    pattern = re.escape(start_tag) + r"(.*?)" + re.escape(end_tag)
    return re.findall(pattern, text, flags=re.DOTALL)


def get_delimiters(delimiters: str):
    dels = []
    s = 0
    for m in re.finditer(r"`([^`]+)`", delimiters, re.I):
        f, t = m.span()
        dels.append(m.group(1))
        dels.extend(list(delimiters[s:f]))
        s = t
    if s < len(delimiters):
        dels.extend(list(delimiters[s:]))

    dels.sort(key=lambda x: -len(x))
    dels = [re.escape(d) for d in dels if d]
    dels = [d for d in dels if d]
    dels_pattern = "|".join(dels)

    return dels_pattern


class Node:
    def __init__(self, level, depth=-1, texts=None):
        self.level = level
        self.depth = depth
        self.texts = texts or []
        self.children = []

    def add_child(self, child_node):
        self.children.append(child_node)

    def get_children(self):
        return self.children

    def get_level(self):
        return self.level

    def get_texts(self):
        return self.texts

    def set_texts(self, texts):
        self.texts = texts

    def add_text(self, text):
        self.texts.append(text)

    def clear_text(self):
        self.texts = []

    def __repr__(self):
        return f"Node(level={self.level}, texts={self.texts}, children={len(self.children)})"

    def build_tree(self, lines):
        stack = [self]
        for level, text in lines:
            if self.depth != -1 and level > self.depth:
                # Beyond target depth: merge content into the current leaf instead of creating deeper nodes
                stack[-1].add_text(text)
                continue

            # Move up until we find the proper parent whose level is strictly smaller than current
            while len(stack) > 1 and level <= stack[-1].get_level():
                stack.pop()

            node = Node(level=level, texts=[text])
            # Attach as child of current parent and descend
            stack[-1].add_child(node)
            stack.append(node)

        return self

    def get_tree(self):
        tree_list = []
        self._dfs(self, tree_list, [])
        return tree_list

    def _dfs(self, node, tree_list, titles):
        level = node.get_level()
        texts = node.get_texts()
        child = node.get_children()

        if level == 0 and texts:
            tree_list.append("\n".join(titles + texts))

        # Titles within configured depth are accumulated into the current path
        if 1 <= level <= self.depth:
            path_titles = titles + texts
        else:
            path_titles = titles

        # Body outside the depth limit becomes its own chunk under the current title path
        if level > self.depth and texts:
            tree_list.append("\n".join(path_titles + texts))

        # A leaf title within depth emits its title path as a chunk (header-only section)
        elif not child and (1 <= level <= self.depth):
            tree_list.append("\n".join(path_titles))

        # Recurse into children with the updated title path
        for c in child:
            self._dfs(c, tree_list, path_titles)
