"""
Built-in registry of governance processing scripts (templates).

These are reference templates exposed via the data-governance UI as "从模板库选择"
on the 重复行学习 page (formerly 样板行发现 / common-lines workbench).

IMPORTANT
---------
Per :class:`app.api.schemas.governance_profile.GovernanceProcessingScript`,
scripts are persisted with a governance profile **only for review/versioning**.
The ingestion pipeline does **not** execute them unless a separate sandboxed
runtime explicitly supports that in the future. The templates below are
therefore intentionally side-effect free reference code customers can copy as
a starting point — not a guarantee of runtime behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProcessingScriptLanguage = Literal["javascript", "typescript", "python", "rust"]
ProcessingScriptStage = Literal["post_parse", "post_governance"]


@dataclass(frozen=True)
class BuiltinProcessingScript:
    """
    Built-in processing script template.

    The shape mirrors :class:`GovernanceProcessingScript` so the UI can splice an
    instance straight into ``payload.processing_scripts`` after user selection.
    """

    key: str
    name: str
    description: str
    language: ProcessingScriptLanguage
    stage: ProcessingScriptStage
    content: str
    tags: list[str] = field(default_factory=list)


_CN_NUMBER_NORMALIZE = '''"""
中文大写金额归一化(模板)

把 "壹万贰仟元"、"一百二十万"、"叁佰元整" 等中文(含繁体)金额表达
转换为阿拉伯数字,便于后续抽取与统计。

NOTE: 该脚本仅作模板展示,入库管道不会自动执行;请复制到自定义服务后调用。
"""

import re

_CN_DIGIT = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "兩": 2, "两": 2,
    "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
    "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}
_CN_UNIT = {
    "十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000,
    "万": 10_000, "萬": 10_000, "亿": 100_000_000, "億": 100_000_000,
}
_MONEY_RE = re.compile(r"([零〇一壹二贰兩两三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟万萬亿億]+)\\s*(元|圆|圓)?")


def _cn_to_int(text: str) -> int:
    total, section, current = 0, 0, 0
    for ch in text:
        if ch in _CN_DIGIT:
            current = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            if unit >= 10_000:
                section = (section + current) * unit
                total += section
                section, current = 0, 0
            else:
                section += (current or 1) * unit
                current = 0
    return total + section + current


def normalize(text: str) -> str:
    def _sub(m: "re.Match[str]") -> str:
        value = _cn_to_int(m.group(1))
        return f"{value} {m.group(2) or '元'}" if value else m.group(0)
    return _MONEY_RE.sub(_sub, text)
'''


_PDF_SOFTBREAK_REPAIR = '''"""
PDF 软换行修复(模板)

很多 PDF 在文本抽取后,一个完整句子会被拆成多行(行末没有句号但语义未结束)。
该模板把"上行末为非终止标点 + 下行首为小写字母/中文非句首字符"的两行合并,
同时保留段落空行作为段落分隔。

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_TERMINATORS = "。.!?！？；;"
_LIST_OR_TITLE_PREFIX = re.compile(r"^\\s*(?:[#\\-*•·]|\\d+[.、)]|[一二三四五六七八九十]、)")


def repair(text: str) -> str:
    lines = text.split("\\n")
    out: list[str] = []
    buf = ""
    for raw in lines:
        line = raw.rstrip()
        if not line:
            if buf:
                out.append(buf)
                buf = ""
            out.append("")
            continue
        if _LIST_OR_TITLE_PREFIX.match(line):
            if buf:
                out.append(buf)
            buf = line
            continue
        if buf and buf[-1] not in _TERMINATORS:
            buf = f"{buf}{line.lstrip()}"
        else:
            if buf:
                out.append(buf)
            buf = line
    if buf:
        out.append(buf)
    return "\\n".join(out)
'''


_CN_PUNCT_NORMALIZE = '''"""
中文标点全/半角统一(模板)

- 含 ≥ 30% 中文字符的段落,半角 , . : ; ! ? 统一替换为全角 , 。 : ; ! ?
- 其他段落保持半角(避免破坏代码块和英文正文)

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_HALF_TO_FULL = {
    ",": ",", ".": "。", ":": ":", ";": ";",
    "!": "!", "?": "?",
}
_CN_CHAR_RE = re.compile(r"[\\u4e00-\\u9fff]")


def _is_chinese_paragraph(text: str, threshold: float = 0.3) -> bool:
    if not text:
        return False
    cn = len(_CN_CHAR_RE.findall(text))
    return (cn / len(text)) >= threshold


def normalize(text: str) -> str:
    paragraphs = text.split("\\n\\n")
    out = []
    for para in paragraphs:
        if _is_chinese_paragraph(para):
            for half, full in _HALF_TO_FULL.items():
                para = para.replace(half, full)
        out.append(para)
    return "\\n\\n".join(out)
'''


_CURRENCY_UNIT_EXPAND = '''"""
货币单位口径展开(模板)

把 "1.2 亿元" / "350 万元" / "5 百万元" 等口径表达
展开为完整阿拉伯数字 + 单位,便于跨文档比对一致口径。

输出会保留原文便于审计,例如:
    "营收 1.2 亿元" → "营收 1.2 亿元 [≈ 120,000,000 元]"

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_UNIT_TO_FACTOR = {
    "亿": 100_000_000,
    "億": 100_000_000,
    "万": 10_000,
    "萬": 10_000,
    "百万": 1_000_000,
    "千": 1_000,
    "仟": 1_000,
}

_PATTERN = re.compile(
    r"(\\d+(?:\\.\\d+)?)\\s*(百万|亿|億|万|萬|千|仟)\\s*(元|圆|圓|人民币)?",
)


def expand(text: str) -> str:
    def _sub(m: "re.Match[str]") -> str:
        amount = float(m.group(1))
        unit = m.group(2)
        currency = m.group(3) or "元"
        factor = _UNIT_TO_FACTOR.get(unit, 1)
        value = int(amount * factor)
        return f"{m.group(0)} [≈ {value:,} {currency}]"
    return _PATTERN.sub(_sub, text)
'''


_HTML_EMPTY_TAG_STRIP = '''/**
 * HTML 空标签清理(模板)
 *
 * 删除 <p></p>、<span></span>、<div></div> 等空容器(包括只含空白/&nbsp; 的)。
 * 保留 <br/> / <hr/> 等本身就无内容的自闭合标签。
 *
 * NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
 */

const EMPTY_CONTAINER_TAGS = ["p", "span", "div", "section", "article", "li"];

/**
 * 把 HTML 字符串中的空容器删除。返回清理后的 HTML。
 *
 * @param {string} html - 输入 HTML 字符串
 * @returns {string} 清理后的 HTML
 */
function stripEmpty(html) {
  if (!html || typeof html !== "string") return html;
  let prev;
  let curr = html;
  // 反复迭代,直到没有可清理的空标签为止(处理嵌套空容器)
  do {
    prev = curr;
    for (const tag of EMPTY_CONTAINER_TAGS) {
      const re = new RegExp(
        `<${tag}(?:\\\\s[^>]*)?>(?:\\\\s|&nbsp;|<br\\\\s*/?>)*</${tag}>`,
        "gi",
      );
      curr = curr.replace(re, "");
    }
  } while (curr !== prev);
  return curr;
}

module.exports = { stripEmpty };
'''


_MD_TABLE_ALIGN = '''/**
 * markdown 表格列对齐修复(模板)
 *
 * 输入的 markdown 表格可能存在:
 *  - 分隔行 |---|---| 的列数与表头不一致
 *  - 数据行 cell 数量与表头不一致
 *
 * 该脚本按表头列数补齐分隔行和每条数据行,避免渲染崩坏。
 *
 * NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
 */

/**
 * @param {string} md - markdown 文本
 * @returns {string} 修复后的 markdown
 */
function alignTables(md) {
  const lines = md.split("\\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\\s*\\|.+\\|\\s*$/.test(line) && i + 1 < lines.length && /^\\s*\\|?\\s*:?-+:?\\s*(\\|\\s*:?-+:?\\s*)*\\|?\\s*$/.test(lines[i + 1])) {
      const cols = line.split("|").filter((c, idx, arr) => !(idx === 0 && c.trim() === "") && !(idx === arr.length - 1 && c.trim() === "")).length;
      out.push(line);
      out.push("| " + Array(cols).fill("---").join(" | ") + " |");
      i += 2;
      while (i < lines.length && /\\|/.test(lines[i])) {
        const cells = lines[i].split("|").map((c) => c.trim());
        const inner = cells.slice(cells[0] === "" ? 1 : 0, cells[cells.length - 1] === "" ? cells.length - 1 : cells.length);
        while (inner.length < cols) inner.push("");
        out.push("| " + inner.slice(0, cols).join(" | ") + " |");
        i++;
      }
      continue;
    }
    out.push(line);
    i++;
  }
  return out.join("\\n");
}

module.exports = { alignTables };
'''


_CN_LAW_CLAUSE_NORMALIZE = '''/**
 * 法规条款编号统一(模板)
 *
 * 把"第Ｘ条"、"第x条"、"第 X 條"、"第壹条" 等多变写法统一为
 * 标准 "第 X 条"(其中 X 为阿拉伯数字)。
 *
 * 同时支持:
 *  - "第 X 款"、"第 X 项"、"第 X 章"、"第 X 节"
 *  - 繁体 條 → 条
 *
 * NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
 */

const CN_DIGIT: Record<string, number> = {
  零: 0, 一: 1, 壹: 1, 二: 2, 贰: 2, 兩: 2, 两: 2, 三: 3, 叁: 3,
  四: 4, 肆: 4, 五: 5, 伍: 5, 六: 6, 陆: 6, 七: 7, 柒: 7,
  八: 8, 捌: 8, 九: 9, 玖: 9, 十: 10, 拾: 10,
};

function cnDigitsToInt(token: string): number | null {
  if (/^\\d+$/.test(token)) return parseInt(token, 10);
  // 简单匹配 "二十一"、"十"、"百" 等
  let total = 0;
  let current = 0;
  for (const ch of token) {
    const d = CN_DIGIT[ch];
    if (d == null) return null;
    if (d >= 10) {
      total += (current || 1) * d;
      current = 0;
    } else {
      current = d;
    }
  }
  return total + current;
}

export function normalizeClauseNumbering(text: string): string {
  return text.replace(
    /第\\s*([\\d０-９一壹二贰兩两三叁四肆五伍六陆七柒八捌九玖十拾]+)\\s*([条條款项項章节節])/g,
    (_, raw, unit) => {
      // 把全角数字转半角
      const tok = raw.replace(/[０-９]/g, (c: string) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
      const value = cnDigitsToInt(tok);
      const u = unit === "條" ? "条" : unit === "項" ? "项" : unit === "節" ? "节" : unit;
      return value == null ? `第 ${tok} ${u}` : `第 ${value} ${u}`;
    },
  );
}
'''


_PII_PLACEHOLDER_AUDIT = '''"""
PII 占位符审计(模板)

扫描文本中的 [REDACTED] / [SECRET] / [PII] / [PHONE] / [EMAIL] 等占位符,
统计每类出现次数与首次行号,输出审计报告(JSON-serializable dict)。

该脚本不修改正文,仅用于审计。可在 governance profile 中绑定到
post_governance stage,作为出仓前的最后一次合规检查。

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re
from typing import TypedDict

_PLACEHOLDER_RE = re.compile(r"\\[(REDACTED|SECRET|PII|PHONE|EMAIL|ID_CARD|BANK_CARD)\\]")


class AuditReport(TypedDict):
    total: int
    by_kind: dict[str, int]
    first_line_by_kind: dict[str, int]


def audit(text: str) -> AuditReport:
    by_kind: dict[str, int] = {}
    first_line_by_kind: dict[str, int] = {}
    for lineno, line in enumerate(text.split("\\n"), start=1):
        for match in _PLACEHOLDER_RE.finditer(line):
            kind = match.group(1)
            by_kind[kind] = by_kind.get(kind, 0) + 1
            first_line_by_kind.setdefault(kind, lineno)
    return AuditReport(
        total=sum(by_kind.values()),
        by_kind=by_kind,
        first_line_by_kind=first_line_by_kind,
    )
'''


_GOV_QA_SPLIT_BY_SEPARATOR = '''"""
政务客服 QA 单元切分(模板)

把常州 12345 / 政务服务 / 一件事指南等知识库文件,按统一分隔符
"==##########==" 切分为 QA 单元列表;去除空白单元,保留行内换行。

适用文件:
- 12345QA.txt(常州市本级/各区)
- 专题常见问答.txt
- 一件事指南.txt
- 事项清单.txt

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_SEPARATOR = re.compile(r"^\\s*==##+==\\s*$", re.MULTILINE)


def split_units(text: str) -> list[str]:
    """按 ==##########== 分隔符切出 QA 单元,保留单元内换行。"""
    if not text:
        return []
    parts = _SEPARATOR.split(text)
    units = [p.strip() for p in parts if p and p.strip()]
    return units
'''


_GOV_QA_FIELD_PARSE = '''"""
政务 12345 QA 字段解析(模板)

把单个 QA 单元(由 ==##########== 切分而来)解析成结构化字典:
- question: "问题：[xxx]" 中的方括号内容
- answer: "答案：xxx" 起到下一个识别字段或文末
- source_dept: "来源部门：xxx"
- aliases: "==##相似问法：xxx##==" 内逗号/顿号分隔
- links: 文本中 **<http(s)://...>** 双星包裹 URL 列表

适用文件: 12345QA.txt / 专题问答.txt / 操作指引.txt 等。

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_QUESTION_RE = re.compile(r"问题[：:]\\s*\\[([^\\]]+)\\]")
_ANSWER_RE = re.compile(r"答案[：:]\\s*(.*?)(?=\\n(?:来源部门|==##|$))", re.DOTALL)
_SOURCE_RE = re.compile(r"来源部门[：:]\\s*([^\\n]+)")
_ALIASES_RE = re.compile(r"==##\\s*相似问法[：:]([^#]+)##==")
_LINK_RE = re.compile(r"\\*\\*<((?:https?://)[^>]+)>\\*\\*")


def parse_qa_unit(unit: str) -> dict:
    question_m = _QUESTION_RE.search(unit)
    answer_m = _ANSWER_RE.search(unit)
    source_m = _SOURCE_RE.search(unit)
    aliases_m = _ALIASES_RE.search(unit)
    aliases_raw = (aliases_m.group(1) if aliases_m else "").strip()
    aliases = [a.strip() for a in re.split(r"[、,，]", aliases_raw) if a.strip()]
    return {
        "question": (question_m.group(1).strip() if question_m else ""),
        "answer": (answer_m.group(1).strip() if answer_m else ""),
        "source_dept": (source_m.group(1).strip() if source_m else ""),
        "aliases": aliases,
        "links": _LINK_RE.findall(unit),
    }
'''


_GOV_ITEM_FIELD_PARSE = '''"""
政务服务事项清单字段解析(模板)

把常州事项清单 .txt(8 个区/市)的单个事项单元
(由 ==##########== 分隔)解析为结构化字典,涵盖 13+ 标准字段:

  事项名称 / 行使层级 / 办理形式 / 办理地点 / 办理时间
  受理条件 / 办件类型 / 法定办结时限 / 承诺办结时限
  收费情况 / 咨询方式 / 监督投诉方式 / 办理材料
  办理流程 / 在线办理地址

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_FIELD_KEYS = (
    "事项名称", "行使层级", "办理形式", "办理地点", "办理时间",
    "受理条件", "办件类型", "法定办结时限", "承诺办结时限",
    "收费情况", "咨询方式", "监督投诉方式", "办理材料",
    "办理流程", "在线办理地址",
)
_TITLE_RE = re.compile(r"\\[\\s*事项名称[：:]\\s*([^\\]]+)\\]")


def parse_item_unit(unit: str) -> dict:
    title_m = _TITLE_RE.search(unit)
    result: dict[str, str] = {"事项名称": title_m.group(1).strip() if title_m else ""}
    for key in _FIELD_KEYS[1:]:
        pat = re.compile(
            rf"^{re.escape(key)}[：:]\\s*(.*?)(?=^(?:{'|'.join(re.escape(k) for k in _FIELD_KEYS)})[：:]|\\Z)",
            re.DOTALL | re.MULTILINE,
        )
        m = pat.search(unit)
        if m:
            result[key] = m.group(1).strip()
    return result
'''


_GOV_PHONE_NORMALIZE = '''"""
常州政务电话规范化(模板)

把文本中政务电话写法统一为可点击的规范形态:
- "0519-12345" / "0519 12345" / "(0519)12345" / "0519 - 12345" → "0519-12345"
- 单独 "12345" 政务服务热线 → "12345(政务服务热线)"
- 0519-xxxxxxxx(8 位) / 0519-xxxxxxx(7 位) 区号补齐

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_AREA_PHONE = re.compile(r"[\\(（]?\\s*0519\\s*[\\)）]?[\\s\\-]*(\\d{7,8})")
_BARE_12345 = re.compile(r"(?<!\\d)12345(?!\\d)")


def normalize(text: str) -> str:
    def _fix_area(m: "re.Match[str]") -> str:
        return f"0519-{m.group(1)}"
    text = _AREA_PHONE.sub(_fix_area, text)
    # 仅对裸 12345 标注,避免改坏已规范化的 0519-12345
    text = re.sub(
        r"(?<!\\-)" + _BARE_12345.pattern,
        "12345(政务服务热线)",
        text,
    )
    return text
'''


_GOV_URL_UNWRAP = '''"""
政务文档双星包裹 URL 解包(模板)

把 markdown 中的 "**<https://example.com>**" 这种双星包裹 + 尖括号
的链接形式,解包为标准 markdown 链接 "[example.com](https://example.com)";
保留 URL 作为文字便于检索召回。

适用文件: 12345QA.txt / 事项清单.txt(在线办理地址)等。

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re
from urllib.parse import urlparse

_BOLD_BRACKETED = re.compile(r"\\*\\*<((?:https?://)[^>\\s]+)>\\*\\*")


def unwrap(text: str) -> str:
    def _sub(m: "re.Match[str]") -> str:
        url = m.group(1)
        try:
            host = urlparse(url).netloc or url
        except Exception:
            host = url
        return f"[{host}]({url})"
    return _BOLD_BRACKETED.sub(_sub, text)
'''


_GOV_KEYWORD_EXTRACT = '''"""
政务文档元数据关键字抽取(模板)

抽取以下两种政务知识库内嵌元数据块:
  ==##关键字：xxx、yyy、zzz##==
  ==##相似问法：xxx、yyy##==

返回 {"keywords": [...], "aliases": [...]},便于灌入 chunk metadata
做 HyDE 检索召回扩展。

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_KW_RE = re.compile(r"==##\\s*关键字[：:]([^#]+)##==")
_AL_RE = re.compile(r"==##\\s*相似问法[：:]([^#]+)##==")


def _split(raw: str) -> list[str]:
    return [s.strip() for s in re.split(r"[、,，;；]", raw) if s.strip()]


def extract(text: str) -> dict:
    keywords: list[str] = []
    aliases: list[str] = []
    for m in _KW_RE.finditer(text):
        keywords.extend(_split(m.group(1)))
    for m in _AL_RE.finditer(text):
        aliases.extend(_split(m.group(1)))
    return {
        "keywords": sorted(set(keywords)),
        "aliases": sorted(set(aliases)),
    }
'''


_GOV_QA_XLSX_HEADER_ALIGN = '''"""
政务 QA xlsx 表头多变异统一(模板)

不同部门导出的 xlsx 表头差异:
- 公积金: 问题 / 答案 / 相似问法 / 关键词 / 适用区域 / 办事链接
- 不动产: 类目路径 / 问题 / 相似问法 / 答案
- 医保:   序号 / 问答标题 / 问答答案 / 内容生效时间 / 内容失效时间 / 问答提供部门
- 高频:   问题 / 相似问法 / 答案

此脚本把多变表头映射为统一字段名,接入下游 RAG 元数据:
  question / answer / aliases / keywords / region / link / source_dept / category / valid_from / valid_to

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

HEADER_MAP = {
    # 问题
    "问题": "question", "问答标题": "question", "标题": "question",
    # 答案
    "答案": "answer", "问答答案": "answer", "答复内容": "answer",
    # 相似问法
    "相似问法": "aliases", "相似问题": "aliases", "问法": "aliases",
    # 关键词
    "关键词": "keywords", "关键字": "keywords",
    # 区域
    "适用区域": "region", "区域": "region", "适用范围": "region",
    # 链接
    "办事链接": "link", "链接": "link", "URL": "link", "网址": "link",
    # 来源部门
    "来源部门": "source_dept", "问答提供部门": "source_dept", "提供部门": "source_dept",
    # 分类
    "类目路径": "category", "类目": "category", "分类": "category",
    # 生效失效
    "内容生效时间": "valid_from", "生效时间": "valid_from",
    "内容失效时间": "valid_to", "失效时间": "valid_to",
}


def align_row(headers: list[str], row: list) -> dict:
    """按 HEADER_MAP 把 row 转为规范化字段字典;未识别的表头保留原名。"""
    out: dict = {}
    for h, v in zip(headers, row):
        key = HEADER_MAP.get(str(h or "").strip(), str(h or "").strip())
        if key:
            out[key] = v
    return out
'''


_GOV_TERM_CANONICALIZE = '''"""
政务专名规范化(模板)

把常州/江苏政务知识库中常见的术语异写统一为权威写法,
便于嵌入向量和 BM25 检索一致命中。

示例:
- 苏服办APP / 苏服办应用 / 苏服办app → 苏服办
- 江苏政务服务网 / 江苏政务网 → 江苏政务服务网
- 苏证通APP / 苏证通app → 苏证通
- 常州市本级 / 常州本级 / 市本级 → 常州市本级
- 12345政务热线 / 12345热线 → 12345 政务服务热线

NOTE: 该脚本仅作模板展示,入库管道不会自动执行。
"""

import re

_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"苏服办\\s*(?:APP|app|应用)"), "苏服办"),
    (re.compile(r"江苏政务网"), "江苏政务服务网"),
    (re.compile(r"苏证通\\s*(?:APP|app)"), "苏证通"),
    (re.compile(r"(?<!常州)市本级"), "常州市本级"),
    (re.compile(r"常州本级"), "常州市本级"),
    (re.compile(r"12345\\s*(?:政务)?\\s*热线"), "12345 政务服务热线"),
    (re.compile(r"政务服务中心\\s*(?:大厅)?"), "政务服务中心"),
]


def canonicalize(text: str) -> str:
    for pat, repl in _RULES:
        text = pat.sub(repl, text)
    return text
'''


_BUILTIN_PROCESSING_SCRIPTS: tuple[BuiltinProcessingScript, ...] = (
    BuiltinProcessingScript(
        key="cn_number_normalize",
        name="中文大写金额归一",
        description="把壹万贰仟 / 一百二十万 等中文(含繁体)金额表达转换为阿拉伯数字。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_CN_NUMBER_NORMALIZE,
        tags=["builtin", "zh", "finance", "number_normalize"],
    ),
    BuiltinProcessingScript(
        key="pdf_softbreak_repair",
        name="PDF 软换行修复",
        description="把 PDF 抽取后被拆成多行的同一句子合并;保留段落空行与标题/列表前缀。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_PDF_SOFTBREAK_REPAIR,
        tags=["builtin", "pdf", "softbreak", "parse_fix"],
    ),
    BuiltinProcessingScript(
        key="cn_punct_normalize",
        name="中文标点全/半角统一",
        description="中文段落统一全角标点,英文/代码段落保持半角。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_CN_PUNCT_NORMALIZE,
        tags=["builtin", "zh", "punctuation", "normalize"],
    ),
    BuiltinProcessingScript(
        key="currency_unit_expand",
        name="货币单位口径展开",
        description="把 1.2 亿元 / 350 万元 展开为完整阿拉伯数字 [≈ 120,000,000 元] 并保留原文。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_governance",
        content=_CURRENCY_UNIT_EXPAND,
        tags=["builtin", "zh", "finance", "currency_unit"],
    ),
    BuiltinProcessingScript(
        key="html_empty_tag_strip",
        name="HTML 空标签清理",
        description="移除 <p></p> / <span></span> / <div></div> 等空容器,保留 <br/> / <hr/>。模板代码,不会被入库管道执行。",
        language="javascript",
        stage="post_parse",
        content=_HTML_EMPTY_TAG_STRIP,
        tags=["builtin", "html", "empty_tag", "cleanup"],
    ),
    BuiltinProcessingScript(
        key="md_table_align",
        name="markdown 表格列对齐",
        description="按表头列数补齐分隔行和数据行的 cell 数量,避免表格渲染崩坏。模板代码,不会被入库管道执行。",
        language="javascript",
        stage="post_governance",
        content=_MD_TABLE_ALIGN,
        tags=["builtin", "markdown", "table", "alignment"],
    ),
    BuiltinProcessingScript(
        key="cn_law_clause_normalize",
        name="法规条款编号统一",
        description="把第Ｘ条 / 第x条 / 第 X 條 / 第壹条 统一为标准 第 X 条;支持条/款/项/章/节。模板代码,不会被入库管道执行。",
        language="typescript",
        stage="post_governance",
        content=_CN_LAW_CLAUSE_NORMALIZE,
        tags=["builtin", "zh", "legal", "clause_numbering"],
    ),
    BuiltinProcessingScript(
        key="pii_placeholder_audit",
        name="PII 占位符审计",
        description="扫描 [REDACTED]/[SECRET]/[PII] 等占位符统计与首次出现行号,不修改正文。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_governance",
        content=_PII_PLACEHOLDER_AUDIT,
        tags=["builtin", "pii", "audit", "compliance"],
    ),
    # ---------- 政务客服垂直(常州 12345 / 政务事项 / 一件事) ----------
    BuiltinProcessingScript(
        key="gov_qa_split_by_separator",
        name="政务 QA 按分隔符切分",
        description="按 ==##########== 分隔符切分常州 12345 / 政务知识库文件为 QA 单元列表。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_GOV_QA_SPLIT_BY_SEPARATOR,
        tags=["builtin", "zh", "gov", "12345", "split"],
    ),
    BuiltinProcessingScript(
        key="gov_qa_field_parse",
        name="政务 12345 QA 字段解析",
        description="把单个 QA 单元解析为 {question, answer, source_dept, aliases, links} 结构化字典。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_GOV_QA_FIELD_PARSE,
        tags=["builtin", "zh", "gov", "12345", "field_parse"],
    ),
    BuiltinProcessingScript(
        key="gov_item_field_parse",
        name="政务事项清单字段解析",
        description="解析常州事项清单 14+ 标准字段(事项名称/办理形式/办件类型/法定办结时限/在线办理地址等)。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_GOV_ITEM_FIELD_PARSE,
        tags=["builtin", "zh", "gov", "item_list", "field_parse"],
    ),
    BuiltinProcessingScript(
        key="gov_phone_normalize",
        name="常州政务电话规范化",
        description="把 (0519) / 0519 / 0519- 多种写法的政务电话统一为 0519-xxxxxxxx;裸 12345 标注为政务服务热线。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_GOV_PHONE_NORMALIZE,
        tags=["builtin", "zh", "gov", "phone", "normalize"],
    ),
    BuiltinProcessingScript(
        key="gov_url_unwrap",
        name="政务文档双星包裹 URL 解包",
        description="把 **<https://xxx>** 双星包裹解为标准 markdown [host](url),保留 host 作为可检索文字。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_GOV_URL_UNWRAP,
        tags=["builtin", "zh", "gov", "url_unwrap", "markdown"],
    ),
    BuiltinProcessingScript(
        key="gov_keyword_extract",
        name="政务关键字/相似问法抽取",
        description="抽取 ==##关键字##== / ==##相似问法##== 元数据块为 {keywords, aliases} 列表,灌入 chunk metadata 做 HyDE 召回扩展。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_GOV_KEYWORD_EXTRACT,
        tags=["builtin", "zh", "gov", "metadata", "keyword"],
    ),
    BuiltinProcessingScript(
        key="gov_qa_xlsx_header_align",
        name="政务 QA xlsx 表头规范化",
        description="把公积金/不动产/医保/高频不同部门 xlsx 表头(问题/问答标题/问答答案/相似问法/适用区域 等)统一为 question/answer/aliases/region 等规范字段。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_parse",
        content=_GOV_QA_XLSX_HEADER_ALIGN,
        tags=["builtin", "zh", "gov", "xlsx", "header_align"],
    ),
    BuiltinProcessingScript(
        key="gov_term_canonicalize",
        name="政务专名规范化",
        description="苏服办 APP / 江苏政务网 / 苏证通 APP / 市本级 / 12345 热线 等专名统一为权威写法,提升检索一致命中。模板代码,不会被入库管道执行。",
        language="python",
        stage="post_governance",
        content=_GOV_TERM_CANONICALIZE,
        tags=["builtin", "zh", "gov", "term_canonicalize"],
    ),
)


def list_builtin_processing_scripts() -> list[BuiltinProcessingScript]:
    return list(_BUILTIN_PROCESSING_SCRIPTS)


__all__ = [
    "BuiltinProcessingScript",
    "ProcessingScriptLanguage",
    "ProcessingScriptStage",
    "list_builtin_processing_scripts",
]
