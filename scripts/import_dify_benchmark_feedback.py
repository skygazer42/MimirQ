#!/usr/bin/env python3
"""Import Dify benchmark audit rows into the feedback triage board.

The feedback board is message-backed, so this script creates a tiny synthetic
conversation per selected benchmark row: user question, assistant answer, and
one feedback record on the assistant message.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid5

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_AUDIT_JSONL = Path("/tmp/dify_http_full800_case_title_fix_20260705/audit_review.jsonl")
DEFAULT_SYSTEM = "dify_http_mimirq"
DEFAULT_ACCOUNT_ID = "system:benchmark"
DEFAULT_LIMIT = 60
DEFAULT_PER_BUCKET = 15
DEFAULT_BATCH_ID = "dify-http-full800-20260705"
IMPORT_NAMESPACE = UUID("66a3fda6-9b9b-4df9-81c8-971729bb8e2d")
QUALITY_BUCKET_ORDER = ("missed_context", "bad_answer", "no_answer", "partial", "good")


@dataclass(frozen=True)
class AuditRowQuality:
    bucket: str
    rating: int
    issue: str
    tag: str


@dataclass(frozen=True)
class FeedbackPayload:
    rating: int
    reason: str
    tags: list[str]
    expected_answer: str | None
    extra: dict[str, Any]
    message_metadata: dict[str, Any]
    citations: list[dict[str, Any]]


@dataclass(frozen=True)
class FeedbackRowPayload:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    message_id: UUID
    account_id: str
    rating: int
    reason: str
    tags: list[str]
    expected_answer: str | None
    extra: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class FeedbackImportRecord:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    tenant_id: UUID
    account_id: str
    conversation_title: str
    user_message_content: str
    assistant_message_content: str
    assistant_citations: list[dict[str, Any]]
    assistant_metadata: dict[str, Any]
    feedback: FeedbackRowPayload
    created_at: datetime
    user_created_at: datetime
    assistant_created_at: datetime


def _text(value: Any, *, max_len: int | None = None) -> str:
    text = str(value or "").strip()
    if max_len is not None and max_len >= 0:
        return text[:max_len]
    return text


def _number(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if numeric == numeric else default


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _case_id(row: dict[str, Any]) -> str:
    return _text(row.get("case_id") or row.get("id") or row.get("source_case_id"))


def _system(row: dict[str, Any]) -> str:
    return _text(row.get("system") or DEFAULT_SYSTEM)


def _import_key(row: dict[str, Any], *, batch_id: str) -> str:
    return f"{_text(batch_id) or DEFAULT_BATCH_ID}:{_system(row)}:{_case_id(row)}"


def _stable_uuid(*parts: Any) -> UUID:
    return uuid5(IMPORT_NAMESPACE, ":".join(_text(part) for part in parts))


def _unique_strings(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def classify_audit_row(row: dict[str, Any]) -> AuditRowQuality:
    verdict = _text(row.get("verdict"))
    answer = _text(row.get("answer_preview"))
    business_score = _number(row.get("business_score"))
    evidence_coverage = _number(row.get("evidence_coverage"))
    clause_coverage = _number(row.get("answer_clause_coverage"), 1.0)
    subquestion_coverage = _number(row.get("answer_subquestion_coverage"), 1.0)
    wrong_evidence_rate = _number(row.get("wrong_evidence_rate"))
    missing_evidence = _list(row.get("missing_evidence_clause_ids"))

    if not answer or "无答案" in verdict:
        return AuditRowQuality(
            bucket="no_answer",
            rating=1,
            issue="无答案",
            tag="quality:no_answer",
        )
    if "证据不足" in verdict or "未命中" in verdict or evidence_coverage < 0.6 or missing_evidence:
        return AuditRowQuality(
            bucket="missed_context",
            rating=1,
            issue="未命中知识库",
            tag="quality:missed_context",
        )
    if (
        business_score < 0.65
        or clause_coverage < 0.6
        or subquestion_coverage < 0.5
        or wrong_evidence_rate >= 0.35
    ):
        return AuditRowQuality(
            bucket="bad_answer",
            rating=2,
            issue="回答质量差",
            tag="quality:bad_answer",
        )
    if verdict == "准确" and business_score >= 0.85 and evidence_coverage >= 0.85 and wrong_evidence_rate <= 0.2:
        return AuditRowQuality(
            bucket="good",
            rating=5,
            issue="回答良好",
            tag="quality:good",
        )
    return AuditRowQuality(
        bucket="partial",
        rating=3,
        issue="部分准确",
        tag="quality:partial",
    )


def _score_line(row: dict[str, Any]) -> str:
    return (
        f"业务分 {_number(row.get('business_score')):.3f}"
        f"；证据覆盖 {_number(row.get('evidence_coverage')):.3f}"
        f"；错证率 {_number(row.get('wrong_evidence_rate')):.3f}"
    )


def _reason_from_row(row: dict[str, Any], quality: AuditRowQuality) -> str:
    verdict = _text(row.get("verdict")) or quality.issue
    parts = [f"评测样本：{verdict}", _score_line(row), f"归因：{quality.issue}"]
    missing_evidence = [_text(item) for item in _list(row.get("missing_evidence_clause_ids")) if _text(item)]
    missing_subquestions = [_text(item) for item in _list(row.get("missing_subquestion_ids")) if _text(item)]
    if missing_evidence:
        parts.append("缺失证据：" + "、".join(missing_evidence[:8]))
    if missing_subquestions:
        parts.append("漏答子问题：" + "、".join(missing_subquestions[:8]))
    score_reason = _text(row.get("score_reason"), max_len=600)
    if score_reason:
        parts.append(score_reason)
    return "；".join(parts)[:1800]


def _benchmark_citations(
    row: dict[str, Any],
    *,
    import_key: str,
    source_title: str,
    source_file: str,
    top_record_preview: str,
) -> list[dict[str, Any]]:
    snippet = top_record_preview or _text(row.get("native_evidence_preview"), max_len=2000)
    if not snippet:
        return []

    document_name = source_title or Path(source_file).name or _case_id(row) or "Benchmark document"
    document_id = _stable_uuid("benchmark-document", import_key, document_name, source_file or "no-file")
    chunk_id = _stable_uuid("benchmark-chunk", import_key, snippet)
    return [
        {
            "document_id": str(document_id),
            "document_name": document_name,
            "chunk_id": str(chunk_id),
            "chunk_content": snippet,
            "relevance_score": max(0.0, min(1.0, _number(row.get("evidence_coverage"), 1.0))),
            "retrieval_mode": "benchmark",
            "source_file": source_file,
            "label": document_name,
        }
    ]


def build_feedback_payload(row: dict[str, Any], *, batch_id: str = DEFAULT_BATCH_ID) -> FeedbackPayload:
    quality = classify_audit_row(row)
    case_id = _case_id(row)
    system = _system(row)
    import_key = _import_key(row, batch_id=batch_id)
    expected_answer = _text(row.get("expected_answer_basis"), max_len=4000) or None
    source_file = _text(row.get("source_file"), max_len=512)
    top_record_preview = _text(row.get("top_record_preview"), max_len=2000)
    source_title = _text(row.get("source_record_title"), max_len=200)
    source_section = _text(row.get("source_section"), max_len=120)
    verdict = _text(row.get("verdict"))

    tags = _unique_strings(
        [
            "benchmark:800",
            "benchmark:dify_3way",
            f"system:{system}",
            quality.tag,
            f"quality_bucket:{quality.bucket}",
            f"verdict:{verdict}" if verdict else "",
            f"case:{_text(row.get('case_type'))}" if _text(row.get("case_type")) else "",
            f"knowledge:{_text(row.get('knowledge_id'))}" if _text(row.get("knowledge_id")) else "",
            f"section:{source_section}" if source_section else "",
        ]
    )

    extra = {
        "source": "benchmark",
        "benchmark_source": "dify_3way",
        "benchmark_batch_id": batch_id,
        "benchmark_case_id": case_id,
        "benchmark_import_key": import_key,
        "system": system,
        "verdict": verdict,
        "feedback_issue": quality.issue,
        "quality_bucket": quality.bucket,
        "business_score": _number(row.get("business_score")),
        "answer_clause_coverage": _number(row.get("answer_clause_coverage")),
        "answer_subquestion_coverage": _number(row.get("answer_subquestion_coverage")),
        "evidence_coverage": _number(row.get("evidence_coverage")),
        "wrong_evidence_rate": _number(row.get("wrong_evidence_rate")),
        "missing_evidence_clause_ids": _list(row.get("missing_evidence_clause_ids")),
        "missing_subquestion_ids": _list(row.get("missing_subquestion_ids")),
        "knowledge_id": _text(row.get("knowledge_id")),
        "case_type": _text(row.get("case_type")),
        "query": _text(row.get("query"), max_len=2000),
        "source_file": source_file,
        "source_section": source_section,
        "source_record_title": source_title,
        "top_record_preview": top_record_preview,
        "archived": False,
    }

    message_metadata = {
        "source": "benchmark",
        "benchmark_source": "dify_3way",
        "benchmark_feedback_import_key": import_key,
        "benchmark_case_id": case_id,
        "system": system,
        "verdict": verdict,
        "quality_bucket": quality.bucket,
        "request_id": f"benchmark:{import_key}",
    }

    citations = _benchmark_citations(
        row,
        import_key=import_key,
        source_title=source_title,
        source_file=source_file,
        top_record_preview=top_record_preview,
    )

    return FeedbackPayload(
        rating=quality.rating,
        reason=_reason_from_row(row, quality),
        tags=tags,
        expected_answer=expected_answer,
        extra=extra,
        message_metadata=message_metadata,
        citations=citations,
    )


def _conversation_title(row: dict[str, Any], quality: AuditRowQuality) -> str:
    title = _text(row.get("source_record_title"), max_len=80) or _text(row.get("query"), max_len=80) or _case_id(row)
    return f"评测样本 · {quality.issue} · {title}"[:500]


def build_import_record(
    row: dict[str, Any],
    *,
    tenant_id: UUID,
    account_id: str = DEFAULT_ACCOUNT_ID,
    batch_id: str = DEFAULT_BATCH_ID,
    imported_by: str = DEFAULT_ACCOUNT_ID,
    position: int = 0,
    imported_at: datetime | None = None,
) -> FeedbackImportRecord:
    payload = build_feedback_payload(row, batch_id=batch_id)
    quality = classify_audit_row(row)
    import_key = payload.extra["benchmark_import_key"]
    conversation_id = _stable_uuid("conversation", tenant_id, account_id, import_key)
    user_message_id = _stable_uuid("message", "user", tenant_id, account_id, import_key)
    assistant_message_id = _stable_uuid("message", "assistant", tenant_id, account_id, import_key)
    feedback_id = _stable_uuid("feedback", tenant_id, account_id, import_key)
    base_time = imported_at or datetime.now(timezone.utc)
    user_created_at = base_time + timedelta(seconds=position * 3)
    assistant_created_at = user_created_at + timedelta(seconds=1)
    feedback_updated_at = assistant_created_at + timedelta(seconds=1)
    user_content = _text(row.get("query"), max_len=4000) or f"评测问题 {import_key}"
    assistant_content = _text(row.get("answer_preview"), max_len=8000) or "（评测记录中没有模型回答）"
    extra = dict(payload.extra)
    extra["imported_by"] = imported_by
    extra["imported_at"] = feedback_updated_at.isoformat()

    return FeedbackImportRecord(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_title=_conversation_title(row, quality),
        user_message_content=user_content,
        assistant_message_content=assistant_content,
        assistant_citations=payload.citations,
        assistant_metadata=payload.message_metadata,
        feedback=FeedbackRowPayload(
            id=feedback_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            account_id=account_id,
            rating=payload.rating,
            reason=payload.reason,
            tags=payload.tags,
            expected_answer=payload.expected_answer,
            extra=extra,
            created_at=feedback_updated_at,
            updated_at=feedback_updated_at,
        ),
        created_at=user_created_at,
        user_created_at=user_created_at,
        assistant_created_at=assistant_created_at,
    )


def load_audit_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
            if isinstance(value, dict):
                rows.append(value)
    return rows


def select_balanced_audit_rows(
    rows: list[dict[str, Any]],
    *,
    per_bucket: int = DEFAULT_PER_BUCKET,
    limit: int = DEFAULT_LIMIT,
    seed: int = 42,
) -> list[dict[str, Any]]:
    if per_bucket <= 0:
        selected = list(rows)
        random.Random(seed).shuffle(selected)
        return selected[: max(0, limit)] if limit > 0 else selected

    grouped: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in QUALITY_BUCKET_ORDER}
    for row in rows:
        grouped.setdefault(classify_audit_row(row).bucket, []).append(row)

    rng = random.Random(seed)
    capped: dict[str, list[dict[str, Any]]] = {}
    for bucket, bucket_rows in grouped.items():
        shuffled = list(bucket_rows)
        rng.shuffle(shuffled)
        capped[bucket] = shuffled[:per_bucket]

    selected: list[dict[str, Any]] = []
    while any(capped.values()):
        for bucket in QUALITY_BUCKET_ORDER:
            bucket_rows = capped.get(bucket) or []
            if not bucket_rows:
                continue
            selected.append(bucket_rows.pop(0))
            if limit > 0 and len(selected) >= limit:
                return selected
    return selected


def _upsert_feedback_records(records: list[FeedbackImportRecord]) -> dict[str, Any]:
    from app.core.database import SessionLocal
    from app.models.chat import Conversation, Message
    from app.models.feedback import MessageFeedback

    created_feedback = 0
    updated_feedback = 0
    db = SessionLocal()
    try:
        for record in records:
            conversation = (
                db.query(Conversation)
                .filter(Conversation.id == record.conversation_id, Conversation.tenant_id == record.tenant_id)
                .first()
            )
            if conversation is None:
                conversation = Conversation(
                    id=record.conversation_id,
                    tenant_id=record.tenant_id,
                    title=record.conversation_title,
                    title_source="manual",
                    document_ids=[],
                    message_count=2,
                    created_at=record.created_at,
                    updated_at=record.feedback.updated_at,
                )
                db.add(conversation)
            else:
                conversation.title = record.conversation_title
                conversation.title_source = "manual"
                conversation.message_count = 2
                conversation.updated_at = record.feedback.updated_at

            _upsert_message(
                db=db,
                model=Message,
                message_id=record.user_message_id,
                tenant_id=record.tenant_id,
                conversation_id=record.conversation_id,
                role="user",
                content=record.user_message_content,
                citations=[],
                metadata={
                    "source": "benchmark",
                    "benchmark_feedback_import_key": record.assistant_metadata.get("benchmark_feedback_import_key"),
                    "benchmark_role": "user_question",
                },
                created_at=record.user_created_at,
            )
            _upsert_message(
                db=db,
                model=Message,
                message_id=record.assistant_message_id,
                tenant_id=record.tenant_id,
                conversation_id=record.conversation_id,
                role="assistant",
                content=record.assistant_message_content,
                citations=record.assistant_citations,
                metadata=record.assistant_metadata,
                created_at=record.assistant_created_at,
            )
            db.flush()

            feedback = (
                db.query(MessageFeedback)
                .filter(
                    MessageFeedback.tenant_id == record.tenant_id,
                    MessageFeedback.message_id == record.assistant_message_id,
                    MessageFeedback.account_id == record.account_id,
                )
                .first()
            )
            if feedback is None:
                feedback = MessageFeedback(
                    id=record.feedback.id,
                    tenant_id=record.feedback.tenant_id,
                    conversation_id=record.feedback.conversation_id,
                    message_id=record.feedback.message_id,
                    account_id=record.feedback.account_id,
                    rating=record.feedback.rating,
                    reason=record.feedback.reason,
                    tags=record.feedback.tags,
                    expected_answer=record.feedback.expected_answer,
                    extra=record.feedback.extra,
                    created_at=record.feedback.created_at,
                    updated_at=record.feedback.updated_at,
                )
                db.add(feedback)
                created_feedback += 1
            else:
                feedback.rating = record.feedback.rating
                feedback.reason = record.feedback.reason
                feedback.tags = record.feedback.tags
                feedback.expected_answer = record.feedback.expected_answer
                feedback.extra = record.feedback.extra
                feedback.updated_at = record.feedback.updated_at
                updated_feedback += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {
        "created_feedback": created_feedback,
        "updated_feedback": updated_feedback,
        "total_records": len(records),
    }


def _upsert_message(
    *,
    db: Any,
    model: Any,
    message_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    role: str,
    content: str,
    citations: list[dict[str, Any]],
    metadata: dict[str, Any],
    created_at: datetime,
) -> None:
    row = db.query(model).filter(model.id == message_id, model.tenant_id == tenant_id).first()
    if row is None:
        db.add(
            model(
                id=message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                citations=citations,
                token_count=None,
                message_metadata=metadata,
                created_at=created_at,
            )
        )
        return
    row.conversation_id = conversation_id
    row.role = role
    row.content = content
    row.citations = citations
    row.message_metadata = metadata
    row.created_at = created_at


def _bucket_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        bucket = classify_audit_row(row).bucket
        counts[bucket] = counts.get(bucket, 0) + 1
    return {key: counts[key] for key in QUALITY_BUCKET_ORDER if counts.get(key)}


def _resolve_tenant_id(raw: str | None) -> UUID:
    if raw:
        return UUID(raw)
    from app.core.config import settings

    return UUID(str(settings.DEFAULT_TENANT_ID))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-jsonl", type=Path, default=DEFAULT_AUDIT_JSONL)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("--imported-by", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("--system", default=DEFAULT_SYSTEM)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--per-bucket", type=int, default=DEFAULT_PER_BUCKET)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    rows = load_audit_rows(args.audit_jsonl)
    if args.system:
        rows = [row for row in rows if _system(row) == args.system]
    selected = select_balanced_audit_rows(
        rows,
        per_bucket=args.per_bucket,
        limit=args.limit,
        seed=args.seed,
    )
    tenant_id = _resolve_tenant_id(args.tenant_id)
    imported_at = datetime.now(timezone.utc)
    records = [
        build_import_record(
            row,
            tenant_id=tenant_id,
            account_id=args.account_id,
            batch_id=args.batch_id,
            imported_by=args.imported_by,
            position=index,
            imported_at=imported_at,
        )
        for index, row in enumerate(selected)
    ]
    summary = {
        "audit_jsonl": str(args.audit_jsonl),
        "system": args.system,
        "tenant_id": str(tenant_id),
        "account_id": args.account_id,
        "batch_id": args.batch_id,
        "available_rows": len(rows),
        "selected_rows": len(selected),
        "available_buckets": _bucket_counts(rows),
        "selected_buckets": _bucket_counts(selected),
        "sample_feedback_ids": [str(record.feedback.id) for record in records[:5]],
        "dry_run": bool(args.dry_run),
    }
    if not args.dry_run:
        summary.update(_upsert_feedback_records(records))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
