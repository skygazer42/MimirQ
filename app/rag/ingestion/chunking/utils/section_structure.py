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

"""Classify section headings and assemble bounded chapter hierarchies."""

import logging
import random
import re

from app.infrastructure.tokens import num_tokens_from_string

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
    hits = [0] * len(BULLET_PATTERN)
    for section in sections:
        text = section.strip()
        if not_bullet(text):
            continue
        for index, patterns in enumerate(BULLET_PATTERN):
            if any(re.match(pattern, text) for pattern in patterns):
                hits[index] += 1
    maximum = max(hits, default=0)
    return hits.index(maximum) if maximum else -1


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
        if not _section_text(sections[end]).startswith(prefix):
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
    if not normalized_sections:
        return []
    lines, sorted_levels = _tree_lines(bull, normalized_sections)
    target_level = _tree_target_level(sorted_levels, bull, depth)
    root = SectionNode(level=0, depth=target_level, texts=[])
    root.build_tree(lines)
    return [element for element in root.get_tree() if element]


def _normalize_structured_sections(sections):
    if isinstance(sections[0], str):
        sections = [(section, "") for section in sections]
    normalized = []
    for text, layout in sections:
        if not text:
            continue
        prefix = text.partition("@")[0].strip()
        if len(prefix) > 1 and not re.match(r"\d+$", prefix):
            normalized.append((text, layout))
    return normalized


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
        logging.debug("Rendering hierarchical chunk sections=%s", len(texts))
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


class SectionNode:
    def __init__(self, level, depth=-1, texts=None):
        self.level = level
        self.depth = depth
        self.texts = texts or []
        self.children = []

    def __repr__(self):
        return f"Node(level={self.level}, texts={self.texts}, children={len(self.children)})"

    def build_tree(self, lines):
        stack = [self]
        for level, text in lines:
            if self.depth != -1 and level > self.depth:
                # Beyond target depth: merge content into the current leaf instead of creating deeper nodes
                stack[-1].texts.append(text)
                continue

            # Move up until we find the proper parent whose level is strictly smaller than current
            while len(stack) > 1 and level <= stack[-1].level:
                stack.pop()

            node = SectionNode(level=level, texts=[text])
            # Attach as child of current parent and descend
            stack[-1].children.append(node)
            stack.append(node)

        return self

    def get_tree(self):
        tree_list = []
        self._dfs(self, tree_list, [])
        return tree_list

    def _dfs(self, node, tree_list, titles):
        level = node.level
        texts = node.texts
        child = node.children

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


__all__ = [
    "random_choices",
    "bullets_category",
    "is_english",
    "remove_contents_table",
    "make_colon_as_title",
    "tree_merge",
    "hierarchical_merge",
    "docx_question_level",
    "SectionNode",
]
