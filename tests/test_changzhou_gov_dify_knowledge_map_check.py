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
