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

import bisect
import json
import logging
import math
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import RootModel, StrictInt, StrictStr, model_validator

from app.infrastructure.runtime.dependencies import require_dependency

# Prefer using NLTK data distributed with the package to avoid runtime downloads
_TOKENIZER_DICTIONARY_PATH = Path(__file__).resolve().parents[1] / "resources" / "data_parser" / "qieci"
_NLTK_DATA_DIR = Path(__file__).resolve().parents[1] / "resources" / "nltk_data"

_SPLIT_CHAR_PATTERN = (
    r"([ ,\.<>/?;:'\[\]\\`!@#$%^&*\(\)\{\}\|_+=《》，。？、；‘’：“”【】~！￥%……（）——-]+"
    r"|[a-zA-Z0-9,\.-]+)"
)


class _TrieCache(RootModel[dict[str, StrictInt | tuple[StrictInt, StrictStr]]]):
    @model_validator(mode="after")
    def require_word_and_prefix_entries(self) -> "_TrieCache":
        for key, entry in self.root.items():
            if key.startswith("DD"):
                if entry != 1:
                    raise ValueError("Invalid reverse-prefix trie entry")
            elif not isinstance(entry, tuple):
                raise ValueError("Invalid word-frequency trie entry")
        return self


class _JsonTrie:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}
        self._sorted_keys: list[str] | None = None

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str):
        return self._data[key]

    def __setitem__(self, key: str, value) -> None:
        self._data[key] = value
        self._sorted_keys = None

    def save(self, path: str) -> None:
        # Write atomically to avoid producing partially-written caches on crashes/reloads.
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=Path(path).parent,
                prefix=f".{Path(path).name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(self._data, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    logging.warning("Failed to remove temporary trie cache %s", temporary_path, exc_info=True)

    @classmethod
    def load(cls, path: str) -> "_JsonTrie":
        data = _TrieCache.model_validate_json(Path(path).read_bytes()).root
        obj = cls()
        obj._data = data
        obj._sorted_keys = sorted(obj._data.keys())
        return obj

    def has_keys_with_prefix(self, prefix: str) -> bool:
        if self._sorted_keys is None:
            self._sorted_keys = sorted(self._data.keys())
        keys = self._sorted_keys
        idx = bisect.bisect_left(keys, prefix)
        return idx < len(keys) and keys[idx].startswith(prefix)


class RagTokenizer:
    def key_(self, line):
        return str(line.lower().encode("utf-8"))[2:-1]

    def rkey_(self, line):
        return str(("DD" + (line[::-1].lower())).encode("utf-8"))[2:-1]

    def load_dict_(self, fnm):
        logging.info("[HUQIE]:Build trie from %s", fnm)
        trie = _JsonTrie()
        with open(fnm, encoding="utf-8") as stream:
            for line in stream:
                word, frequency, tag = line.split()
                key = self.key_(word)
                log_frequency = int(math.log(float(frequency) / self.DENOMINATOR) + 0.5)
                if key not in trie or trie[key][0] < log_frequency:
                    trie[key] = (log_frequency, tag)
                trie[self.rkey_(word)] = 1
        self.trie_ = trie
        try:
            trie.save(fnm + ".trie")
        except OSError:
            # The dictionary is authoritative; its derived disk cache is optional.
            logging.warning("[HUQIE]:Cannot save derived trie cache for %s", fnm, exc_info=True)

    def __init__(self, debug: bool = False) -> None:
        nltk = require_dependency("nltk", feature="parsing_tokenizer")
        hanziconv = require_dependency("hanziconv", feature="parsing_tokenizer")
        if str(_NLTK_DATA_DIR) not in nltk.data.path:
            nltk.data.path.insert(0, str(_NLTK_DATA_DIR))
        self.DEBUG = debug
        self.DENOMINATOR = 1000000
        self.DIR_ = str(_TOKENIZER_DICTIONARY_PATH)

        self.stemmer = nltk.stem.PorterStemmer()
        self.lemmatizer = nltk.stem.WordNetLemmatizer()
        self._word_tokenize = nltk.word_tokenize
        self._hanzi_converter = hanziconv.HanziConv

        self.SPLIT_CHAR = _SPLIT_CHAR_PATTERN

        trie_file_name = self.DIR_ + ".txt.trie"
        # check if trie file existence
        if os.path.exists(trie_file_name):
            try:
                # load trie from file
                self.trie_ = _JsonTrie.load(trie_file_name)
                return
            except (OSError, ValueError) as exc:
                # Fail to load trie from file, rebuild from source dictionary.
                # Legacy or partial cache files are discarded and rebuilt from the source dictionary.
                if self.DEBUG:
                    logging.exception(f"[HUQIE]:Fail to load trie file {trie_file_name}, rebuild the default trie file")
                else:
                    logging.warning(
                        "[HUQIE]:Fail to load trie file %s (%s), rebuild the default trie file",
                        trie_file_name,
                        str(exc)[:200],
                    )
                self.trie_ = _JsonTrie()
        else:
            # file not exist, build default trie
            logging.info(f"[HUQIE]:Trie file {trie_file_name} not found, build the default trie file")
            self.trie_ = _JsonTrie()

        # load data from dict file and save to trie file
        self.load_dict_(self.DIR_ + ".txt")

    def _str_q2b(self, ustring):
        """Convert full-width characters to half-width characters"""
        rstring = ""
        for uchar in ustring:
            inside_code = ord(uchar)
            if inside_code == 0x3000:
                inside_code = 0x0020
            else:
                inside_code -= 0xFEE0
            if inside_code < 0x0020 or inside_code > 0x7E:
                rstring += uchar
            else:
                rstring += chr(inside_code)
        return rstring

    def _tradi2simp(self, line):
        return self._hanzi_converter.toSimplified(line)

    @staticmethod
    def _unknown_token(token):
        return token, (-12, "")

    def _token_entry(self, token):
        k = self.key_(token)
        if k in self.trie_:
            return token, self.trie_[k]
        return self._unknown_token(token)

    @staticmethod
    def _dfs_state_key(s, pre_tks):
        if pre_tks:
            return s, tuple(tk[0] for tk in pre_tks)
        return s, None

    @staticmethod
    def _repetitive_span(chars, s):
        if s >= len(chars) - 4:
            return None
        char_to_check = chars[s]
        for i in range(1, 5):
            if s + i >= len(chars) or chars[s + i] != char_to_check:
                return None
        end = s
        while end < len(chars) and chars[end] == char_to_check:
            end += 1
        return end

    @staticmethod
    def _copy_with_entry(pre_tks, entry):
        return [*pre_tks, entry]

    def _dfs_depth_limit(self, chars, s, pre_tks, tkslist):
        if s < len(chars):
            remaining = "".join(chars[s:])
            tkslist.append(self._copy_with_entry(pre_tks, self._unknown_token(remaining)))
        return s

    def _dfs_repetitive_branch(self, chars, s, pre_tks, tkslist, _depth, _memo):
        end = self._repetitive_span(chars, s)
        if end is None:
            return None
        mid = s + min(10, end - s)
        token = "".join(chars[s:mid])
        pretks = self._copy_with_entry(pre_tks, self._token_entry(token))
        return self.dfs_(chars, mid, pretks, tkslist, _depth + 1, _memo)

    def _dfs_start_bound(self, chars, s, pre_tks):
        start = s + 1
        if s + 2 <= len(chars):
            token_1 = "".join(chars[s : s + 1])
            token_2 = "".join(chars[s : s + 2])
            if self.trie_.has_keys_with_prefix(self.key_(token_1)) and not self.trie_.has_keys_with_prefix(
                self.key_(token_2)
            ):
                start = s + 2
        if len(pre_tks) > 2 and all(len(pre_tks[-idx][0]) == 1 for idx in range(1, 4)):
            token = pre_tks[-1][0] + "".join(chars[s : s + 1])
            if self.trie_.has_keys_with_prefix(self.key_(token)):
                start = s + 2
        return start

    def _dfs_known_tokens(self, chars, s, pre_tks, tkslist, _depth, _memo):
        result = s
        for e in range(self._dfs_start_bound(chars, s, pre_tks), len(chars) + 1):
            token = "".join(chars[s:e])
            key = self.key_(token)
            if e > s + 1 and not self.trie_.has_keys_with_prefix(key):
                break
            if key not in self.trie_:
                continue
            pretks = self._copy_with_entry(pre_tks, (token, self.trie_[key]))
            result = max(result, self.dfs_(chars, e, pretks, tkslist, _depth + 1, _memo))
        return result

    def dfs_(self, chars, s, pre_tks, tkslist, _depth=0, _memo=None):
        if _memo is None:
            _memo = {}
        max_depth = 10
        if _depth > max_depth:
            return self._dfs_depth_limit(chars, s, pre_tks, tkslist)

        state_key = self._dfs_state_key(s, pre_tks)
        if state_key in _memo:
            return _memo[state_key]

        if s >= len(chars):
            tkslist.append(pre_tks)
            _memo[state_key] = s
            return s
        repetitive_result = self._dfs_repetitive_branch(chars, s, pre_tks, tkslist, _depth, _memo)
        if repetitive_result is not None:
            _memo[state_key] = repetitive_result
            return repetitive_result

        result = self._dfs_known_tokens(chars, s, pre_tks, tkslist, _depth, _memo)
        if result > s:
            _memo[state_key] = result
            return result

        pretks = self._copy_with_entry(pre_tks, self._token_entry("".join(chars[s : s + 1])))
        result = self.dfs_(chars, s + 1, pretks, tkslist, _depth + 1, _memo)
        _memo[state_key] = result
        return result

    def freq(self, tk: str) -> int:
        k = self.key_(tk)
        if k not in self.trie_:
            return 0
        return int(math.exp(self.trie_[k][0]) * self.DENOMINATOR + 0.5)

    def tag(self, tk: str) -> str:
        k = self.key_(tk)
        if k not in self.trie_:
            return ""
        return self.trie_[k][1]

    def score_(self, tfts):
        base_score = 30
        frequency_score, multi_char_ratio, tks = 0, 0, []
        for tk, (freq, _tag) in tfts:
            frequency_score += freq
            multi_char_ratio += 0 if len(tk) < 2 else 1
            tks.append(tk)
        multi_char_ratio /= len(tks)
        logging.debug(
            "[SC] {} {} {} {} {}".format(
                tks,
                len(tks),
                multi_char_ratio,
                frequency_score,
                base_score / len(tks) + multi_char_ratio + frequency_score,
            )
        )
        return tks, base_score / len(tks) + multi_char_ratio + frequency_score

    def sort_tks_(self, tkslist):
        res = []
        for tfts in tkslist:
            tks, s = self.score_(tfts)
            res.append((tks, s))
        return sorted(res, key=lambda x: x[1], reverse=True)

    def merge_(self, tks):
        # if split chars is part of token
        res = []
        tks = re.sub(r" +", " ", tks).split()
        s = 0
        while True:
            if s >= len(tks):
                break
            stop = s + 1
            for e in range(s + 2, min(len(tks) + 2, s + 6)):
                tk = "".join(tks[s:e])
                if re.search(self.SPLIT_CHAR, tk) and self.freq(tk):
                    stop = e
            res.append("".join(tks[s:stop]))
            s = stop

        return " ".join(res)

    def max_forward_(self, line):
        res = []
        s = 0
        while s < len(line):
            e = s + 1
            t = line[s:e]
            while e < len(line) and self.trie_.has_keys_with_prefix(self.key_(t)):
                e += 1
                t = line[s:e]

            while e - 1 > s and self.key_(t) not in self.trie_:
                e -= 1
                t = line[s:e]

            if self.key_(t) in self.trie_:
                res.append((t, self.trie_[self.key_(t)]))
            else:
                res.append((t, (0, "")))

            s = e

        return self.score_(res)

    def max_backward_(self, line):
        res = []
        s = len(line) - 1
        while s >= 0:
            e = s + 1
            t = line[s:e]
            while s > 0 and self.trie_.has_keys_with_prefix(self.rkey_(t)):
                s -= 1
                t = line[s:e]

            while s + 1 < e and self.key_(t) not in self.trie_:
                s += 1
                t = line[s:e]

            if self.key_(t) in self.trie_:
                res.append((t, self.trie_[self.key_(t)]))
            else:
                res.append((t, (0, "")))

            s -= 1

        return self.score_(res[::-1])

    def english_normalize_(self, tks):
        return [self.stemmer.stem(self.lemmatizer.lemmatize(t)) if re.match(r"[a-zA-Z_-]+$", t) else t for t in tks]

    def _split_by_lang(self, line):
        txt_lang_pairs = []
        arr = re.split(self.SPLIT_CHAR, line)
        for a in arr:
            if not a:
                continue
            s = 0
            e = s + 1
            zh = is_chinese(a[s])
            while e < len(a):
                _zh = is_chinese(a[e])
                if _zh == zh:
                    e += 1
                    continue
                txt_lang_pairs.append((a[s:e], zh))
                s = e
                e = s + 1
                zh = _zh
            if s >= len(a):
                continue
            txt_lang_pairs.append((a[s:e], zh))
        return txt_lang_pairs

    @staticmethod
    def _normalized_line(line):
        return re.sub(r"\W+", " ", line)

    def _tokenize_non_chinese(self, text):
        return [self.stemmer.stem(self.lemmatizer.lemmatize(t)) for t in self._word_tokenize(text)]

    @staticmethod
    def _keep_whole_segment(text):
        return len(text) < 2 or re.match(r"[a-z\.-]+$", text) or re.match(r"[0-9\.-]+$", text)

    @staticmethod
    def _shared_prefix_length(left, right, left_start=0, right_start=0):
        same = 0
        while left_start + same < len(left) and right_start + same < len(right):
            if left[left_start + same] != right[right_start + same]:
                break
            same += 1
        return same

    @staticmethod
    def _join_tokens(tokens, start, stop):
        return "".join(tokens[start:stop])

    def _segment_with_dfs(self, text):
        tkslist = []
        self.dfs_(text, 0, [], tkslist)
        return " ".join(self.sort_tks_(tkslist)[0][0])

    def _resolve_bidirectional_tokens(self, tks, tks1):
        res = []
        prefix = self._shared_prefix_length(tks1, tks)
        if prefix > 0:
            res.append(" ".join(tks[:prefix]))

        _i = prefix
        _j = prefix
        i = _i + 1
        j = _j + 1
        while i < len(tks1) and j < len(tks):
            tk1 = self._join_tokens(tks1, _i, i)
            tk = self._join_tokens(tks, _j, j)
            if tk1 != tk:
                if len(tk1) > len(tk):
                    j += 1
                else:
                    i += 1
                continue

            if tks1[i] != tks[j]:
                i += 1
                j += 1
                continue

            res.append(self._segment_with_dfs(self._join_tokens(tks, _j, j)))
            same = self._shared_prefix_length(tks1, tks, i, j)
            res.append(" ".join(tks[j : j + same]))
            _i = i + same
            _j = j + same
            i = _i + 1
            j = _j + 1

        if _i < len(tks1):
            if _j >= len(tks):
                raise RuntimeError("Token alignment index exceeded source tokens")
            if self._join_tokens(tks1, _i, len(tks1)) != self._join_tokens(tks, _j, len(tks)):
                raise RuntimeError("Token alignment suffix mismatch")
            res.append(self._segment_with_dfs(self._join_tokens(tks, _j, len(tks))))
        return res

    def _tokenize_cjk_segment(self, text):
        tks, forward_score = self.max_forward_(text)
        tks1, backward_score = self.max_backward_(text)
        if self.DEBUG:
            logging.debug("[FW] {} {}".format(tks, forward_score))
            logging.debug("[BW] {} {}".format(tks1, backward_score))
        return self._resolve_bidirectional_tokens(tks, tks1)

    def _tokenize_segment(self, text, is_chinese_text):
        if not is_chinese_text:
            return self._tokenize_non_chinese(text)
        if self._keep_whole_segment(text):
            return [text]
        return self._tokenize_cjk_segment(text)

    def tokenize(self, line: str) -> str:
        line = self._normalized_line(line)
        line = self._str_q2b(line).lower()
        line = self._tradi2simp(line)

        arr = self._split_by_lang(line)
        res = []
        for text, is_chinese_text in arr:
            res.extend(self._tokenize_segment(text, is_chinese_text))

        res = " ".join(res)
        merged = self.merge_(res)
        logging.debug("[TKS] %s", merged)
        return merged

    @staticmethod
    def _mostly_non_chinese(tks):
        zh_num = len([1 for c in tks if c and is_chinese(c[0])])
        return zh_num < len(tks) * 0.2

    def _fine_grained_token(self, tk):
        if len(tk) < 3 or len(tk) > 10 or re.match(r"[0-9,\.-]+$", tk):
            return tk
        tkslist = []
        self.dfs_(tk, 0, [], tkslist)
        if len(tkslist) < 2:
            return tk
        stk = self.sort_tks_(tkslist)[1][0]
        if len(stk) == len(tk):
            return tk
        if re.match(r"[a-z\.-]+$", tk):
            for token in stk:
                if len(token) < 3:
                    return tk
        return " ".join(stk)

    def fine_grained_tokenize(self, tks: str) -> str:
        tks = tks.split()
        if self._mostly_non_chinese(tks):
            res = []
            for tk in tks:
                res.extend(tk.split("/"))
            return " ".join(res)

        res = [self._fine_grained_token(tk) for tk in tks]
        return " ".join(self.english_normalize_(res))


def is_chinese(s: str) -> bool:
    return "\u4e00" <= s <= "\u9fa5"


@lru_cache(maxsize=1)
def _get_tokenizer() -> RagTokenizer:
    return RagTokenizer()


def tokenize(text: str) -> str:
    return _get_tokenizer().tokenize(text)


def fine_grained_tokenize(tokens: str) -> str:
    return _get_tokenizer().fine_grained_tokenize(tokens)


def tag(token: str) -> str:
    return _get_tokenizer().tag(token)


__all__ = ["tokenize", "fine_grained_tokenize", "tag", "is_chinese"]
