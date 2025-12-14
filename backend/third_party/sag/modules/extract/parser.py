"""
Utility helpers for parsing entity values from LLM output.
"""
import re


class EntityValueParser:
    def normalize_name(self, name: str) -> str:
        return re.sub(r"\s+", " ", name.strip().lower())

