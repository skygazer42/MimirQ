from __future__ import annotations

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app() -> FastAPI:
    from app.api.v1.industry_rules import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/industry-rules")
    return app


def test_put_glossary_endpoint_persists_curated_glossary(monkeypatch, tmp_path):  # noqa: ANN001
    import app.rag.industry_rules.loaders.yaml_loader as yaml_loader

    rulesets_root = tmp_path / "rulesets"
    ruleset_dir = rulesets_root / "industrial_control"
    ruleset_dir.mkdir(parents=True)
    (ruleset_dir / "glossary.yaml").write_text("485:\n  - RS-485\n", encoding="utf-8")
    (ruleset_dir / "patterns.yaml").write_text("[]\n", encoding="utf-8")
    (ruleset_dir / "intents.yaml").write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(yaml_loader, "_ruleset_root", lambda: rulesets_root, raising=True)

    client = TestClient(_app())
    res = client.put(
        "/api/v1/industry-rules/rulesets/industrial_control/glossary",
        json={"glossary": {"PLC": ["控制器"], "485": ["RS-485"]}},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.industry_rules_update.v1"
    assert body["section"] == "glossary"
    assert body["updated_count"] == 2

    saved = yaml.safe_load((ruleset_dir / "glossary.yaml").read_text(encoding="utf-8"))
    assert saved == {"PLC": ["控制器"], "485": ["RS-485"]}


def test_put_patterns_and_intents_endpoints_persist_sections(monkeypatch, tmp_path):  # noqa: ANN001
    import app.rag.industry_rules.loaders.yaml_loader as yaml_loader

    rulesets_root = tmp_path / "rulesets"
    ruleset_dir = rulesets_root / "industrial_control"
    ruleset_dir.mkdir(parents=True)
    (ruleset_dir / "glossary.yaml").write_text("{}\n", encoding="utf-8")
    (ruleset_dir / "patterns.yaml").write_text("[]\n", encoding="utf-8")
    (ruleset_dir / "intents.yaml").write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(yaml_loader, "_ruleset_root", lambda: rulesets_root, raising=True)

    client = TestClient(_app())
    res1 = client.put(
        "/api/v1/industry-rules/rulesets/industrial_control/patterns",
        json={"patterns": [{"pattern": "XX 没数据", "followup": "请补软件名"}]},
    )
    res2 = client.put(
        "/api/v1/industry-rules/rulesets/industrial_control/intents",
        json={"intents": [{"name": "故障排查", "retrieval_profile": "recall20"}]},
    )

    assert res1.status_code == 200, res1.text
    assert res2.status_code == 200, res2.text

    patterns = yaml.safe_load((ruleset_dir / "patterns.yaml").read_text(encoding="utf-8"))
    intents = yaml.safe_load((ruleset_dir / "intents.yaml").read_text(encoding="utf-8"))
    assert patterns == [{"pattern": "XX 没数据", "followup": "请补软件名"}]
    assert intents == [{"name": "故障排查", "retrieval_profile": "recall20"}]
