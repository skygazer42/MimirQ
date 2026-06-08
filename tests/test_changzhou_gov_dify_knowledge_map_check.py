import importlib.util
import json
from pathlib import Path


def _load_module():
    path = Path("scripts/changzhou_gov_dify_knowledge_map_check.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_knowledge_map_check", str(path))
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _complete_map() -> dict:
    routes = {
        "新北区": ["新北区", "新北"],
        "经开区": ["经开区", "经开"],
        "天宁区": ["天宁区", "天宁"],
        "武进区": ["武进区", "武进"],
        "溧阳市": ["溧阳市", "溧阳"],
        "金坛区": ["金坛区", "金坛"],
        "钟楼区": ["钟楼区", "钟楼"],
    }
    payload: dict = {
        "changzhou_city_service": {
            "dataset_ids": ["city-dataset"],
            "query_routes": [
                {
                    "terms": terms,
                    "dataset_ids": [f"{district}-事项", f"{district}-问答"],
                    "mode": "prepend",
                }
                for district, terms in routes.items()
            ],
        }
    }
    for district in routes:
        payload[f"changzhou_{district}_service"] = [f"{district}-事项", f"{district}-问答", "city-dataset"]
    payload["changzhou_all_districts_service"] = [
        "新北区-事项",
        "经开区-事项",
        "天宁区-事项",
        "武进区-事项",
        "溧阳市-事项",
        "金坛区-事项",
        "钟楼区-事项",
    ]
    return payload


def test_complete_changzhou_knowledge_map_passes() -> None:
    mod = _load_module()

    report = mod.check_knowledge_map(_complete_map(), generated_at="2026-06-06T00:00:00Z")

    assert report["summary"] == {
        "passed": True,
        "failed_conditions": [],
        "city_dataset_count": 1,
        "route_count": 7,
        "district_routes_checked": 7,
        "district_knowledge_ids_checked": 7,
        "plugin_refs_checked": 0,
        "plugin_refs_invalid": 0,
        "plugin_refs_missing_retrieval_policy": 0,
    }
    assert report["district_routes"]["missing"] == []
    assert report["district_knowledge_ids"]["missing"] == []


def test_missing_alias_and_district_mapping_fail_with_actionable_conditions() -> None:
    mod = _load_module()
    payload = _complete_map()
    payload["changzhou_city_service"]["query_routes"][1]["terms"] = ["经开区"]
    del payload["changzhou_经开区_service"]

    report = mod.check_knowledge_map(payload, generated_at="2026-06-06T00:00:00Z")

    assert report["summary"]["passed"] is False
    assert "route_terms_missing:经开区:经开" in report["summary"]["failed_conditions"]
    assert "district_knowledge_id_missing:changzhou_经开区_service" in report["summary"]["failed_conditions"]
    assert report["district_routes"]["incomplete"] == [{"district": "经开区", "missing_terms": ["经开"]}]
    assert report["district_knowledge_ids"]["missing"] == ["changzhou_经开区_service"]


def test_plugin_refs_with_retrieval_policy_are_reported(monkeypatch) -> None:
    mod = _load_module()
    payload = _complete_map()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    payload["changzhou_city_service"]["plugin_refs"] = [plugin_ref]

    monkeypatch.setattr(
        mod,
        "resolve_plugin_retrieval_policy",
        lambda ref: {"schema": "mimirq.retrieval_policy.v1"} if ref == plugin_ref else {},
        raising=False,
    )

    report = mod.check_knowledge_map(payload, generated_at="2026-06-06T00:00:00Z")

    assert report["summary"]["passed"] is True
    assert report["summary"]["plugin_refs_checked"] == 1
    assert report["summary"]["plugin_refs_invalid"] == 0
    assert report["summary"]["plugin_refs_missing_retrieval_policy"] == 0
    assert report["plugin_refs"] == {
        "checked": [{"knowledge_id": "changzhou_city_service", "plugin_ref": plugin_ref}],
        "invalid": [],
        "missing_retrieval_policy": [],
    }


def test_district_knowledge_mapping_object_can_carry_plugin_refs(monkeypatch) -> None:
    mod = _load_module()
    payload = _complete_map()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    payload["changzhou_经开区_service"] = {
        "dataset_ids": ["经开区-事项", "经开区-问答", "city-dataset"],
        "plugin_refs": [plugin_ref],
    }

    monkeypatch.setattr(
        mod,
        "resolve_plugin_retrieval_policy",
        lambda ref: {"schema": "mimirq.retrieval_policy.v1"} if ref == plugin_ref else {},
        raising=False,
    )

    report = mod.check_knowledge_map(payload, generated_at="2026-06-06T00:00:00Z")

    assert report["summary"]["passed"] is True
    assert report["district_knowledge_ids"]["dataset_ids_missing"] == []
    assert report["summary"]["plugin_refs_checked"] == 1
    assert report["plugin_refs"]["checked"] == [
        {"knowledge_id": "changzhou_经开区_service", "plugin_ref": plugin_ref}
    ]


def test_plugin_refs_without_retrieval_policy_fail_with_actionable_conditions(monkeypatch) -> None:
    mod = _load_module()
    payload = _complete_map()
    plugin_ref = "plugin:demo-service@1.0.0:chunk"
    payload["changzhou_city_service"]["plugin_refs"] = [plugin_ref]

    monkeypatch.setattr(mod, "resolve_plugin_retrieval_policy", lambda _ref: {}, raising=False)

    report = mod.check_knowledge_map(payload, generated_at="2026-06-06T00:00:00Z")

    assert report["summary"]["passed"] is False
    assert report["summary"]["plugin_refs_checked"] == 1
    assert report["summary"]["plugin_refs_invalid"] == 0
    assert report["summary"]["plugin_refs_missing_retrieval_policy"] == 1
    assert (
        "plugin_retrieval_policy_missing:changzhou_city_service:plugin:demo-service@1.0.0:chunk"
        in report["summary"]["failed_conditions"]
    )
    assert report["plugin_refs"]["missing_retrieval_policy"] == [
        {"knowledge_id": "changzhou_city_service", "plugin_ref": plugin_ref}
    ]


def test_invalid_plugin_refs_fail_before_registry_lookup(monkeypatch) -> None:
    mod = _load_module()
    payload = _complete_map()
    payload["changzhou_city_service"]["plugin_refs"] = ["demo-service"]
    calls: list[str] = []

    monkeypatch.setattr(mod, "resolve_plugin_retrieval_policy", lambda ref: calls.append(ref) or {}, raising=False)

    report = mod.check_knowledge_map(payload, generated_at="2026-06-06T00:00:00Z")

    assert report["summary"]["passed"] is False
    assert report["summary"]["plugin_refs_checked"] == 1
    assert report["summary"]["plugin_refs_invalid"] == 1
    assert report["summary"]["plugin_refs_missing_retrieval_policy"] == 0
    assert "plugin_ref_invalid:changzhou_city_service:demo-service" in report["summary"]["failed_conditions"]
    assert report["plugin_refs"]["invalid"] == [{"knowledge_id": "changzhou_city_service", "plugin_ref": "demo-service"}]
    assert calls == []


def test_cli_loads_env_file_and_writes_report(tmp_path: Path) -> None:
    mod = _load_module()
    env_file = tmp_path / ".env"
    out = tmp_path / "report.json"
    env_file.write_text(
        "IGNORED=1\n"
        f"DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON='{json.dumps(_complete_map(), ensure_ascii=False)}'\n",
        encoding="utf-8",
    )

    rc = mod.main(["--env-file", str(env_file), "--out", str(out)])

    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["passed"] is True
    assert report["summary"]["route_count"] == 7


def test_cli_resolves_plugin_refs_from_repo_root(tmp_path: Path) -> None:
    import subprocess
    import sys

    plugin_ref = "plugin:changzhou-gov-service-knowledge@1.0.0:chunk"
    payload = _complete_map()
    payload["changzhou_city_service"]["plugin_refs"] = [plugin_ref]
    env_file = tmp_path / ".env"
    out = tmp_path / "report.json"
    env_file.write_text(
        "IGNORED=1\n"
        f"DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON='{json.dumps(payload, ensure_ascii=False)}'\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/changzhou_gov_dify_knowledge_map_check.py",
            "--env-file",
            str(env_file),
            "--out",
            str(out),
        ],
        check=False,
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["plugin_refs_checked"] == 1
    assert report["summary"]["plugin_refs_missing_retrieval_policy"] == 0
