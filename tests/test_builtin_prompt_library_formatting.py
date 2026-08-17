import hashlib
import json
from dataclasses import asdict

from app.rag.llm.prompts.builtin_library import list_builtin_prompt_templates


def test_builtin_prompt_library_content_is_byte_stable() -> None:
    templates = list_builtin_prompt_templates()
    payload = json.dumps(
        [asdict(template) for template in templates],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert len(templates) == 33
    assert hashlib.sha256(payload.encode()).hexdigest() == (
        "2d51bbececadb962f62e45e95a56fa82716ccbbabdeebd376945bd89c0a7dbe7"
    )
