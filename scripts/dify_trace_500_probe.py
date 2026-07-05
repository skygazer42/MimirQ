from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_API_URL = "http://127.0.0.1:18080/api/v1/integrations/dify/retrieval"
DEFAULT_KNOWLEDGE_ID = "demo_knowledge"
DEFAULT_RUN_ID = "codex-dify-trace-500"


@dataclass(frozen=True)
class ProbeQuestion:
    index: int
    conversation_index: int
    turn_index: int
    topic: str
    style: str
    query: str

    @property
    def request_id(self) -> str:
        return f"{DEFAULT_RUN_ID}-req-{self.index:03d}"

    @property
    def dify_conversation_id(self) -> str:
        return f"{DEFAULT_RUN_ID}-conv-{self.conversation_index:02d}"

    @property
    def dify_message_id(self) -> str:
        return f"{DEFAULT_RUN_ID}-msg-{self.index:03d}"

    @property
    def dify_workflow_run_id(self) -> str:
        return f"{DEFAULT_RUN_ID}-workflow"


TOPIC_POOLS: list[dict[str, Any]] = [
    {
        "topic": "保健食品广告审查",
        "aliases": ["保健品广告", "保健食品宣传", "蓝帽子产品广告", "功能食品广告", "保健食品广告审查"],
        "people": ["新开的门店", "公司市场部", "电商店铺", "药店", "社区团购商家"],
        "intents": ["归谁办", "多久能办好", "算什么类型", "能不能网上办", "需要哪些材料", "要不要先审"],
    },
    {
        "topic": "身份证补办进度",
        "aliases": ["身份证补办", "身份证进度", "居民证件", "补身份证", "证件办理"],
        "people": ["我爸", "孩子", "外地户口家人", "老人", "自己"],
        "intents": ["怎么查进度", "去哪查", "多久拿证", "要带什么", "能不能代办", "周末能办吗"],
    },
    {
        "topic": "社保卡居民服务",
        "aliases": ["社保卡", "市民卡", "三代社保卡", "社保卡挂失", "社保卡补办"],
        "people": ["家里老人", "刚来本地的人", "孩子", "单位员工", "自己"],
        "intents": ["丢了怎么办", "在哪里办", "多久能拿", "能不能线上办", "需要带照片吗", "怎么激活"],
    },
    {
        "topic": "开餐饮店",
        "aliases": ["开小饭店", "餐饮店开业", "奶茶店", "小吃店", "外卖店"],
        "people": ["朋友", "夫妻店", "个体户", "创业的人", "社区门面"],
        "intents": ["先办什么证", "需要哪些许可", "能不能一件事办", "流程怎么走", "大概要多久", "窗口在哪"],
    },
    {
        "topic": "汽车置换补贴",
        "aliases": ["换车补贴", "以旧换新", "汽车置换", "买新车补贴", "旧车换新车"],
        "people": ["家里", "同事", "我爸", "朋友", "自己"],
        "intents": ["怎么申请", "入口在哪", "材料有哪些", "多久到账", "有没有时间限制", "谁能申请"],
    },
    {
        "topic": "小学入学",
        "aliases": ["孩子上小学", "一年级报名", "义务教育入学", "小学招生", "新生报名"],
        "people": ["孩子", "外地户口小孩", "新买房家庭", "租房家庭", "转学家庭"],
        "intents": ["怎么报名", "需要哪些资料", "什么时候开始", "学区怎么查", "能不能线上办", "咨询哪里"],
    },
    {
        "topic": "公积金线上业务",
        "aliases": ["公积金", "住房公积金", "公积金公众号", "账户转移", "公积金提取"],
        "people": ["单位员工", "离职人员", "新入职员工", "买房的人", "自己"],
        "intents": ["线上怎么弄", "要不要去窗口", "需要什么材料", "多久到账", "账号怎么处理", "电话是多少"],
    },
    {
        "topic": "政务服务中心",
        "aliases": ["便民中心", "政务大厅", "服务中心", "办事大厅", "窗口"],
        "people": ["家附近", "东区这边", "北区这边", "西区附近", "产业园区"],
        "intents": ["地址在哪", "电话多少", "几点上班", "周六开不开", "能不能预约", "停车方便吗"],
    },
    {
        "topic": "企业员工密码重置",
        "aliases": ["企业账号密码", "员工密码", "应急局账号", "系统登录不上", "密码输错"],
        "people": ["企业安全员", "单位经办人", "新员工", "老账号", "同事"],
        "intents": ["怎么重置", "找谁处理", "要不要提交材料", "多久恢复", "能不能电话办", "有没有线上入口"],
    },
    {
        "topic": "普通话测试",
        "aliases": ["普通话考试", "普通话报名", "普通话成绩", "普通话证书", "测试计划"],
        "people": ["教师资格证考生", "学生", "上班族", "外地考生", "自己"],
        "intents": ["什么时候报名", "成绩怎么查", "证书怎么领", "在哪里考", "要带什么", "错过了怎么办"],
    },
    {
        "topic": "建设规划许可查询",
        "aliases": ["规划许可证", "建设规划", "楼盘规划", "规划公示", "商品房规划"],
        "people": ["小区业主", "买房的人", "开发商咨询", "附近居民", "自己"],
        "intents": ["哪里查", "有没有公示", "怎么核实", "需要登录吗", "能查到哪些信息", "咨询哪个部门"],
    },
    {
        "topic": "企业社会保险登记",
        "aliases": ["公司社保登记", "企业社保开户", "单位社保", "新公司参保", "员工社保登记"],
        "people": ["新办企业", "人事", "财务", "小微企业", "个体工商户"],
        "intents": ["在哪里办", "需要什么材料", "能不能网上办", "多久生效", "流程是什么", "窗口在哪"],
    },
    {
        "topic": "住宅专项维修资金",
        "aliases": ["维修基金", "房屋维修资金", "专项维修资金", "买房维修基金", "交存标准"],
        "people": ["买新房的人", "业主", "售楼处客户", "家里老人", "自己"],
        "intents": ["交多少", "去哪交", "什么时候交", "能不能退", "标准怎么算", "咨询哪里"],
    },
    {
        "topic": "预约办事",
        "aliases": ["网上预约", "预约窗口", "办事预约", "政务预约", "取号"],
        "people": ["上班族", "带老人办事", "外地回来的人", "学生家长", "自己"],
        "intents": ["怎么预约", "入口在哪", "能不能取消", "迟到了怎么办", "需要提前几天", "预约后还排队吗"],
    },
    {
        "topic": "公积金服务网点",
        "aliases": ["公积金网点", "分中心", "公积金窗口", "服务网点", "公积金大厅"],
        "people": ["家附近", "单位附近", "新北这边", "武进这边", "溧阳这边"],
        "intents": ["哪里最近", "电话多少", "上班时间", "能办提取吗", "要不要预约", "周末开吗"],
    },
]

OPENERS = [
    "{person}想问下{alias}{intent}？",
    "{alias}这个事{intent}，去哪问比较靠谱？",
    "我不太确定名字，应该是{alias}，{intent}？",
    "{person}要办{alias}，{intent}吗？",
    "麻烦帮我查一下{alias}，主要想知道{intent}。",
    "{alias}是不是可以网上处理，顺便看下{intent}。",
    "如果是{person}办{alias}，{intent}？",
    "请问{alias}现在{intent}，流程复杂吗？",
    "{alias}有点急，{intent}，今天能先了解下吗？",
    "我只知道大概是{alias}，想问{intent}。",
]

FOLLOW_UPS = [
    "那这个一般要几个工作日？",
    "如果不是本人去，可以代办吗？",
    "材料能不能拍照上传，还是必须纸质？",
    "入口在哪里，我没找到。",
    "这个属于审批还是备案一类的？",
    "周末或者下班后能不能办？",
    "有没有咨询电话或者窗口地址？",
    "如果资料不全会不会退回？",
    "线上提交后还要不要跑现场？",
    "办完会不会短信通知？",
    "我这种情况算不算符合条件？",
    "要不要先预约，还是直接去取号？",
]

NOISY_DETAILS = [
    "我在本地",
    "天宁这边",
    "北区附近",
    "武进这边",
    "家里老人不太会手机",
    "公司刚成立",
    "只有营业执照还没别的材料",
    "之前没办过",
    "想一次问清楚",
    "最好别跑好几趟",
    "手机上能弄最好",
    "窗口人多的话想先预约",
]


def normalize_query_text(query: str) -> str:
    replacements = {
        "吗吗": "吗",
        "？？": "？",
        "，，": "，",
        "。。": "。",
        "？。": "？",
        "？ 另外": "？另外",
    }
    for old, new in replacements.items():
        query = query.replace(old, new)
    return " ".join(query.strip().split())


def generate_questions(*, count: int = 500, seed: int = 20260703) -> list[ProbeQuestion]:
    rng = random.Random(seed)
    questions: list[ProbeQuestion] = []
    seen: set[str] = set()
    conversation_count = 25

    while len(questions) < count:
        topic_info = TOPIC_POOLS[len(questions) % len(TOPIC_POOLS)]
        conversation_index = (len(questions) % conversation_count) + 1
        turn_index = (len(questions) // conversation_count) + 1
        alias = rng.choice(topic_info["aliases"])
        person = rng.choice(topic_info["people"])
        intent = rng.choice(topic_info["intents"])

        is_follow_up = False
        if turn_index > 1 and rng.random() < 0.22:
            is_follow_up = True
            query = rng.choice(FOLLOW_UPS)
            if rng.random() < 0.65:
                query = f"{alias}，{query}"
        else:
            query = rng.choice(OPENERS).format(alias=alias, person=person, intent=intent)

        if rng.random() < 0.38:
            query = f"{query}（{rng.choice(NOISY_DETAILS)}）"
        if rng.random() < 0.16:
            extra_intent = rng.choice([item for item in topic_info["intents"] if item != intent])
            query = f"{query} 另外也想知道{extra_intent}。"
        if rng.random() < 0.08:
            query = query.replace("？", "")

        normalized = normalize_query_text(query)
        if normalized in seen:
            continue
        seen.add(normalized)
        questions.append(
            ProbeQuestion(
                index=len(questions) + 1,
                conversation_index=conversation_index,
                turn_index=turn_index,
                topic=str(topic_info["topic"]),
                style="follow_up" if is_follow_up else "realistic_user",
                query=normalized,
            )
        )
    return questions


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def question_to_row(question: ProbeQuestion, *, knowledge_id: str) -> dict[str, Any]:
    return {
        "index": question.index,
        "conversation_index": question.conversation_index,
        "turn_index": question.turn_index,
        "topic": question.topic,
        "style": question.style,
        "knowledge_id": knowledge_id,
        "query": question.query,
        "request_id": question.request_id,
        "dify_conversation_id": question.dify_conversation_id,
        "dify_message_id": question.dify_message_id,
        "dify_workflow_run_id": question.dify_workflow_run_id,
    }


def post_json(url: str, api_key: str, payload: dict[str, Any], *, timeout: float) -> tuple[int, dict[str, Any] | None, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else None
            return int(response.status), parsed, ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), None, body[:1000]
    except Exception as exc:
        return 0, None, str(exc)[:1000]


def call_one(row: dict[str, Any], *, url: str, api_key: str, timeout: float) -> dict[str, Any]:
    payload = {
        "knowledge_id": row["knowledge_id"],
        "query": row["query"],
        "retrieval_setting": {"top_k": 5, "score_threshold": 0.0},
        "request_id": row["request_id"],
        "dify_conversation_id": row["dify_conversation_id"],
        "dify_message_id": row["dify_message_id"],
        "dify_workflow_run_id": row["dify_workflow_run_id"],
    }
    started = time.perf_counter()
    status, parsed, error = post_json(url, api_key, payload, timeout=timeout)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    records = list((parsed or {}).get("records") or [])
    return {
        **row,
        "status": status,
        "ok": status == 200,
        "elapsed_ms": elapsed_ms,
        "record_count": len(records),
        "top_score": records[0].get("score") if records else None,
        "top_title": records[0].get("title") if records else None,
        "error": error,
    }


def collect_traces(metrics_path: Path, request_ids: set[str]) -> dict[str, dict[str, Any]]:
    traces: dict[str, dict[str, Any]] = {}
    if not metrics_path.exists():
        return traces
    with metrics_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "rag_trace":
                continue
            request_id = str(row.get("request_id") or "")
            if request_id in request_ids:
                traces[request_id] = row
    return traces


def run_probe(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    questions = generate_questions(count=args.count, seed=args.seed)
    question_rows = [question_to_row(item, knowledge_id=args.knowledge_id) for item in questions]
    questions_path = output_dir / "questions.jsonl"
    results_path = output_dir / "results.jsonl"
    summary_path = output_dir / "summary.json"
    write_jsonl(questions_path, question_rows)

    if args.generate_only:
        print(f"generated={len(question_rows)} questions_path={questions_path}")
        return 0

    if not args.api_key:
        print("api key required for run mode", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(call_one, row, url=args.api_url, api_key=args.api_key, timeout=args.timeout)
            for row in question_rows
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if len(results) % 50 == 0:
                ok_count = sum(1 for item in results if item["ok"])
                print(f"progress={len(results)}/{len(question_rows)} ok={ok_count}", flush=True)

    results.sort(key=lambda item: int(item["index"]))
    write_jsonl(results_path, results)

    # Metrics logging is async; allow the background writer to flush.
    time.sleep(args.metrics_flush_wait)
    request_ids = {str(row["request_id"]) for row in question_rows}
    traces = collect_traces(Path(args.metrics_path), request_ids)
    missing_trace_ids = sorted(request_ids - set(traces))
    failures = [row for row in results if not row["ok"]]
    zero_record_count = sum(1 for row in results if row["ok"] and int(row["record_count"] or 0) == 0)
    summary = {
        "question_count": len(question_rows),
        "response_ok_count": len(results) - len(failures),
        "response_failure_count": len(failures),
        "trace_count": len(traces),
        "missing_trace_count": len(missing_trace_ids),
        "zero_record_count": zero_record_count,
        "avg_elapsed_ms": round(sum(float(row["elapsed_ms"]) for row in results) / max(1, len(results)), 2),
        "p95_elapsed_ms": percentile([float(row["elapsed_ms"]) for row in results], 0.95),
        "questions_path": str(questions_path),
        "results_path": str(results_path),
        "metrics_path": args.metrics_path,
        "sample_failures": failures[:10],
        "sample_missing_trace_ids": missing_trace_ids[:20],
        "sample_trace_conversation_ids": sorted(
            {str(row.get("conversation_id")) for row in traces.values() if row.get("conversation_id")}
        )[:10],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures and not missing_trace_ids else 1


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, max(0, round((len(values) - 1) * q)))
    return round(values[index], 2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate 500 realistic Dify queries and verify RAG trace logging.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--knowledge-id", default=DEFAULT_KNOWLEDGE_ID)
    parser.add_argument("--output-dir", default="artifacts/dify_trace_500")
    parser.add_argument("--metrics-path", default="artifacts/dify_trace_500/rag_metrics.jsonl")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260703)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--metrics-flush-wait", type=float, default=2.0)
    parser.add_argument("--generate-only", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run_probe(build_parser().parse_args()))
