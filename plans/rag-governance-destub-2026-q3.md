# RAG 治理去桩计划（2026-Q3）——Guard 换真模型 + 红队真基线 + 隔离区五类归因

> 日期：2026-07-13 ｜ 前置调研：`plans/rag-safety-compliance-deep-dive-2026-q2.md`
> 定位：**政务交付的宣称风险止血**。当前"已有 Llama Guard / Prompt Guard / Presidio"的宣称与实现不符——三者均为同名正则桩；更严重的是红队 suite 测的就是这些桩，ASR 指标自欺。本计划让治理能力名实相符，且全程满足政务专网离线部署约束。

## Context（2026-07-13 核实）

| 组件 | 现状 | 证据 |
|---|---|---|
| llama_guard.py | 54 行，无模型加载 | `app/rag/safety/llama_guard.py`（无 torch/transformers import） |
| prompt_guard.py | 35 行，无模型加载 | `app/rag/safety/prompt_guard.py` |
| pii_presidio.py | 131 行纯正则（复用 pii_anonymizer + 车牌/社保正则），schema 挂 presidio 名但 **presidio 不在 requirements** | `app/rag/preprocessing/pii_presidio.py:1-25` |
| 红队 | redteam_suite.py 82 行**直接实例化上述桩**跑 case——ASR 数字测的是正则 | `app/rag/evaluation/redteam_suite.py:16-27` |
| 隔离区 | 单一 governance 来源，五类归因未做（字段在 `app/models/ingestion_run.py`） | 2026-07 核对 |
| chunk-ACL | 零命中（仅 API 层文档级权限） | 全库 grep |
| 已有可复用 | InputGuard 156 行规则式 / OutputGuard 122 行 / GLiNER 资产（KG extraction）/ pre_poc_scanner 全套 | — |

## 落地设计

### P0-1 Guard 去桩：本地模型三件套（政务离线约束下的选型）
- **Prompt Guard**：接 `Llama-Prompt-Guard-2-86M`（或 22M），transformers 本地加载，CPU 可跑（<20ms）；落 `prompt_guard.py`，保留现有 `check()` 接口与 label 语义，正则桩降级为模型不可用时的 fallback（复用 reranker factory 的健康检查+降级模式，`app/rag/reranker/factory.py:230` 先例）。
- **内容安全**：中文场景优先评估 `Llama-Guard-3-8B`（vLLM 本地） vs 国产替代（Qwen3Guard 类）；输出映射到现有 `guard_user_input/action` 接口。8B 延迟高 → 只挂**输出侧+异步审计**，输入侧靠 Prompt-Guard-86M + InputGuard 规则。
- **PII**：引入真 `presidio-analyzer/anonymizer`（离线、纯 Python，无外呼），现有中国正则（车牌/社保/身份证）注册为 presidio 自定义 recognizer——**规则资产不丢，换引擎**；`mimirq.pii_presidio_analysis.v1` schema 不变。
- 验收：三组件均有"模型加载成功/失败降级"健康端点；单测覆盖中英文各 20 例对抗样本。

### P0-2 红队真基线（去桩后立即跑，否则 P0-1 无法验收）
- 扩充 `redteam_suite.py`（现 82 行骨架）：注入攻击集 ≥200 条（提示注入/越狱/PII 诱导/跨文档 exfil 四类，中文为主），接现有显著性栈出报告。
- 产出**首个真实 ASR 基线**并写入文档；目标线 ASR <5%（Q2 调研既定）。此前所有 ASR 宣称作废。
- False Positive 同步测量（Q2 调研的"FP 叠加数学"警告）：多 Guard 串联的放行率 = ∏(1-FPᵢ)，给出每层 FP 预算。

### P1-1 隔离区五类来源归因
- 归因枚举落库：`governance_rule / guard_hit / pii_detected / precheck_failed / manual`，写入 ingestion_run 隔离字段 + quarantine 记录；前端五类饼图（`plans/rag-quarantine-frontend-deep-dive-2026-q2.md` P0 的后端前置）。
- 每类带 reason_code + 命中规则 ID，打通 industry_rules 与 pre_poc_scanner 的既有产出。

### P1-2 chunk 级 ACL（最小可用版）
- chunk metadata 增加 `acl_tags`（继承文档级 + 章节级覆写）；检索侧在 Milvus filter 表达式注入 tenant+acl 过滤（**过滤在召回前不在装配后**，防止越权内容进 rerank/LLM）。
- 验收：越权查询零泄漏的回归用例进 CI。

### P2 进阶
- 输出侧引用一致性 Guard：答案 claim 与 citation 的 NLI 校验（与验证域 llm_judge 共用小模型）。
- Guard 决策全量入审计日志（43 文件审计基建已有），支持"为什么拦我"申诉链路。

## 优先级矩阵

| 优先级 | 任务 | 工作量 | 落点 |
|---|---|---|---|
| P0 | Prompt-Guard-86M + presidio 真引擎 | ~3 人日 | `safety/prompt_guard.py`、`preprocessing/pii_presidio.py`、requirements |
| P0 | 红队集 200 条 + 真 ASR 基线 | ~4 人日 | `evaluation/redteam_suite.py` + 数据集 |
| P1 | 内容安全本地 8B（输出侧异步） | ~5 人日 | `safety/llama_guard.py` + vLLM 部署 |
| P1 | 隔离区五类归因 | ~3 人日 | `models/ingestion_run.py` + service |
| P1 | chunk-ACL 最小版 | ~4 人日 | chunk metadata + Milvus filter |

## 验证与门槛
- 每个 Guard：对抗集准确率 + FP 率 + p95 延迟三指标；输入侧 Guard 总延迟预算 ≤30ms（不破坏召回计划的延迟中性承诺）。
- 红队 ASR <5% 且 FP 串联放行率 ≥95% 才可对外宣称。

## 不做什么
- 不接外部内容安全 API（政务专网离线红线）；不自训 Guard 模型（用开源权重+规则组合）；NeMo Guardrails 整框架不引入（现有 pipeline 中间件足够挂点）。
