from __future__ import annotations

import yaml


def test_write_glossary_candidates_creates_generated_yaml_and_merges_on_load(monkeypatch, tmp_path):  # noqa: ANN001
    import app.rag.industry_rules.loaders.yaml_loader as module

    rulesets_root = tmp_path / "rulesets"
    ruleset_dir = rulesets_root / "industrial_control"
    ruleset_dir.mkdir(parents=True)
    (ruleset_dir / "glossary.yaml").write_text("485:\n  - RS-485\n", encoding="utf-8")
    (ruleset_dir / "patterns.yaml").write_text("[]\n", encoding="utf-8")
    (ruleset_dir / "intents.yaml").write_text("[]\n", encoding="utf-8")

    monkeypatch.setattr(module, "_ruleset_root", lambda: rulesets_root, raising=True)

    result = module.write_glossary_candidates(
        "industrial_control",
        [{"token": "485"}, {"token": "MCU"}, {"token": "MCU"}, {"token": ""}],
    )

    assert result["ruleset"] == "industrial_control"
    assert result["candidate_count"] == 2
    assert result["added_count"] == 1
    assert result["skipped_count"] == 1
    assert result["added_tokens"] == ["MCU"]
    assert result["skipped_tokens"] == ["485"]

    generated_path = ruleset_dir / "glossary.generated.yaml"
    generated = yaml.safe_load(generated_path.read_text(encoding="utf-8"))
    assert generated == {"MCU": []}

    merged = module.load_ruleset("industrial_control")
    assert merged.glossary["485"] == ["RS-485"]
    assert merged.glossary["MCU"] == []
