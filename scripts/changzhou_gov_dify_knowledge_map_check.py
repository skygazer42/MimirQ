#!/usr/bin/env python3
"""Validate Changzhou Dify external-knowledge mapping before remote probes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "mimirq.changzhou_gov_service_knowledge.dify_knowledge_map_check.v1"
CITY_KNOWLEDGE_ID = "changzhou_city_service"
MAP_ENV_NAME = "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON"
VALID_ROUTE_MODES = {"prepend", "append", "replace"}
REQUIRED_DISTRICT_TERMS: dict[str, tuple[str, ...]] = {
    "新北区": ("新北区", "新北"),
    "经开区": ("经开区", "经开"),
    "天宁区": ("天宁区", "天宁"),
    "武进区": ("武进区", "武进"),
    "溧阳市": ("溧阳市", "溧阳"),
    "金坛区": ("金坛区", "金坛"),
    "钟楼区": ("钟楼区", "钟楼"),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _clean_env_value(value: str) -> str:
    text = _text(value)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def load_env_file(path: str) -> dict[str, str]:
    env_path = Path(_text(path))
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _clean_env_value(value)
    return values


def load_knowledge_map(
    *,
    knowledge_map_json: str = "",
    env_file: str = ".env",
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source_env = env if env is not None else os.environ
    env_file_values = load_env_file(env_file)
    raw = _text(knowledge_map_json) or _text(source_env.get(MAP_ENV_NAME)) or _text(env_file_values.get(MAP_ENV_NAME))
    if not raw:
        raise ValueError(f"{MAP_ENV_NAME} is required")
    payload = json.loads(_clean_env_value(raw))
    if not isinstance(payload, dict):
        raise ValueError(f"{MAP_ENV_NAME} must be a JSON object")
    return payload


def _route_for_terms(routes: list[Any], required_terms: tuple[str, ...]) -> dict[str, Any] | None:
    for route in routes:
        if not isinstance(route, dict):
            continue
        terms = set(_text_list(route.get("terms")))
        if any(term in terms for term in required_terms):
            return route
    return None


def _district_knowledge_id(district: str) -> str:
    return f"changzhou_{district}_service"


def check_knowledge_map(payload: dict[str, Any], *, generated_at: str = "") -> dict[str, Any]:
    failed_conditions: list[str] = []
    city_mapping = payload.get(CITY_KNOWLEDGE_ID)
    city_dataset_ids: list[str] = []
    routes: list[Any] = []
    if not isinstance(city_mapping, dict):
        failed_conditions.append(f"knowledge_id_missing:{CITY_KNOWLEDGE_ID}")
    else:
        city_dataset_ids = _text_list(city_mapping.get("dataset_ids"))
        routes_raw = city_mapping.get("query_routes")
        routes = routes_raw if isinstance(routes_raw, list) else []
        if not city_dataset_ids:
            failed_conditions.append("city_dataset_ids_missing")
        if not routes:
            failed_conditions.append("query_routes_missing")

    missing_routes: list[str] = []
    incomplete_routes: list[dict[str, Any]] = []
    route_dataset_missing: list[str] = []
    route_mode_invalid: list[dict[str, str]] = []
    for district, required_terms in REQUIRED_DISTRICT_TERMS.items():
        route = _route_for_terms(routes, required_terms)
        if route is None:
            missing_routes.append(district)
            failed_conditions.append(f"route_missing:{district}")
            continue
        terms = set(_text_list(route.get("terms")))
        missing_terms = [term for term in required_terms if term not in terms]
        if missing_terms:
            incomplete_routes.append({"district": district, "missing_terms": missing_terms})
            for term in missing_terms:
                failed_conditions.append(f"route_terms_missing:{district}:{term}")
        if not _text_list(route.get("dataset_ids")):
            route_dataset_missing.append(district)
            failed_conditions.append(f"route_dataset_ids_missing:{district}")
        mode = _text(route.get("mode") or "prepend")
        if mode not in VALID_ROUTE_MODES:
            route_mode_invalid.append({"district": district, "mode": mode})
            failed_conditions.append(f"route_mode_invalid:{district}:{mode}")

    missing_knowledge_ids: list[str] = []
    empty_knowledge_ids: list[str] = []
    for district in REQUIRED_DISTRICT_TERMS:
        knowledge_id = _district_knowledge_id(district)
        dataset_ids = _text_list(payload.get(knowledge_id))
        if knowledge_id not in payload:
            missing_knowledge_ids.append(knowledge_id)
            failed_conditions.append(f"district_knowledge_id_missing:{knowledge_id}")
        elif not dataset_ids:
            empty_knowledge_ids.append(knowledge_id)
            failed_conditions.append(f"district_knowledge_dataset_ids_missing:{knowledge_id}")

    district_count = len(REQUIRED_DISTRICT_TERMS)
    return {
        "schema": SCHEMA,
        "generated_at": _text(generated_at) or _utc_now_text(),
        "summary": {
            "passed": not failed_conditions,
            "failed_conditions": failed_conditions,
            "city_dataset_count": len(city_dataset_ids),
            "route_count": len(routes),
            "district_routes_checked": district_count,
            "district_knowledge_ids_checked": district_count,
        },
        "city": {
            "knowledge_id": CITY_KNOWLEDGE_ID,
            "dataset_count": len(city_dataset_ids),
        },
        "district_routes": {
            "required": list(REQUIRED_DISTRICT_TERMS),
            "missing": missing_routes,
            "incomplete": incomplete_routes,
            "dataset_ids_missing": route_dataset_missing,
            "invalid_modes": route_mode_invalid,
        },
        "district_knowledge_ids": {
            "required": [_district_knowledge_id(district) for district in REQUIRED_DISTRICT_TERMS],
            "missing": missing_knowledge_ids,
            "dataset_ids_missing": empty_knowledge_ids,
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Changzhou Dify external-knowledge map routes.")
    parser.add_argument("--knowledge-map-json", default="", help="Explicit knowledge-map JSON; overrides env lookup.")
    parser.add_argument("--env-file", default=".env", help="Env file containing DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON.")
    parser.add_argument("--out", default="", help="Optional JSON report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        payload = load_knowledge_map(knowledge_map_json=str(args.knowledge_map_json), env_file=str(args.env_file))
        report = check_knowledge_map(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": _utc_now_text(),
            "summary": {
                "passed": False,
                "failed_conditions": [f"config_error:{type(exc).__name__}"],
                "city_dataset_count": 0,
                "route_count": 0,
                "district_routes_checked": len(REQUIRED_DISTRICT_TERMS),
                "district_knowledge_ids_checked": len(REQUIRED_DISTRICT_TERMS),
            },
            "error": _text(exc),
        }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if _text(args.out):
        Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if bool((report.get("summary") or {}).get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
