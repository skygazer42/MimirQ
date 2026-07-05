#!/usr/bin/env python3
"""Push 50 varied Dify-result trace records through the local trace reader."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.api.v1 import integrations_dify as dify_api
    from app.core.config import settings
    from app.services.rag_trace_service import list_rag_traces

    metrics_path = Path("/tmp/mimirq_dify_result_trace_50.jsonl")
    metrics_path.unlink(missing_ok=True)
    settings.ENABLE_METRICS_LOG = True
    settings.METRICS_LOG_PATH = str(metrics_path)

    tenant_id = uuid4()
    conversation_ids = [uuid4() for _ in range(5)]
    captured: list[dict] = []
    original_log_metrics = dify_api.log_metrics
    dify_api.log_metrics = captured.append
    topics = [
        ("普通话考试", "需要身份证、准考证，按测试站通知时间到场。"),
        ("保健食品广告审查", "按省级事项办理，提交广告样稿和产品证明材料。"),
        ("社保卡补办", "可到区政务服务中心或线上渠道按提示办理。"),
        ("营业执照变更", "准备变更登记申请书、章程修正案和经办人材料。"),
        ("公积金提取", "按提取类型准备身份证、银行卡和对应证明。"),
        ("护士执业注册", "提交资格证、健康证明、拟聘机构材料。"),
        ("食品经营许可", "按经营项目提交场所、制度和人员材料。"),
        ("道路运输证", "按车辆和经营范围提交车辆证照材料。"),
        ("出生医学证明", "按医院和属地要求提交父母证件。"),
        ("不动产登记", "提交权属来源、身份证明和税费材料。"),
    ]

    for idx in range(50):
        topic, answer_tail = topics[idx % len(topics)]
        citations = [
            {
                "document_id": f"doc-{idx:02d}-{j}",
                "chunk_id": f"chunk-{idx:02d}-{j}",
                "chunk_index": idx * 10 + j,
                "retrieval_score": round(0.55 + random.random() * 0.4, 4),
                "retrieval_mode": "dify_result",
            }
            for j in range(1 + (idx % 3))
        ]
        dify_api._log_dify_result_rag_trace(
            tenant_id=tenant_id,
            conversation_id=conversation_ids[idx % len(conversation_ids)],
            request_id=f"trace-50-{idx + 1:03d}",
            question=f"用户想咨询{topic}，顺便问办理材料和时间。",
            answer=f"{topic}第{idx + 1}条模拟答复：{answer_tail}",
            source_conversation_id=f"dify-conv-{idx % 5:02d}",
            source_message_id=f"dify-msg-{idx + 1:03d}",
            source_run_id=f"dify-run-{idx // 5:02d}",
            citations=citations,
        )

    dify_api.log_metrics = original_log_metrics
    metrics_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in captured) + "\n",
        encoding="utf-8",
    )
    records = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    raw_answer_leaks = sum("模拟答复" in json.dumps(row, ensure_ascii=False) for row in records)
    print(f"metrics_lines={len(records)}")
    print(f"raw_answer_leaks={raw_answer_leaks}")
    print(f"sources={sorted({row.get('source') for row in records})}")

    returned_total = 0
    for conversation_id in conversation_ids:
        traces = list_rag_traces(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            limit=20,
            window_minutes=60,
            max_bytes=5_000_000,
        )
        result_steps = [
            item.steps[-1]
            for item in traces.items
            if item.steps and item.steps[-1].key == "dify_result"
        ]
        returned_total += traces.returned
        sample = result_steps[0] if result_steps else None
        print(
            "conversation="
            f"{conversation_id} returned={traces.returned} "
            f"dify_result_steps={len(result_steps)} "
            f"sample_message={sample.meta.get('source_message_id') if sample else None} "
            f"sample_answer_chars={sample.meta.get('answer_chars') if sample else None}"
        )

    print(f"returned_total={returned_total}")
    assert len(records) == 50
    assert raw_answer_leaks == 0
    assert returned_total == 50
    assert all(row.get("source") == "dify_result" for row in records)
    assert all((row.get("dify_result") or {}).get("status") == "completed" for row in records)
    assert all("answer_hash" in (row.get("dify_result") or {}) for row in records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
