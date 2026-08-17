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
import copy
import json
import logging
import math
import os
import re
import string
import sys
from pathlib import Path

import nltk
from hanziconv import HanziConv
from nltk import word_tokenize
from nltk.stem import PorterStemmer, WordNetLemmatizer

# Prefer using NLTK data distributed with the package to avoid runtime downloads
_NLTK_DATA_DIR = Path(__file__).resolve().parents[2] / "resources" / "nltk_data"
if str(_NLTK_DATA_DIR) not in nltk.data.path:
    nltk.data.path.insert(0, str(_NLTK_DATA_DIR))

_SPLIT_CHAR_PATTERN = (
    r"([ ,\.<>/?;:'\[\]\\`!@#$%^&*\(\)\{\}\|_+=《》，。？、；‘’：“”【】~！￥%……（）——-]+"
    r"|[a-zA-Z0-9,\.-]+)"
)


class _JsonTrie:
    def __init__(self, _alphabet: str = ""):
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
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception as exc:
                logging.debug("Failed to remove temporary trie cache %s: %s", tmp, exc)

    @classmethod
    def load(cls, path: str) -> "_JsonTrie":
        # The cache file may be:
        # - JSON (the supported format)
        # - a legacy binary cache generated in a different environment
        # - partially written / corrupted
        # Fast sniff prevents noisy UnicodeDecodeError on binary caches.
        with open(path, "rb") as f:
            head = f.read(128)
        head = head.lstrip()
        if head.startswith(b"\xef\xbb\xbf"):
            head = head[3:]
        if not head or head[:1] not in (b"{", b"["):
            raise ValueError("Trie cache is not JSON")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except UnicodeDecodeError as exc:
            raise ValueError("Trie cache is not UTF-8 JSON") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("Trie cache is not valid JSON") from exc
        if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
            raise ValueError("Invalid trie cache format")
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


Trie = _JsonTrie


def get_default_resource_dir():
    """
    Return the default resource directory path, assuming this file is in:
    project_root/some/module/path/tokenizer.py
    Then the resource dir is: project_root/resources/data_parser/qieci
    If the directory does not exist, it will be created automatically.
    """
    try:
        from ...configs import settings as deepdoc_settings

        token_path = getattr(deepdoc_settings, "TOKENIZER_DICT_PATH", None)
        if token_path:
            return os.path.abspath(token_path)
    except Exception:
        logging.debug("Tokenizer settings not available, falling back to default", exc_info=True)

    resource_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../resources/data_parser/qieci"))
    return resource_dir


class RagTokenizer:
    def key_(self, line):
        return str(line.lower().encode("utf-8"))[2:-1]

    def rkey_(self, line):
        return str(("DD" + (line[::-1].lower())).encode("utf-8"))[2:-1]

    def load_dict_(self, fnm):
        logging.info(f"[HUQIE]:Build trie from {fnm}")
        try:
            with open(fnm, "r", encoding="utf-8") as of:
                while True:
                    line = of.readline()
                    if not line:
                        break
                    line = re.sub(r"[\r\n]+", "", line)
                    line = re.split(r"[ \t]", line)
                    k = self.key_(line[0])
                    F = int(math.log(float(line[1]) / self.DENOMINATOR) + 0.5)
                    if k not in self.trie_ or self.trie_[k][0] < F:
                        self.trie_[self.key_(line[0])] = (F, line[2])
                    self.trie_[self.rkey_(line[0])] = 1

                dict_file_cache = fnm + ".trie"
                logging.info(f"[HUQIE]:Build trie cache to {dict_file_cache}")
                self.trie_.save(dict_file_cache)
        except Exception:
            logging.exception(f"[HUQIE]:Build trie {fnm} failed")

    def __init__(self, debug=False):
        self.DEBUG = debug
        self.DENOMINATOR = 1000000
        self.DIR_ = get_default_resource_dir()

        self.stemmer = PorterStemmer()
        self.lemmatizer = WordNetLemmatizer()

        self.SPLIT_CHAR = _SPLIT_CHAR_PATTERN

        trie_file_name = self.DIR_ + ".txt.trie"
        # check if trie file existence
        if os.path.exists(trie_file_name):
            try:
                # load trie from file
                self.trie_ = Trie.load(trie_file_name)
                return
            except Exception as exc:
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
                try:
                    os.remove(trie_file_name)
                except Exception as exc:
                    logging.debug("Failed to remove unreadable trie cache %s: %s", trie_file_name, exc)
                self.trie_ = Trie(string.printable)
        else:
            # file not exist, build default trie
            logging.info(f"[HUQIE]:Trie file {trie_file_name} not found, build the default trie file")
            self.trie_ = Trie(string.printable)

        # load data from dict file and save to trie file
        self.load_dict_(self.DIR_ + ".txt")

    def load_user_dict(self, fnm):
        try:
            self.trie_ = Trie.load(fnm + ".trie")
            return
        except Exception:
            self.trie_ = Trie(string.printable)
        self.load_dict_(fnm)

    def add_user_dict(self, fnm):
        self.load_dict_(fnm)

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
        return HanziConv.toSimplified(line)

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
        copied = copy.deepcopy(pre_tks)
        copied.append(entry)
        return copied

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
        MAX_DEPTH = 10
        if _depth > MAX_DEPTH:
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

    def freq(self, tk):
        k = self.key_(tk)
        if k not in self.trie_:
            return 0
        return int(math.exp(self.trie_[k][0]) * self.DENOMINATOR + 0.5)

    def tag(self, tk):
        k = self.key_(tk)
        if k not in self.trie_:
            return ""
        return self.trie_[k][1]

    def score_(self, tfts):
        B = 30
        F, L, tks = 0, 0, []
        for tk, (freq, tag) in tfts:
            F += freq
            L += 0 if len(tk) < 2 else 1
            tks.append(tk)
        L /= len(tks)
        logging.debug("[SC] {} {} {} {} {}".format(tks, len(tks), L, F, B / len(tks) + L + F))
        return tks, B / len(tks) + L + F

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
            E = s + 1
            for e in range(s + 2, min(len(tks) + 2, s + 6)):
                tk = "".join(tks[s:e])
                if re.search(self.SPLIT_CHAR, tk) and self.freq(tk):
                    E = e
            res.append("".join(tks[s:E]))
            s = E

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
        return [self.stemmer.stem(self.lemmatizer.lemmatize(t)) for t in word_tokenize(text)]

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

    def tokenize(self, line):
        line = self._normalized_line(line)
        line = self._str_q2b(line).lower()
        line = self._tradi2simp(line)

        arr = self._split_by_lang(line)
        res = []
        for text, is_chinese_text in arr:
            res.extend(self._tokenize_segment(text, is_chinese_text))

        res = " ".join(res)
        logging.debug("[TKS] {}".format(self.merge_(res)))
        return self.merge_(res)

    @staticmethod
    def _mostly_non_chinese(tks):
        zh_num = len([1 for c in tks if c and is_chinese(c[0])])
        return zh_num < len(tks) * 0.2

    def _fine_grained_token(self, tk):
        if len(tk) < 3 or re.match(r"[0-9,\.-]+$", tk):
            return tk
        tkslist = [tk] if len(tk) > 10 else []
        if len(tk) <= 10:
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
        return " ".join(stk) if isinstance(stk, list) else stk

    def fine_grained_tokenize(self, tks):
        tks = tks.split()
        if self._mostly_non_chinese(tks):
            res = []
            for tk in tks:
                res.extend(tk.split("/"))
            return " ".join(res)

        res = [self._fine_grained_token(tk) for tk in tks]
        return " ".join(self.english_normalize_(res))


def is_chinese(s):
    if s >= "\u4e00" and s <= "\u9fa5":
        return True
    else:
        return False


def is_number(s):
    if s >= "\u0030" and s <= "\u0039":
        return True
    else:
        return False


def is_alphabet(s):
    if (s >= "\u0041" and s <= "\u005a") or (s >= "\u0061" and s <= "\u007a"):
        return True
    else:
        return False


def naive_qie(txt):
    tks = []
    for t in txt.split():
        if tks and re.match(r".*[a-zA-Z]$", tks[-1]) and re.match(r".*[a-zA-Z]$", t):
            tks.append(" ")
        tks.append(t)
    return tks


naiveQie = naive_qie


RagTokenizer.loadDict_ = RagTokenizer.load_dict_
RagTokenizer.loadUserDict = RagTokenizer.load_user_dict
RagTokenizer.addUserDict = RagTokenizer.add_user_dict
RagTokenizer._strQ2B = RagTokenizer._str_q2b
RagTokenizer.sortTks_ = RagTokenizer.sort_tks_
RagTokenizer.maxForward_ = RagTokenizer.max_forward_
RagTokenizer.maxBackward_ = RagTokenizer.max_backward_

tokenizer = RagTokenizer()
tokenize = tokenizer.tokenize
fine_grained_tokenize = tokenizer.fine_grained_tokenize
tag = tokenizer.tag
freq = tokenizer.freq
loadUserDict = tokenizer.load_user_dict
addUserDict = tokenizer.add_user_dict
tradi2simp = tokenizer._tradi2simp
strQ2B = tokenizer._str_q2b

if __name__ == "__main__":
    tknzr = RagTokenizer(debug=True)
    # huqie.addUserDict("/tmp/tmp.new.tks.dict")
    tks = tknzr.tokenize(
        "哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈哈"
    )
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize(
        "公开征求意见稿提出，境外投资者可使用自有人民币或外汇投资。使用外汇投资的，可通过债券持有人在香港人民币业务清算行及香港地区经批准可进入境内银行间外汇市场进行交易的境外人民币业务参加行（以下统称香港结算行）办理外汇资金兑换。香港结算行由此所产生的头寸可到境内银行间外汇市场平盘。使用外汇投资的，在其投资的债券到期或卖出后，原则上应兑换回外汇。"
    )
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize(
        "多校划片就是一个小区对应多个小学初中，让买了学区房的家庭也不确定到底能上哪个学校。目的是通过这种方式为学区房降温，把就近入学落到实处。南京市长江大桥"
    )
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize(
        "实际上当时他们已经将业务中心偏移到安全部门和针对政府企业的部门 Scripts are compiled and cached aaaaaaaaa"
    )
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize("虽然我不怎么玩")
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize("蓝月亮如何在外资夹击中生存,那是全宇宙最有意思的")
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize(
        "涡轮增压发动机num最大功率,不像别的共享买车锁电子化的手段,我们接过来是否有意义,黄黄爱美食,不过，今天阿奇要讲到的这家农贸市场，说实话，还真蛮有特色的！不仅环境好，还打出了"
    )
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize("这周日你去吗？这周日你有空吗？")
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize("Unity3D开发经验 测试开发工程师 c++双11双11 985 211 ")
    logging.info(tknzr.fine_grained_tokenize(tks))
    tks = tknzr.tokenize(
        "数据分析项目经理|数据分析挖掘|数据分析方向|商品数据分析|搜索数据分析 sql python hive tableau Cocos2d-"
    )
    logging.info(tknzr.fine_grained_tokenize(tks))
    if len(sys.argv) < 2:
        sys.exit()
    tknzr.DEBUG = False
    tknzr.load_user_dict(sys.argv[1])
    of = open(sys.argv[2], "r")
    while True:
        line = of.readline()
        if not line:
            break
        logging.info(tknzr.tokenize(line))
    of.close()
