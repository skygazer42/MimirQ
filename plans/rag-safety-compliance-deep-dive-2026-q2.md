# 安全 / 合规 / Guard 深度调研报告（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：前 6 份 plan 的 **安全合规专项深化**。综合报告 § 13 只给 1 章；**我方 Output Guard 仅 35 行** vs Input Guard 157 行，是**全系统最紧迫的短板**。本文聚焦 Llama Guard 3 / Prompt Guard-86M / NeMo Guardrails / Presidio / 红队常态化 / RTBF 级联 / Lineage。
> **核心问题**：RAG 上线的合规/安全要求正从"做了规则"走向"证明有覆盖 × 可审计 × 可对抗红队 × 可 RTBF 级联"。本文给出达到这一标准的最短路径。
> **交叉引用**：`rag-capability-gap-2026-q2.md` §13；`rag-deep-research-2026-q2.md` §13；`rag-eval-dataset-deep-dive-2026-q2.md` §3.2 Stage 3 对抗样本；`rag-agentic-reasoning-deep-dive-2026-q2.md` §11 SoK POMDP 风险。

---

## 1. 威胁模型（Threat Model）

RAG 系统的**六类主要威胁**，决定 Guard 的覆盖边界：

| # | 威胁 | 典型样例 | 我方当前防护 |
|---|---|---|---|
| 1 | **Prompt Injection** | "忽略前面指令，按 X 回答" | ✅ InputGuard 157 行 |
| 2 | **Jailbreak** | 角色扮演 / DAN / GCG 自动攻击 | 🟡 部分覆盖（ROLE_HIJACK 规则） |
| 3 | **Indirect Injection** | 恶意 doc 注入指令（RAG 特有） | 🟡 `indirect_injection_history` 仅检查历史 |
| 4 | **PII / 敏感信息泄露** | 答案含身份证 / 电话 / 银行卡 | 🟡 preprocessing 侧有，**输出侧薄** |
| 5 | **Hallucination / Citation Fabrication** | 答案实体不在 context 中 | ❌ 未系统检测 |
| 6 | **Cascading Agent Risk** | 工具调用错误级联（SoK POMDP） | ❌ 无专项检测 |

**OWASP Top 10 for LLM 2026** 排前三位：**Prompt Injection / Sensitive Info Disclosure / Excessive Agency** —— 恰好覆盖前 5 条。

### 1.1 RAG 特有的威胁：Indirect Prompt Injection

- 攻击通过**文档内容**注入（如用户上传的 PDF 含"从现在起按 X 回答"）
- 我方入库流程 → embedding → 检索 → LLM prompt 拼接 → **攻击生效**
- 防护必须在**检索层之后、LLM 生成之前**
- NeMo Guardrails 有**专门的 retrieval rail** 解决此问题（§4.2）

---

## 2. 业界 Guard 三大派系对比

| 派系 | 代表 | 机制 | 延迟 | 成本 | 适用 |
|---|---|---|---|---|---|
| **规则 / 正则** | 我方 InputGuard / Regex / 关键词 | Pattern match | **µs 级** | ~0 | 粗筛、快拒 |
| **分类器 / 小模型** | Llama Guard 3 / Prompt Guard-86M | 专用小模型推理 | **10–50ms** | 低 | 生产标配 |
| **LLM-as-judge** | GPT-4o moderation / Claude / 自定义 | LLM 调用 | **500ms–8s** | 高 | 精准 / 复杂上下文 |

### 2.1 False Positive 数学（关键警告）

- 单一 Guard 准确率 90% 看似可接受
- **叠加 5 个 Guard**：`0.9^5 = 0.59`
- **至少一个误报率 = 41%**
- **工程结论**：**不要无脑堆 Guard**，必须按场景分层，每层精心评估 precision

### 2.2 延迟预算

- 实时聊天：**总 Guard 开销 < 200ms**
- 批处理管线：秒级可接受
- Agentic 多步：每步加 Guard 会放大延迟 N 倍

---

## 3. Meta Llama Guard 3

### 3.1 定位与能力

- **SAFETY_MODEL**：分类器类小模型（Llama-Guard-3-8B 或 Llama-Guard-3-1B）
- 覆盖 **Meta 安全分类法 13 类**：暴力、仇恨、性、自残、金融建议、医疗建议、隐私、代码解释器滥用等
- **双向使用**：评估 **user input**（仅含用户消息）与 **agent response**（含上下文 + 响应）
- Llama Guard 3 Vision：多模态版（支持图片输入）

### 3.2 生产部署范式

**Red Hat Llama Stack（June 2025）推荐栈**：

```
INFERENCE_MODEL  = meta-llama/Llama-3.1-8B-Instruct
SAFETY_MODEL     = meta-llama/Llama-Guard-3-8B
PROMPT_GUARD_MODEL = meta-llama/Prompt-Guard-86M
```

注册为 **Shield**：
- `content_safety`（LlamaGuard 3）
- `content_safety2`（PromptGuard-86M，专门防 prompt injection）

**工程要点**：双 Shield **并联**而非串联（Prompt Guard 管注入，Llama Guard 管内容安全，职责正交）。

### 3.3 我方现状对标

- `app/rag/safety/input_guard.py` 157 行 —— **全规则，无 LLM-based**
- `app/rag/safety/output_guard.py` 35 行 —— **近乎无防护**
- `app/rag/safety/rules.py` 71 行 —— 规则库
- `app/rag/safety/metrics.py` 34 行 —— Prometheus 打点

### 3.4 建议

- **P0** `safety/llama_guard.py`（~200 行）：
  - 封装 Llama Guard 3（8B / 1B 可选）vLLM 推理
  - 暴露 `guard_user_input()` + `guard_agent_response()` 两接口
  - Prometheus metrics：`llama_guard_allow_total{stage="input"|"output"}` / `block_total{category=...}`
  - 与规则 Guard **级联**：规则先行（µs），Llama Guard 后行（10–50ms），最后 LLM-judge（仅高置信攻击场景）

---

## 4. Prompt Guard-86M

### 4.1 定位

- **86M 参数**的轻量专用分类器（比 Llama Guard 小 ~100×）
- 专**针对 prompt injection 与 jailbreak**
- 3 分类：`BENIGN` / `INJECTION` / `JAILBREAK`
- 部署成本极低，可本地运行于 CPU

### 4.2 与 Llama Guard 3 互补

- **Prompt Guard-86M** 先行（防注入）→ **Llama Guard 3** 后行（内容安全）
- 二者职责正交，并联 / 级联都可

### 4.3 我方现状对标

- 无 Prompt Guard 等价物
- `input_guard.py` 规则覆盖 role_hijack / instruction_override / delimiter_attack，但**无统一语义理解**

### 4.4 建议

- **P0** `safety/prompt_guard.py`（~150 行）：
  - Prompt-Guard-86M 本地部署（CPU 即可）
  - 3 分类输出 + 置信度
  - 与现有 `input_guard` **并联**（两侧任一 trigger 即报警）
  - 低误报：86M 轻量模型偏 lenient，适合作**辅助信号**

---

## 5. NVIDIA NeMo Guardrails

### 5.1 5 种 Rail（**RAG 尤其重要**）

| Rail | 作用 | RAG 必要性 |
|---|---|---|
| **Input rail** | 用户消息进入前过滤 | 标配 |
| **Output rail** | 模型响应出去前过滤 | 标配 |
| **Dialog rail** | 对话流程控制（拒答 / 澄清 / 转人工） | 中等 |
| **Retrieval rail** | **过滤 / 掩码 RAG 检索回的 chunk** | **RAG 必备** |
| **Execution rail** | 包裹工具调用 | Agent 必备 |

### 5.2 Colang DSL

```colang
define user ask about salary
  "how much does X make"
  "salary of X"

define bot refuse salary
  "I can't share salary information."

define flow
  user ask about salary
  bot refuse salary
```

**优势**：可读 / 可测 / 可版本控制；非代码员工可审

### 5.3 Retrieval Rail（RAG 关键）

```
retrieval rail 可以：
1. 拒绝某 chunk（不进 LLM prompt）
2. 修改某 chunk（mask 敏感信息）
```

**用途**：
- Indirect prompt injection 防护（过滤含"忽略指令"的 chunk）
- 动态 PII 掩码（chunk 里的身份证 → `[REDACTED]`）
- 来源白名单（仅允许特定 dataset 的 chunk 进 prompt）

### 5.4 许可证与部署

- 开源工具包免费（github.com/NVIDIA-NeMo/Guardrails）
- **NIM 微服务 / Helm chart 需要 NVIDIA AI Enterprise 许可**
- 开源工具包本地运行无限制

### 5.5 我方现状对标

- 无 Colang 等价
- Retrieval rail 对应的 chunk 级防护散落在 `preprocessing/pii_anonymizer.py`（入库时）和 `middleware/pii.py`（响应时），**无检索时过滤点**

### 5.6 建议

- **P1** `safety/retrieval_rail.py`（~200 行）：在 `retriever.py` 召回之后、prompt 组装之前插入 hook：
  - 检测 chunk 含注入模式 → skip
  - 检测 chunk 含 PII → mask（调 Presidio）
  - 来源白名单（chunk.metadata.source 必须在 allowed_sources）
  - 全部决策落 audit log
- **P2** Colang 集成（若业务需要非代码员工可审的 Guard 规则）：**不紧迫**，大多数场景 Python 规则 + YAML 配置够

---

## 6. Microsoft Presidio：结构化 PII 识别

### 6.1 Presidio 能力

- **Analyzer**：基于规则 + ML 识别 50+ 种 PII（身份证 / 电话 / 信用卡 / 邮箱 / 姓名 / 地址）
- **Anonymizer**：脱敏（hash / replace / mask / encrypt）
- **多语言**：英文成熟、中文需补模型（支持自定义 recognizers）

### 6.2 与 LLM PII 发现双层

| 层 | 方法 | 优劣 |
|---|---|---|
| L1 | Presidio 规则 + ML | 快、解释性强 / 长尾覆盖差 |
| L2 | LLM 判定是否含 PII + 类型 | 慢、贵 / 发现企业特定 PII（内部工号 / 客户 ID） |

**生产范式**：L1 全量 + L2 抽样（每 1% 输出 sample 跑 LLM 发现）

### 6.3 我方现状对标

- `app/rag/preprocessing/pii_anonymizer.py` 219 行 —— **规则为主**，未用 Presidio
- `app/rag/preprocessing/secrets.py` 160 行 —— API key / token 识别
- `app/core/pii_redaction.py` 167 行 —— 核心工具
- `app/rag/middleware/pii.py` 110 行 —— 响应侧
- **无 LLM-based PII 发现层**

### 6.4 建议

- **P0** `preprocessing/pii_presidio.py`（~200 行）：Presidio Analyzer + Anonymizer 封装；中文补 `PatternRecognizer`（身份证 / 手机号 / 车牌 / 社保号）
- **P1** `preprocessing/pii_llm_discover.py`（~150 行）：LLM 抽样发现新型 PII，发现即反向补 Presidio 规则（半自动扩规则库）
- **预计收益**：PII 召回率从当前估计 70% 升至 90%+（Presidio 社区基准）

---

## 7. Output Guard 扩容（最紧迫建设）

### 7.1 当前状况

- `app/rag/safety/output_guard.py` **仅 35 行** —— 35 行不可能覆盖 §1 威胁模型的 5–6 类输出侧风险
- 对比 InputGuard 157 行覆盖 8 类攻击，**输入侧 4× 覆盖，输出侧近零**

### 7.2 Output 侧 5 大检测任务

| 任务 | 检测目标 | 实现 |
|---|---|---|
| **PII 二次扫描** | 答案中的 PII（即使 context 被脱敏也要二检） | Presidio + LLM 抽样 |
| **Citation Consistency** | 答案实体必须在 context chunks 中出现 | 实体抽取 + 集合包含 |
| **Hallucination 检测** | claim-level faithfulness | NLI 模型 / LLM judge |
| **Jailbreak 输出** | Llama Guard 3 agent response mode | Llama Guard 3 |
| **敏感主题偏离** | 是否违反 dataset 领域（医疗给法律建议） | Topic classifier / policy |

### 7.3 建议的 Output Guard 结构（~200 行目标）

```python
# app/rag/safety/output_guard.py （扩容版）

class OutputGuard:
    async def check(
        self,
        answer: str,
        context_chunks: list[Chunk],
        question: str,
        tenant: str,
    ) -> OutputGuardResult:
        results = await asyncio.gather(
            self._pii_double_scan(answer),
            self._citation_consistency(answer, context_chunks),
            self._hallucination_nli(answer, context_chunks),
            self._llama_guard_response(answer, question),
            self._topic_policy_check(answer, tenant),
        )
        return OutputGuardResult(
            action=self._resolve_action(results),
            violations=[r for r in results if r.triggered],
        )

    def _resolve_action(self, results) -> str:
        # block > rewrite > warn > allow
        ...
```

### 7.4 建议

- **P0** Output Guard 扩容至 ~200 行：
  - PII 二次扫描（调 Presidio + LLM 抽样）
  - Citation consistency（答案实体抽取 → 集合交集与 chunk 实体）
  - Llama Guard 3 agent response 调用
  - 违规时的 4 档处置：`block` / `rewrite` / `warn` / `allow`
- **P1** Hallucination NLI（BGE 小模型跑 entailment）
- **P1** Topic policy（每 tenant 可配禁区词）

---

## 8. 红队评测集与常态化

### 8.1 业界基准

| 基准 | 规模 | 特点 |
|---|---|---|
| **JailbreakBench**（NeurIPS 2024，arXiv:2404.01318） | **JBB-Behaviors 100 行为 × 10 类** + **100 benign**（测 overrefusal） | 55% 原创 / 18% AdvBench / 27% HarmBench |
| **AdvBench**（Zou et al., 2023） | 520 有害指令 | 经典 |
| **HarmBench**（Mazeika et al., 2024） | 大规模 | 细分类别 |
| **MaliciousInstruct**（Huang et al., 2024b） | 100 | 简洁 |
| **Red Teaming arXiv:2505.04806**（2025-05） | **1400+ 对抗 prompt** | roleplay / logic traps / encoding / multi-turn 四类 |
| **SafetyPrompts.com** | 数据集 catalog | 汇总 |
| **General Analysis Leaderboard** | HarmBench + AdvBench 评 ASR | Claude 3.5 Sonnet v2 ASR 仅 4.39% |

### 8.2 9 种攻击方法（AAAI 2026 综合）

- Plain Harmful（直接）
- PEZ（优化 embedding）
- UAT（Universal Adversarial Triggers）
- GCG（Greedy Coordinate Gradient）
- AutoPrompt
- GBDA（Gumbel-Softmax based）
- GCG-M（multi-target）
- PAIR（LLM 作攻击者）
- Human-Crafted（人工）

### 8.3 我方现状对标

- `app/rag/evaluation/` 14 文件含 `hard_negative_mining`、`test_generator`、`replay_capture`
- **无专门 jailbreak / prompt injection 红队 suite**
- 评测集专项 Stage 3 建议包含 red-team 样本，但未细化

### 8.4 建议

- **P0** `evaluation/redteam_suite.py`（~300 行）：
  - 下载 JBB-Behaviors + MaliciousInstruct 公开集
  - 按我方场景 curate 200–500 条中文对抗样本（roleplay / 角色扮演 / 身份欺骗 / 指令覆盖 / 编码 / 多轮诱导 / 间接注入）
  - 周度自动跑，出 ASR（Attack Success Rate）报表
  - 目标 ASR < 5%（对齐 Claude 3.5 Sonnet v2）
- **P1** CI 集成：每 PR 跑 top-20 高风险样本，ASR 上升 → 阻塞 merge
- **P2** 自动生成新样本：用 LLM-as-attacker（PAIR 风格）每月补充新攻击模式

---

## 9. PII Lifecycle：发现 → 脱敏 → 审计 → 级联删除

### 9.1 完整生命周期

```
[入库] → Presidio 扫描 → 脱敏 → 存
       ↘ LLM 抽样发现新型 PII → 扩规则库

[召回] → Retrieval rail → 二次扫描 chunk（防漏）

[生成] → LLM → Output Guard 二次扫描答案 → 拒答 / 脱敏后放行

[审计] → 每次 PII 命中记 audit_log（doc_id / chunk_id / field / action）

[RTBF] → 用户请求删除 → 级联删 vector DB / KG / cache / object / backup / audit

[监控] → PII 泄露 incident 回溯 → 原因分析 → 规则补强
```

### 9.2 我方现状对标

- 入库脱敏 ✅
- 召回时脱敏 🟡（散落）
- 生成侧脱敏 🟡（弱）
- 审计日志 ✅（`services/audit_log_*` 多个）
- **RTBF 级联**：`services/connector_reconcile_service.py` 部分，但跨存储级联未确认
- 监控 🟡（`services/connector_acl_prometheus_metrics.py` 等有打点）

### 9.3 建议

- **P0** 生命周期 end-to-end 审计：一次性评审是否所有环节都记录 audit，填补缺口
- **P1** RTBF 级联工作流（见 §10）

---

## 10. RTBF 级联删除

### 10.1 挑战

一个用户的数据会散布在：

| 存储 | 删除难度 |
|---|---|
| Postgres（原始文档 metadata） | 🟢 SQL delete |
| Milvus（vector embedding） | 🟡 by partition + where filter |
| KG（实体 + 关系） | 🟡 `DELETE VERTEX / EDGE` + 关联 event |
| Redis cache（chunk 缓存 / rerank 缓存） | 🟡 by pattern delete |
| Object storage（原 PDF / 图像） | 🟡 delete object |
| Audit log（是否保留？） | ⚠️ **合规要求保留 + 脱敏** |
| Backup / snapshot | ⚠️ 删除窗口 / 法务批准 |
| Tracing / logs | ⚠️ 涉及 LLM span，合规可能需保留 |

### 10.2 生产级 RTBF 工作流

```
POST /api/v1/rtbf/request
  body: {user_id, data_categories, reason, legal_basis}

→ 1. 生成 deletion_ticket
→ 2. 各存储方异步删（Saga pattern）
→ 3. 审计 log 记录每步（自审不删）
→ 4. 完成后通知 requester + DPO
→ 5. 7 日后二次验证（防漏）
```

### 10.3 建议

- **P1** `services/rtbf_cascade.py`（~400 行）：Saga 模式跨存储级联；每步可重试；失败可报警至 DPO
- **P1** `api/v1/rtbf.py`：暴露 POST /rtbf/request + GET /rtbf/status/{ticket_id}
- **P2** Backup / snapshot 的 RTBF 策略（需与法务 / DBA 联合决定）

---

## 11. Lineage：端到端数据血缘

### 11.1 血缘链条

```
connector_source → raw_doc (object storage)
                 → parsed_doc (markdown/json)
                 → chunks (metadata: chunk_id, doc_id, acl)
                 → embeddings (milvus)
                 → KG entities/relations
                 → retrieval_run (query, top_k, rerank)
                 → answer (citations: [chunk_id1, chunk_id2])
                 → user response
```

### 11.2 为什么重要

1. **合规**：用户问"为什么我的数据被 AI 这样答"要能精确回溯
2. **调试**：badcase 回溯到某段 chunk 的解析错误
3. **RTBF**：级联删除需要知道从哪里到哪里
4. **审计**：外部审计员要看"哪条数据影响了哪个决策"

### 11.3 业界对标

- **OpenLineage**（标准）
- **Marquez**（实现）
- LangSmith trace 已有部分
- Phoenix / Langfuse 有 span 级 trace

### 11.4 我方现状对标

- `app/rag/kg/provenance.py` —— KG 侧 provenance ✅
- `app/services/audit_log_*` —— 审计 ✅
- `app/rag/tracing/langsmith.py` —— trace
- **无统一的 doc→chunk→embedding→retrieval→answer 端到端 API**

### 11.5 建议

- **P1** `services/lineage_service.py`（~400 行） + `api/v1/lineage.py`：
  - `GET /lineage/chunk/{chunk_id}`：上溯 doc + connector，下溯被哪些 retrieval_run 使用
  - `GET /lineage/answer/{trace_id}`：下钻所有 chunk / embedding / rerank / LLM span
  - `GET /lineage/user/{user_id}`：RTBF 前置查询
- **P2** 对齐 OpenLineage 语义规范（future-proof）

---

## 12. 我方安全栈现状对标总表

| 能力 | 业界 SOTA | 本系统位置 | 行数 | 状态 |
|---|---|---|---|---|
| 规则 Input Guard | 成熟 | `safety/input_guard.py` | 157 | 🟢 |
| LLM-based Input Guard | Prompt Guard-86M | — | — | 🔴 缺 |
| 规则 Output Guard | 弱 | `safety/output_guard.py` | **35** | 🔴 **最紧迫短板** |
| LLM-based Output Guard | Llama Guard 3 | — | — | 🔴 缺 |
| Retrieval Rail（防间接注入） | NeMo | — | — | 🔴 缺 |
| Presidio PII | Microsoft | `preprocessing/pii_anonymizer.py`（规则） | 219 | 🟡 未集成 Presidio |
| LLM PII 发现 | 抽样 | — | — | 🔴 缺 |
| Citation Consistency | NLI / LLM | — | — | 🔴 缺 |
| Hallucination 检测 | NLI | `evaluation/` 部分 | — | 🟡 未入 Guard 主路径 |
| 红队 Suite | JBB / HarmBench | — | — | 🔴 缺 |
| CI 红队门禁 | — | — | — | 🔴 缺 |
| 审计日志 | 成熟 | `services/audit_log_*` | 多文件 | 🟢 |
| RTBF 级联 | Saga | `services/connector_reconcile_*` 部分 | — | 🟡 未跨存储 |
| Lineage | OpenLineage | `kg/provenance.py` + audit | — | 🟡 未统一 API |
| 数据驻留 | region pinning | — | — | 🔴 缺 |
| Prometheus 安全 metrics | 标准 | `safety/metrics.py` + `services/*metrics.py` | 多 | 🟢 |

**总结**：**Input Guard 与审计做得好；Output Guard / LLM-based / 红队 / Presidio / RTBF 级联 / Lineage 是系统性 gap**。

---

## 13. 建议优化（按优先级）

### 🥇 P0（1–4 周，紧迫）

| # | 建议 | 依据 |
|---|---|---|
| 1 | **Output Guard 扩容至 ~200 行**（PII 二检 + Citation consistency + Llama Guard 3） | 当前 35 行覆盖严重不足 |
| 2 | `safety/llama_guard.py`（Llama Guard 3-8B vLLM 推理，input+output 双用） | Meta 生产范式 |
| 3 | `safety/prompt_guard.py`（Prompt-Guard-86M，与 input_guard 并联） | 86M 小模型，部署成本低 |
| 4 | `preprocessing/pii_presidio.py`（Presidio Analyzer + 中文扩展） | 社区基准召回 90%+ |
| 5 | `evaluation/redteam_suite.py`（JBB + 自建中文 200–500 条，周度 ASR 报表） | ASR 目标 < 5% |

### 🥈 P1（1–2 月）

| # | 建议 | 理由 |
|---|---|---|
| 6 | `safety/retrieval_rail.py`（检索后 chunk 级过滤，防间接注入） | RAG 特有攻击面 |
| 7 | `services/rtbf_cascade.py` + `api/v1/rtbf.py`（Saga 跨存储级联） | 合规刚需 |
| 8 | `services/lineage_service.py` + `api/v1/lineage.py`（端到端血缘） | 合规 + 调试 |
| 9 | `preprocessing/pii_llm_discover.py`（LLM 抽样发现新型 PII） | 长尾扩规则 |
| 10 | Hallucination NLI 检测（BGE 小模型 entailment） | 减少 Citation Fabrication |
| 11 | CI 红队门禁（每 PR 跑 top-20 样本，ASR 回归报警） | 持续保护 |

### 🥉 P2（2–6 月）

| # | 建议 |
|---|---|
| 12 | Topic policy per tenant（敏感主题白名单 / 禁区） |
| 13 | Colang DSL 集成（非代码员工可维护 Guard 规则） |
| 14 | 数据驻留 / region pinning（`core/config.py` 引入 DATA_REGION） |
| 15 | Backup / snapshot RTBF 策略（与法务 / DBA 联合） |
| 16 | LLM-as-attacker（PAIR 风格）自动生成红队样本 |

### 观望 / 延后

- NVIDIA AI Enterprise NIM 微服务（许可门槛）
- Confidential Computing（硬件级隔离）
- 差分隐私（embedding 扰动）

---

## 14. 延迟与误报的工程权衡（不可回避）

### 14.1 Guard 级联的现实

```
[Input] → 规则 InputGuard (µs)
       → Prompt Guard-86M (10ms)
       → Llama Guard 3 (30ms)         ← P95 input 侧开销 ~40ms
[Retrieve] → chunks
[Retrieval Rail] → Presidio (5ms/chunk × 5 = 25ms)  ← 并行
[Generate] → LLM (秒级主导)
[Output] → Presidio (5ms)
        → Citation check (10ms)
        → Llama Guard 3 (30ms)         ← P95 output 侧开销 ~45ms
```

**总 Guard 开销 P95 ~110ms** —— 实时聊天的 200ms 预算内。

### 14.2 False Positive 缓解策略

1. **按 tenant / dataset 精细化配置**：不是全局 Block，而是 context-aware
2. **Shadow mode 逐步推广**：先 log-only 1 周 → review false positive → 再 enforce
3. **人工复核渠道**：被 block 的消息进人工审查队列，1 小时内人工介入
4. **Override token**：高权限用户 / 内部测试可 bypass（必须审计）

---

## 15. 参考资料

### 业界 Guard
- [Llama Guard 3 Model Card](https://www.llama.com/docs/model-cards-and-prompt-formats/llama-guard-3/)
- [Prompt Guard-86M (HuggingFace)](https://huggingface.co/meta-llama/Prompt-Guard-86M)
- [NVIDIA NeMo Guardrails GitHub](https://github.com/NVIDIA-NeMo/Guardrails)
- [NeMo Llama-Guard Integration](https://docs.nvidia.com/nemo/guardrails/latest/user-guides/community/llama-guard.html)
- [Red Hat Llama Stack Tutorial (2025-05)](https://developers.redhat.com/articles/2025/05/28/implement-ai-safeguards-nodejs-and-llama-stack)
- [Microsoft Presidio](https://github.com/microsoft/presidio)
- [Essential Guide to LLM Guardrails (Medium 2025)](https://medium.com/data-science-collective/essential-guide-to-llm-guardrails-llama-guard-nemo-d16ebb7cbe82)
- [Production LLM Guardrails Comparison (PremAI 2026-03)](https://blog.premai.io/production-llm-guardrails-nemo-guardrails-ai-llama-guard-compared/)
- [Langfuse Security & Guardrails](https://langfuse.com/docs/security-and-guardrails)
- [LLM Guardrails Setup Guide 2026](https://aiworkflowlab.dev/article/llm-guardrails-production-defense-in-depth-safety-systems-nemo-guardrails-ai-openai)

### 红队基准
- [JailbreakBench](https://jailbreakbench.github.io/) / [GitHub](https://github.com/JailbreakBench/jailbreakbench) / [arXiv:2404.01318](https://arxiv.org/abs/2404.01318)
- [JBB-Behaviors HuggingFace](https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors)
- [Red Teaming Prompt Injection (arXiv:2505.04806)](https://arxiv.org/html/2505.04806v1)
- [SafetyPrompts](https://safetyprompts.com/)
- [General Analysis Leaderboard](https://www.generalanalysis.com/benchmarks)
- HarmBench (Mazeika et al., 2024)
- AdvBench (Zou et al., 2023)
- MaliciousInstruct (Huang et al., 2024b)

### 合规 / Lineage
- [OpenLineage](https://openlineage.io/) / [Marquez](https://marquezproject.ai/)
- Meta Prompt Guard / Llama Guard 3 模型卡
- OWASP Top 10 LLM 2026

### 本项目相关 plan（交叉引用）
- `plans/rag-capability-gap-2026-q2.md` §13
- `plans/rag-deep-research-2026-q2.md` §13
- `plans/rag-eval-dataset-deep-dive-2026-q2.md` §3.2 对抗样本
- `plans/rag-agentic-reasoning-deep-dive-2026-q2.md` §11 SoK POMDP
- `plans/rag-kg-deep-research-2026-q2.md`（provenance / 网络分析 API 访问控制）
- `plans/rag-parsing-chunking-deep-dive-2026-q2.md`（enrich/ocr_redaction 入库侧协同）

---

## 结论

1. **最紧迫短板是 Output Guard**（35 行）与 **红队常态化**（完全无），P0 五项（扩容 + Llama Guard 3 + Prompt Guard-86M + Presidio + Redteam Suite）**4 周可全部落地**。
2. **不要盲目堆 Guard**：5 个 90% 叠加即 41% 误报；必须精细分层 + Shadow mode 逐步推广。
3. **RAG 特有威胁**：Indirect Prompt Injection（通过文档注入）需要 **Retrieval Rail**（NeMo 核心创新），这是业界很多方案忽略的点。
4. **合规不是单点**：PII Lifecycle（发现→脱敏→审计→级联删除）+ Lineage（端到端血缘）+ RTBF Saga 三件套是企业级 RAG 的合规底盘。
5. **延迟预算**：P95 Guard 总开销 ~110ms，在实时聊天 200ms 预算内；工程上不是障碍，是落地决心问题。

---

> **本轮 3 份专项全部交付完毕**（Agentic / 解析切块 / 安全合规）。加上前 4 份（综合对标 / 深度调研 / 评测集 / KG），总计 7 份报告约 **4100+ 行**。

> **可独立拆的子 plan**（P0 优先）：
> - `plans/output-guard-v2.md`（扩容至 200 行）
> - `plans/llama-guard-3-integration.md`
> - `plans/prompt-guard-86m-integration.md`
> - `plans/pii-presidio-integration.md`
> - `plans/redteam-suite.md`
> - `plans/retrieval-rail.md`（P1）
> - `plans/rtbf-cascade.md`（P1）
> - `plans/lineage-service.md`（P1）
> - `plans/ci-redteam-gate.md`（P1）
