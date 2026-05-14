# RAG 清洗 / Embedding / Prompt 可执行计划 — 2026-Q2

> 来源计划:
> - `plans/rag-data-cleaning-rules-mainstream-2026-q2.md`
> - `plans/rag-embedding-models-mainstream-2026-q2.md`
> - `plans/rag-prompts-mainstream-research-2026-q2.md`
>
> 本文件不是复述调研结论,而是从 3 份调研里筛出当前代码里最值得做、风险可控、能验证的执行项。

## 0. 总计划表

### 0.1 落盘结论

本轮把三份调研计划合并成一个执行计划,只保留当前代码里值得做、能验证、风险可控的项:

- [x] Embedding 先做评测与 Matryoshka 实验,不直接换默认模型。
- [ ] Cleaning 先补 benchmark/golden set,再改 Unicode/PII/行业噪声规则。
- [ ] Prompt 先补安全、KG schema、引用正确性,再考虑平台化和外部工具。
- [ ] 暂缓新增重依赖、默认模型替换、Prompt 平台化、Milvus 量化默认启用等高运维/高回滚成本项。

### 0.2 可执行勾选表

| 状态 | 批次 | 编号 | 可做项 | 阶段 | 验收重点 |
|---|---|---:|---|---|---|
| [ ] | Cleaning | A1 | 建 `cleaning_bench` 小型 golden set 和 runner | 第一阶段 | 同一批 HTML/PII/行业噪声样本可重复输出指标 |
| [ ] | Cleaning | A2 | 数字保护型 Unicode normalization | 第一阶段 | `1½`、`Ⅸ`、全角数字不被 NFKC 误伤 |
| [ ] | Cleaning | A3 | 中文 PII fixture 与 USCI/银行卡补齐 | 第一阶段 | 身份证/手机号/银行卡/统一社会信用代码命中稳定,误报样本不过度替换 |
| [ ] | Cleaning | A4 | 扩已有 legal/finance/industrial_control 行业噪声包 | 第一阶段 | 每个行业都有命中/误删测试,precision 优先 |
| [ ] | Cleaning | A5 | 清洗 trace 输出规则命中统计 | 第二阶段 | ingest trace 能看到命中数、删除行数、保留率 |
| [ ] | Prompt | C1 | Prompt Guard 规则包化 + 分片检测 + optional hook | 第一阶段 | 中英 injection/jailbreak/benign fixture 全覆盖 |
| [ ] | Prompt | C2 | KG extraction schema 补强并抽独立 prompt 模板 | 第一阶段 | schema/snapshot 测试稳定,不破坏现有 selector |
| [ ] | Prompt | C3 | KG gleaning 做 1 轮可配置实验 | 第二阶段 | 同 fixture 记录 `gleaning=0/1` 的实体召回、成本、延迟 |
| [ ] | Prompt | C4 | Citation correctness evaluator | 第一阶段 | 引用 idx 必须指向真实 retrieved chunk |
| [ ] | Prompt | C5 | Refusal evaluator + 拒答集 | 第二阶段 | 应拒答样本在 regression summary 里有独立准确率 |
| [ ] | Prompt | C6 | `chat_with_schema` JSON/validation retry | 第二阶段 | 非 JSON/缺字段时可二次修复,失败保留 raw 降级 |
| [ ] | Embedding | B1 | Voyage/Cohere/Jina 真实 provider wrapper | 暂缓 | 需要官方 API contract / mock contract / 鉴权策略 |
| [x] | Embedding | B2 | Embedding benchmark runner skeleton | 已完成 | `tests/test_embedding_bench_runner.py` 覆盖 Recall/MRR/latency/cost 汇总 |
| [ ] | Embedding | B3 | Language routing trace/capability 校验 | 第二阶段 | trace 显示 provider/model,unsupported mapping 可 fallback |
| [x] | Embedding | B4 | Matryoshka shortlist + rescore 实验函数 | 已完成 | `tests/test_matryoshka_embedding.py` 覆盖低维召回 + 全维重排 |
| [ ] | Embedding | B5 | Shadow embedding 蓝绿迁移小样本验证 | 第二阶段 | 1k 文档双写脚本输出一致性和失败明细 |

## 1. 执行原则

- 先评测,再改默认: 清洗规则和 embedding 默认模型都不能凭榜单或直觉直接替换。
- 先低风险补短板: 优先补当前明显薄弱且已有代码入口的模块,避免大范围重构。
- 先后端质量闭环,再前端平台化: Prompt/Embedding/Cleaning 的管理页面放到 P1 之后。
- 不新增重依赖作为默认链路: `trafilatura`、`datasketch`、模型 guard、Bedrock SDK 等先做 optional 或 benchmark 后再定。
- 每个任务必须有 pytest 或离线 runner 证明,不能只改规则文本。

## 2. 推荐执行顺序

1. A 批: Cleaning benchmark + 安全清洗规则。
2. C 批: Prompt safety / citation / KG extraction 质量闭环。
3. B 批: Embedding provider 和 benchmark,最后再讨论默认模型。

---

## 3. A 批: 数据清洗规则

| 状态 | 编号 | 任务 | 主要落点 | 验收 |
|---|---:|---|---|---|
| [ ] | A1 | 建 `cleaning_bench` 小型 golden set,先评测再改规则 | `app/rag/evaluation/cleaning_bench/` 或 `evaluation/cleaning_bench/` | HTML/PII/行业噪声都有可重复跑的 JSON/HTML 报告 |
| [ ] | A2 | 数字保护型 Unicode normalization | `app/rag/preprocessing/normalization.py` | `1½`、`Ⅸ`、全角数字不被误伤;新增 `tests/test_preprocessing_normalization.py` 用例 |
| [ ] | A3 | 补中文 PII 覆盖: 统一社会信用代码、银行卡 entity 标准化、更多 fixture | `app/rag/preprocessing/pii_presidio.py`, `app/rag/preprocessing/pii_anonymizer.py` | 身份证/手机号/银行卡/USCI 均有 fixture;误报样本不被替换 |
| [ ] | A4 | 扩现有 3 个行业噪声包,不新开一堆空行业 | `app/parsing/preprocess/industry_noise_patterns/{legal,finance,industrial_control}.py` | 每个行业规则有命中/误删测试;precision 优先 |
| [ ] | A5 | 清洗 trace 输出规则命中统计 | ingest/processing trace 入口 | 上传样本时能看到规则命中数、删除行数、保留率 |

### A 批暂缓

| 状态 | 项 | 暂缓原因 |
|---|---|---|
| [ ] | 直接引入 `trafilatura` 作为强依赖 | 当前 `html_canonical.py` 只做 canonical URL;正文抽取需要先 benchmark + fallback |
| [ ] | 直接切 `datasketch MinHashLSH` | 现有 `near_dedup.py` 是 SimHash opt-in;替换前要先证明误删率 |
| [ ] | 新增 medical/government/manufacturing 行业包 | 没有当前样本时容易产生空规则包;先扩已有 legal/finance/industrial_control |

---

## 4. C 批: Prompt / KG / Safety

| 状态 | 编号 | 任务 | 主要落点 | 验收 |
|---|---:|---|---|---|
| [ ] | C1 | Prompt Guard 从 2 条正则扩成规则包 + 分片检测 + 可选模型 hook | `app/rag/safety/prompt_guard.py` | `tests/test_prompt_guard.py` 覆盖中英 injection/jailbreak/benign;攻击 fixture ASR 明显下降 |
| [ ] | C2 | KG extraction schema 补 `description` / `required` / `enum`,抽 prompt 到独立模板 | `app/rag/kg/extraction/processor.py`, `app/rag/llm/prompts/kg_extraction_prompts.py` | schema 测试 + prompt snapshot 稳定 |
| [ ] | C3 | KG gleaning 做 1 轮可配置,不默认无限迭代 | `app/rag/kg/extraction/processor.py`, `app/rag/kg/extraction/extractor.py` | 同一 fixture 对比 `gleaning=0/1`,实体召回有记录;成本和延迟进 trace |
| [ ] | C4 | Citation correctness evaluator | `app/rag/evaluation/citation_eval.py` | 引用 idx 必须真实指向被引 chunk;错误引用能被测出 |
| [ ] | C5 | Refusal evaluator 复用现有 answer_det/regression 指标,补拒答集 | `app/rag/evaluation/metrics/answer_det.py`, regression fixtures | 应拒答样本正确率可在 regression summary 里看到 |
| [ ] | C6 | `chat_with_schema` 增加 retry on JSON/validation failure | `app/rag/llm/base.py` | 返回非 JSON 时能二次修复;失败时仍保留 raw 降级 |

### C 批暂缓

| 状态 | 项 | 暂缓原因 |
|---|---|---|
| [ ] | Promptfoo CI / GitHub Action | 先补本地 evaluator 和 fixtures,否则 CI 只是空跑 |
| [ ] | Langfuse 自部署 + prompt sync | 平台化依赖运维和产品面,不作为当前质量短板第一步 |
| [ ] | Prompt Marketplace / 多行业大模板包 | 当前 `system_prompts.py` 只有基础 3 套;先补安全、引用、KG 质量闭环 |
| [ ] | Llama Prompt Guard 2 默认启用 | 模型依赖和性能成本未评估;先保留 optional hook |

---

## 5. B 批: Embedding

| 状态 | 编号 | 任务 | 主要落点 | 验收 |
|---|---:|---|---|---|
| [ ] | B1 | 修 provider 假支持: Voyage/Cohere/Jina 做真实 HTTP wrapper | `app/rag/embedding/providers/{voyage,cohere,jina}.py`, `app/rag/embedding/factory.py` | mock HTTP 测试证明请求体/响应解析不是 10 行空壳 |
| [x] | B2 | 建 embedding benchmark runner,不先改默认模型 | `app/rag/evaluation/embedding_bench/` | 同一 golden set 输出 Recall/MRR/latency/cost 对比;已由 `tests/test_embedding_bench_runner.py` 覆盖 |
| [ ] | B3 | language routing 加 trace/capability 校验,暂不默认开启 | `app/rag/embedding/factory.py`, retrieval trace | trace 显示选中的 provider/model;unsupported mapping 会 fallback |
| [x] | B4 | Matryoshka shortlist + rescore 只做实验开关 | `app/rag/embedding/matryoshka.py` | 已提供纯函数实验路径,暂不接入 retriever 默认链路;由 `tests/test_matryoshka_embedding.py` 覆盖 |
| [ ] | B5 | Shadow embedding 蓝绿迁移跑一次小样本 | `app/services/embedding_migration.py`, `app/services/indexer.py` | 1k 文档双写验证脚本输出一致性和失败明细 |

### B 批暂缓

| 状态 | 项 | 暂缓原因 |
|---|---|---|
| [ ] | 直接换默认 embedding 模型 | 必须先有 B2 benchmark;榜单不能代表客户语料 |
| [ ] | Bedrock 原生 SigV4 | 需要 boto3/签名链路,优先级低于 Voyage/Cohere/Jina |
| [ ] | Milvus SQ8 / binary 量化 | 运维风险大,需要真实向量规模和 recall 报告 |
| [ ] | Qwen3 / Conan 新 provider | 先补已有 provider 空壳和 benchmark,再扩新增模型 |
| [ ] | Cohere Embed v4 多模态默认接入 | 图表密集文档专项,需要多模态 golden set |

---

## 6. 第一阶段建议切片

第一阶段原定只做 8 个任务,其中 B2 已完成,当前剩余 7 个:

- [ ] A1: `cleaning_bench` golden set skeleton + 3 类 runner。
- [ ] A2: 数字保护型 Unicode normalization。
- [ ] A3: 中文 PII fixture 和 USCI/银行卡补齐。
- [ ] A4: 扩 legal/finance/industrial_control 噪声包并加测试。
- [ ] C1: Prompt Guard 规则包化。
- [ ] C2: KG extraction schema description/enum + prompt 模板化。
- [ ] C4: Citation correctness evaluator。
- [x] B2: Embedding benchmark runner skeleton。

不建议第一阶段做 B1 provider 真实接入,除非已有 API key / mock contract 已明确;否则容易陷入外部 SDK 和鉴权细节。

## 7. 验证命令建议

```bash
pytest tests/test_preprocessing_normalization.py tests/test_pii_presidio.py tests/test_industry_noise_patterns.py -q
pytest tests/test_prompt_guard.py tests/test_prompt_bundle_snapshot.py tests/test_kg_extraction_*.py -q
pytest tests/test_matryoshka_embedding.py tests/test_language_aware_embedding_routing.py tests/test_embedding_provider_wrappers.py -q
python -m ruff check app/rag/preprocessing app/parsing/preprocess app/rag/embedding app/rag/llm app/rag/kg/extraction app/rag/safety tests
```

第一阶段完成后再补一条端到端验证:

```bash
pytest tests/test_retrieval_ablation.py tests/test_hybrid_search_tuning.py tests/test_retrieval_trace_schema_v1.py -q
```

## 8. 完成定义

- [ ] 每个执行项都有对应测试或离线 runner。
- [ ] 没有默认启用新模型、新清洗强规则或新外部依赖。
- [ ] 清洗/Prompt/Embedding 的报告能输出可比较指标。
- [ ] RAG 检索 golden set 不下降;如果下降,必须回滚该规则或默认保持关闭。
- [ ] 计划里的暂缓项没有混入第一阶段实现。

## 9. 当前执行记录

- [x] 2026-05-13: B2 已落地为 `app/rag/evaluation/embedding_bench/`,验证命令: `pytest tests/test_embedding_bench_runner.py -q`。
- [x] 2026-05-13: B4 已落地为 `app/rag/embedding/matryoshka.py` 纯函数实验路径,验证命令: `pytest tests/test_matryoshka_embedding.py -q`。
- [ ] 下一步建议优先做 A1,因为 A2/A3/A4 的清洗规则改动必须先有 cleaning benchmark 兜底,否则容易误删真实业务文本。
