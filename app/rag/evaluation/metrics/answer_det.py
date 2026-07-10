
import math
import re
from typing import Any

_REFUSAL_RE = re.compile(r"(无法|没有相关|未找到|不能确认|无法确认|无相关资料|not enough|cannot answer)", flags=re.IGNORECASE)


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").strip().split()).casefold()


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text) if token]


def evaluate_answer_deterministic(
    *,
    question: str,
    answer: str,
    gold_answer: str,
    is_unanswerable: bool,
) -> dict[str, Any]:
    norm_answer = _normalize(answer)
    norm_gold = _normalize(gold_answer)
    answer_em = 1.0 if (not is_unanswerable and norm_answer == norm_gold and norm_gold) else 0.0

    answer_tokens = _tokenize(norm_answer)
    gold_tokens = _tokenize(norm_gold)
    if answer_tokens and gold_tokens:
        overlap = len(set(answer_tokens) & set(gold_tokens))
        precision = overlap / len(set(answer_tokens))
        recall = overlap / len(set(gold_tokens))
        answer_f1 = 0.0 if precision + recall == 0 else round(2 * precision * recall / (precision + recall), 4)
    else:
        answer_f1 = float(answer_em)

    refusal = bool(_REFUSAL_RE.search(norm_answer))
    refusal_correct = refusal if is_unanswerable else None
    zero_f1 = math.isclose(answer_f1, 0.0, abs_tol=1e-12)
    obvious_hallucination = bool(not is_unanswerable and norm_gold and norm_answer and norm_answer != norm_gold and zero_f1)

    return {
        "question": str(question or ""),
        "answer_em": float(answer_em),
        "answer_f1": float(answer_f1),
        "refusal_correct": refusal_correct,
        "obvious_hallucination": obvious_hallucination,
    }
