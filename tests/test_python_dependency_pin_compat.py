from __future__ import annotations

import re
from pathlib import Path


def _extract_pin(name: str) -> str:
    text = Path('requirements.txt').read_text(encoding='utf-8')
    match = re.search(rf'^{re.escape(name)}==([^\s]+)$', text, flags=re.MULTILINE)
    assert match is not None, f'Missing {name} pin in requirements.txt'
    return match.group(1)


def test_arq_redis_pin_stays_compatible() -> None:
    arq_pin = _extract_pin('arq')
    redis_pin = _extract_pin('redis')

    assert arq_pin == '0.27.0'
    assert int(redis_pin.split('.', 1)[0]) < 6
