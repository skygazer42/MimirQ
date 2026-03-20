"""
Utility helpers for parsing entity values from LLM output.
"""
import re
import unicodedata


class EntityValueParser:
    _ws_re = re.compile(r"\s+")
    _edge_quote_re = re.compile(r"(?:^[\"'`“”‘’]+|[\"'`“”‘’]+$)")
    # Conservative edge punctuation stripping to reduce fragmentation:
    # - We only strip at the edges (not internal), so names like "node.js" are preserved.
    # - We intentionally do NOT strip '#'/'+' to avoid breaking names like "C#" / "C++".
    _edge_strip_chars = " \t\r\n,.;:!?，。；：！？、"

    _wrapping_pairs: tuple[tuple[str, str], ...] = (
        ("(", ")"),
        ("（", "）"),
        ("[", "]"),
        ("【", "】"),
    )

    # Common type aliases (EN + ZH) -> canonical labels.
    _TYPE_MAP: dict[str, str] = {
        # person
        "person": "Person",
        "people": "Person",
        "human": "Person",
        "individual": "Person",
        "人物": "Person",
        "人": "Person",
        "员工": "Person",
        # org
        "org": "Organization",
        "organisation": "Organization",
        "organization": "Organization",
        "company": "Organization",
        "corporation": "Organization",
        "enterprise": "Organization",
        "企业": "Organization",
        "公司": "Organization",
        "组织": "Organization",
        "机构": "Organization",
        # location
        "location": "Location",
        "place": "Location",
        "address": "Location",
        "地点": "Location",
        "位置": "Location",
        "地址": "Location",
        # time/date
        "date": "Date",
        "time": "Date",
        "datetime": "Date",
        "日期": "Date",
        "时间": "Date",
        # misc common
        "event": "Event",
        "事件": "Event",
        "product": "Product",
        "产品": "Product",
        "service": "Service",
        "服务": "Service",
        "system": "System",
        "系统": "System",
        "api": "API",
        "interface": "API",
        "接口": "API",
        "law": "Law",
        "legal": "Law",
        "法规": "Law",
        "法律": "Law",
        "条例": "Law",
        "policy": "Policy",
        "政策": "Policy",
        "standard": "Standard",
        "规范": "Standard",
        "标准": "Standard",
        # skill / SOP-like
        "skill": "Skill",
        "skills": "Skill",
        "技能": "Skill",
        "sop": "Skill",
        # SkillNet-ish taxonomy node types (best-effort).
        "skilltag": "SkillTag",
        "skill_tag": "SkillTag",
        "skill tag": "SkillTag",
        "tag": "SkillTag",
        "标签": "SkillTag",
        "skillcategory": "SkillCategory",
        "skill_category": "SkillCategory",
        "skill category": "SkillCategory",
        "category": "SkillCategory",
        "类别": "SkillCategory",
    }

    def normalize_name(self, name: str) -> str:
        text = unicodedata.normalize("NFKC", str(name or ""))
        text = self._ws_re.sub(" ", text).strip()
        # Trim paired quotes at edges (keep internal punctuation like C++, node.js, e-mail).
        text = self._edge_quote_re.sub("", text).strip()

        # Unwrap common paired wrappers (best-effort), e.g. "(Alice)" / "（Alice）".
        # This reduces fragmentation caused by LLM formatting artifacts.
        for _ in range(3):
            changed = False
            for left, right in self._wrapping_pairs:
                if text.startswith(left) and text.endswith(right) and len(text) > (len(left) + len(right)):
                    text = text[len(left) : -len(right)].strip()
                    changed = True
            if not changed:
                break

        # Strip common punctuation at edges (keeps internal punctuation).
        text = text.strip(self._edge_strip_chars)
        return text.casefold()

    def normalize_type(self, type_name: str) -> str:
        text = unicodedata.normalize("NFKC", str(type_name or ""))
        text = self._ws_re.sub(" ", text).strip()
        if not text:
            return "unknown"
        key = self.normalize_name(text)
        return self._TYPE_MAP.get(key) or text
