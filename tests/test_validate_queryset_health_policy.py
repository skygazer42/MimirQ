from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_validate_queryset_health_policy_script_passes_with_valid_policy(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    mod = _load_script("scripts/validate_queryset_health_policy.py")
    policy = tmp_path / "policy.json"
    out = tmp_path / "policy.normalized.json"

    policy.write_text(
        json.dumps(
            {
                "miss_rate_regression_threshold": 0.2,
                "weak_hit_rr_threshold": 0.15,
                "hard_cases_limit": 8,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rc = mod.main(["--policy", str(policy), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("miss_rate_regression_threshold") == 0.2
    assert payload.get("weak_hit_rr_threshold") == 0.15
    assert payload.get("hard_cases_limit") == 8
    assert "valid" in (capsys.readouterr().out or "").lower()


def test_validate_queryset_health_policy_script_rejects_unknown_keys(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    mod = _load_script("scripts/validate_queryset_health_policy.py")
    policy = tmp_path / "policy.invalid.json"
    policy.write_text(json.dumps({"oops": 1}, ensure_ascii=False), encoding="utf-8")

    rc = mod.main(["--policy", str(policy)])
    assert rc != 0
    err = (capsys.readouterr().err or "").lower()
    assert "unknown policy keys" in err


def test_ci_queryset_health_policy_file_is_valid() -> None:
    from app.services.queryset_health_service import validate_and_normalize_queryset_health_policy

    path = Path("ci/queryset_health_policy.v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized = validate_and_normalize_queryset_health_policy(payload)
    assert normalized.get("hard_cases_limit") == 5


def test_makefile_has_queryset_health_policy_target() -> None:
    contents = Path("Makefile").read_text(encoding="utf-8")
    assert re.search(r"^check-queryset-health-policy:$", contents, flags=re.MULTILINE)


def test_makefile_verify_includes_queryset_health_policy_check() -> None:
    contents = Path("Makefile").read_text(encoding="utf-8")
    assert "\t@$(MAKE) check-queryset-health-policy" in contents
