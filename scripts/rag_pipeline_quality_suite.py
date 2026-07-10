#!/usr/bin/env python3
"""Run or print the repeatable RAG pipeline quality/performance gate suite."""


import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Phase:
    name: str
    purpose: str
    command: list[str]
    required: bool = True
    skip_reason: str = ""


def _api_v1_url(base_url: str) -> str:
    base = str(base_url or "").rstrip("/")
    return base if base.endswith("/api/v1") else f"{base}/api/v1"


def _append_out_arg(command: list[str], out_path: Path) -> list[str]:
    return [*command, "--out", str(out_path)]


def _profile_counts(profile: str) -> dict[str, int]:
    if profile == "server":
        return {
            "ingest_count": 20,
            "ingest_concurrency": 4,
            "retrieve_requests": 80,
            "retrieve_concurrency": 16,
            "chat_requests": 20,
            "chat_concurrency": 5,
        }
    if profile == "full":
        return {
            "ingest_count": 100,
            "ingest_concurrency": 8,
            "retrieve_requests": 300,
            "retrieve_concurrency": 32,
            "chat_requests": 60,
            "chat_concurrency": 8,
        }
    return {
        "ingest_count": 3,
        "ingest_concurrency": 1,
        "retrieve_requests": 12,
        "retrieve_concurrency": 4,
        "chat_requests": 4,
        "chat_concurrency": 2,
    }


def build_phases(args: argparse.Namespace) -> list[Phase]:
    py = str(args.python)
    out_dir = Path(args.output_dir)
    base_url = str(args.base_url).rstrip("/")
    api_v1 = _api_v1_url(base_url)
    tenant_id = str(args.tenant_id)
    user_id = str(args.user_id)
    counts = _profile_counts(str(args.profile))

    phases: list[Phase] = [
        Phase(
            name="api_smoke",
            purpose="后端健康、核心 API、鉴权与基础 RAG 路径冒烟",
            command=[
                py,
                "scripts/api_smoke.py",
                "--base-url",
                base_url,
                "--tenant-id",
                tenant_id,
                "--timeout",
                str(args.http_timeout),
                *(["--skip-llm-test"] if not args.include_llm_smoke else []),
            ],
        ),
        Phase(
            name="production_readiness_chain",
            purpose="多格式文档入库、治理、切块、KG、RAG、聊天引用的真实端到端链路",
            command=[
                py,
                "scripts/production_readiness_chain.py",
                "--base-url",
                base_url,
                "--tenant-id",
                tenant_id,
                "--user-id",
                user_id,
                "--timeout",
                str(args.http_timeout),
                "--processing-timeout",
                str(args.processing_timeout),
                "--llm-probe-timeout",
                str(args.llm_probe_timeout),
                "--output-dir",
                str(out_dir / "production-readiness"),
            ],
        ),
        Phase(
            name="chunking_strategy_matrix",
            purpose="全部内置切块策略在标准 fixture 上的可用性与异常回归",
            command=[py, "scripts/chunking_strategy_matrix.py"],
        ),
        Phase(
            name="rag_e2e_load_test",
            purpose="入库吞吐、检索 P95、聊天 P95 与错误率的轻量压力验证",
            command=[
                py,
                "scripts/rag_e2e_load_test.py",
                "--base-url",
                api_v1,
                "--tenant-id",
                tenant_id,
                "--user-id",
                user_id,
                "--file",
                str(args.load_fixture),
                "--parser-backend",
                str(args.parser_backend),
                "--ingest-count",
                str(counts["ingest_count"]),
                "--ingest-concurrency",
                str(counts["ingest_concurrency"]),
                "--retrieve-requests",
                str(counts["retrieve_requests"]),
                "--retrieve-concurrency",
                str(counts["retrieve_concurrency"]),
                "--chat-requests",
                str(counts["chat_requests"]),
                "--chat-concurrency",
                str(counts["chat_concurrency"]),
                "--timeout-sec",
                str(args.http_timeout),
                "--max-ingest-p95-ms",
                str(args.max_ingest_p95_ms),
                "--max-retrieve-p95-ms",
                str(args.max_retrieve_p95_ms),
                "--max-chat-p95-ms",
                str(args.max_chat_p95_ms),
                "--out",
                str(out_dir / "rag-e2e-load.json"),
            ],
        ),
    ]

    parser_fixture = Path(str(args.parser_fixture)) if str(args.parser_fixture or "").strip() else None
    parser_backends = str(args.parser_backends or "").strip()
    if parser_fixture and parser_backends:
        phases.append(
            Phase(
                name="live_parser_matrix",
                purpose="指定解析器后端的真实 PDF/文档预览冒烟",
                command=[
                    py,
                    "scripts/api_smoke.py",
                    "--base-url",
                    base_url,
                    "--tenant-id",
                    tenant_id,
                    "--timeout",
                    str(args.http_timeout),
                    "--skip-llm-test",
                    "--live-parser-backends",
                    parser_backends,
                    "--live-parser-fixture",
                    str(parser_fixture),
                    "--live-parser-timeout",
                    str(args.parser_timeout),
                ],
            )
        )
    else:
        phases.append(
            Phase(
                name="live_parser_matrix",
                purpose="指定解析器后端的真实 PDF/文档预览冒烟",
                command=[],
                required=False,
                skip_reason="未提供 --parser-fixture 或 --parser-backends，跳过解析器矩阵",
            )
        )

    kg_cases = Path(str(args.kg_cases)) if str(args.kg_cases or "").strip() else None
    kg_thresholds = Path(str(args.kg_thresholds)) if str(args.kg_thresholds or "").strip() else None
    if kg_cases and kg_thresholds:
        phases.append(
            Phase(
                name="kg_regression_gate",
                purpose="KG 召回 Hit/MRR/Recall 阈值回归",
                command=[
                    py,
                    "scripts/kg_search_regression_gate.py",
                    "--base-url",
                    api_v1,
                    "--tenant-id",
                    tenant_id,
                    "--user-id",
                    user_id,
                    "--cases",
                    str(kg_cases),
                    "--thresholds",
                    str(kg_thresholds),
                    "--out-run-json",
                    str(out_dir / "kg-regression-run.json"),
                ],
            )
        )
    else:
        phases.append(
            Phase(
                name="kg_regression_gate",
                purpose="KG 召回 Hit/MRR/Recall 阈值回归",
                command=[],
                required=False,
                skip_reason="未提供 --kg-cases 与 --kg-thresholds，跳过 KG 阈值门禁",
            )
        )

    answer_input = Path(str(args.answer_input)) if str(args.answer_input or "").strip() else None
    answer_thresholds = Path(str(args.answer_thresholds)) if str(args.answer_thresholds or "").strip() else None
    if answer_input and answer_thresholds:
        phases.append(
            Phase(
                name="answer_quality_gate",
                purpose="答案质量指标阈值门禁",
                command=_append_out_arg(
                    [
                        py,
                        "scripts/answer_quality_gate.py",
                        "--input",
                        str(answer_input),
                        "--thresholds",
                        str(answer_thresholds),
                    ],
                    out_dir / "answer-quality-gate.json",
                ),
            )
        )
    else:
        phases.append(
            Phase(
                name="answer_quality_gate",
                purpose="答案质量指标阈值门禁",
                command=[],
                required=False,
                skip_reason="未提供 --answer-input 与 --answer-thresholds，跳过答案质量门禁",
            )
        )

    deepdoc_dataset_id = str(args.deepdoc_dataset_id or "").strip()
    deepdoc_cases = Path(str(args.deepdoc_cases)) if str(args.deepdoc_cases or "").strip() else None
    if deepdoc_dataset_id and deepdoc_cases:
        phases.append(
            Phase(
                name="deepdoc_quality_gate",
                purpose="DeepDoc 大文件 QA、检索、KG 与延迟矩阵门禁",
                command=[
                    py,
                    "scripts/deepdoc_quality_gate.py",
                    "--base-url",
                    api_v1,
                    "--tenant-id",
                    tenant_id,
                    "--user-id",
                    user_id,
                    "--dataset-id",
                    deepdoc_dataset_id,
                    "--cases",
                    str(deepdoc_cases),
                    "--modes",
                    str(args.deepdoc_modes),
                    "--concurrency",
                    str(args.deepdoc_concurrency),
                    "--out",
                    str(out_dir / "deepdoc-quality-gate.json"),
                    *(["--thresholds", str(args.deepdoc_thresholds)] if str(args.deepdoc_thresholds or "").strip() else []),
                ],
            )
        )
    else:
        phases.append(
            Phase(
                name="deepdoc_quality_gate",
                purpose="DeepDoc 大文件 QA、检索、KG 与延迟矩阵门禁",
                command=[],
                required=False,
                skip_reason="未提供 --deepdoc-dataset-id 与 --deepdoc-cases，跳过 DeepDoc 质量矩阵",
            )
        )

    skipped = {item.strip() for item in str(args.skip or "").split(",") if item.strip()}
    if not skipped:
        return phases
    return [
        Phase(
            name=phase.name,
            purpose=phase.purpose,
            command=[] if phase.name in skipped else phase.command,
            required=False if phase.name in skipped else phase.required,
            skip_reason=f"用户通过 --skip 跳过 {phase.name}" if phase.name in skipped else phase.skip_reason,
        )
        for phase in phases
    ]


def _phase_to_dict(phase: Phase) -> dict[str, Any]:
    return {
        "name": phase.name,
        "purpose": phase.purpose,
        "required": phase.required,
        "command": phase.command,
        "skip_reason": phase.skip_reason,
    }


def run_phases(phases: list[Phase], *, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    overall_rc = 0
    for phase in phases:
        if not phase.command:
            results.append({**_phase_to_dict(phase), "status": "skipped", "returncode": 0})
            continue

        started = time.perf_counter()
        proc = subprocess.run(phase.command, cwd=REPO_ROOT, text=True)  # noqa: S603
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        status = "passed" if proc.returncode == 0 else "failed"
        results.append(
            {
                **_phase_to_dict(phase),
                "status": status,
                "returncode": proc.returncode,
                "elapsed_ms": elapsed_ms,
            }
        )
        if proc.returncode != 0 and phase.required:
            overall_rc = proc.returncode or 1
            break

    report = {
        "schema": "mimirq.rag_pipeline_quality_suite.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "passed": overall_rc == 0,
        "results": results,
    }
    report_path = out_dir / "suite-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[rag-pipeline-quality-suite] wrote {report_path}")
    return overall_rc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Actually run phases. Without this flag the suite prints JSON only.")
    parser.add_argument("--profile", choices=["smoke", "server", "full"], default="smoke")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default="00000000-0000-0000-0000-000000000000")
    parser.add_argument("--user-id", default="pipeline-quality-suite")
    parser.add_argument("--output-dir", default="artifacts/rag-pipeline-quality-suite")
    parser.add_argument("--http-timeout", type=float, default=180.0)
    parser.add_argument("--processing-timeout", type=float, default=1800.0)
    parser.add_argument("--llm-probe-timeout", type=float, default=15.0)
    parser.add_argument("--max-ingest-p95-ms", type=int, default=0)
    parser.add_argument("--max-retrieve-p95-ms", type=int, default=0)
    parser.add_argument("--max-chat-p95-ms", type=int, default=0)
    parser.add_argument("--include-llm-smoke", action="store_true")
    parser.add_argument("--load-fixture", default=str(REPO_ROOT / "README.md"))
    parser.add_argument("--parser-backend", default="auto")
    parser.add_argument("--parser-fixture", default="")
    parser.add_argument("--parser-backends", default="")
    parser.add_argument("--parser-timeout", type=float, default=300.0)
    parser.add_argument("--kg-cases", default="")
    parser.add_argument("--kg-thresholds", default="")
    parser.add_argument("--answer-input", default="")
    parser.add_argument("--answer-thresholds", default="")
    parser.add_argument("--deepdoc-dataset-id", default="")
    parser.add_argument("--deepdoc-cases", default="")
    parser.add_argument("--deepdoc-modes", default="retrieve,chat,kg")
    parser.add_argument("--deepdoc-thresholds", default="")
    parser.add_argument("--deepdoc-concurrency", type=int, default=4)
    parser.add_argument("--skip", default="", help="Comma-separated phase names to skip.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    phases = build_phases(args)
    if not args.run:
        print(json.dumps({"schema": "mimirq.rag_pipeline_quality_suite.plan.v1", "phases": [_phase_to_dict(p) for p in phases]}, ensure_ascii=False, indent=2))
        return 0
    return run_phases(phases, out_dir=Path(str(args.output_dir)))


if __name__ == "__main__":
    raise SystemExit(main())
