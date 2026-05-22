# RAG Pipeline Quality and Performance Hardening Plan (2026 Q2)

## 目标

把解析、治理、切块、入库、KG、检索、答案生成和前端联调从零散手工验证收敛成可重复套件。结论必须来自真实后端、真实数据集、真实解析器和真实模型调用；mock 只允许用于单元测试。

## 已验证基线

- [x] Docker API、PostgreSQL、Milvus、Redis、MinIO readiness 可用
- [x] 多格式生产就绪链路已跑通：文档入库、治理、切块、KG、检索、聊天引用
- [x] 解析器已做真实预览测速：basic、markitdown、deepdoc、docling、mineru、marker、etl4llm、paddle_vl、textin、magicpdf、olmocr
- [x] 切块策略矩阵在容器内跑通，失败列表为空
- [x] KG 服务层已有召回预算和低置信度轻量兜底，避免少量文档把图谱问答拖慢
- [x] LLM 默认配置可以真实调用，避免只看 masked settings

## 本次已交付

- [x] 统一质量套件入口：`scripts/rag_pipeline_quality_suite.py`
  - 默认只输出计划，不误跑长任务
  - `--run --profile smoke` 用于本机快速验收
  - `--run --profile server` 用于顶配服务器日常联调
  - `--run --profile full` 用于发布前长跑

- [x] 生产就绪链路支持可配置 LLM 探测超时
  - 之前固定 2 秒容易把真实云模型的偶发慢响应误判为不可用
  - 新参数：`--llm-probe-timeout`

- [x] RAG load test 支持错误率和 P95 门禁
  - 入库、检索、聊天任一阶段出现错误都会返回非零
  - `--max-ingest-p95-ms`、`--max-retrieve-p95-ms`、`--max-chat-p95-ms` 可按机器配置启用

## 覆盖矩阵

| 领域 | 当前覆盖 | 真实证据入口 | 还缺什么 |
| --- | --- | --- | --- |
| 解析 | 多格式入库链路、指定解析器 live preview、解析 golden fixtures | `scripts/production_readiness_chain.py`、`scripts/api_smoke.py --live-parser-backends ...`、`tests/fixtures/parsing_golden_broader/` | 服务器周期性 parser matrix 历史趋势 |
| 切块 | 内置策略矩阵、fixture 回归、RAG load 入库后分块量 | `scripts/chunking_strategy_matrix.py`、`tests/test_chunking_regression_fixtures.py`、`tests/test_chunk_strategy_matrix.py` | 真实业务数据上的 P95 chunk 数和覆盖率基线 |
| 治理 | 入库 pipeline 默认治理、Profile/规则包单测、生产链路检查 parsed/chunk 结果 | `scripts/production_readiness_chain.py`、`tests/test_builtin_governance_profiles.py`、`tests/test_builtin_governance_profile_html_web_rule_packs.py` | 业务语料上的治理前后召回对照 |
| 提示词 | 内置 prompt library 单测、默认聊天引用/降级门禁、答案质量门禁入口 | `tests/test_builtin_prompt_library.py`、`scripts/production_readiness_chain.py`、`scripts/answer_quality_gate.py` | 固定评测集的 Judge/答案阈值资产 |
| 知识库/RAG | 真实数据集创建、上传、检索、聊天、load test 错误率/P95 门禁 | `scripts/production_readiness_chain.py`、`scripts/rag_e2e_load_test.py`、`scripts/rag_pipeline_quality_suite.py` | server/full profile 的持续基线报告 |
| KG/图谱 | KG 抽取、搜索 3 秒门禁、事件/实体预算配置、KG regression gate 入口 | `scripts/production_readiness_chain.py`、`scripts/kg_search_regression_gate.py`、`app/core/config.py` | 稳定 KG cases/thresholds 资产 |

## 后续长跑与资产化任务

- [ ] 服务器长跑留存基线
  - `smoke`：3 份入库、12 次检索、4 次聊天
  - `server`：20 份入库、80 次检索、20 次聊天
  - `full`：100 份入库、300 次检索、60 次聊天
  - 每次结果保存在 `artifacts/rag-pipeline-quality-suite/`

- [ ] 解析器性能基线固化为趋势报告
  - core：basic、markitdown、deepdoc、docling、mineru
  - heavy：magicpdf、paddle_vl、olmocr
  - external：marker、etl4llm、textin
  - heavy/external 不作为默认失败条件，但必须记录耗时、错误、输出字符数和空 Markdown 风险

- [ ] 治理和切块真实有效性回归集
  - Markdown 噪声清洗不破坏表格、代码块、标题层级
  - PDF/HTML/Office/纯文本分别覆盖至少一个 fixture
  - 每个切块策略至少验证：块数、平均长度、覆盖率、重叠浪费、空块数

- [ ] Prompt 与答案质量门禁资产
  - 主答案 Prompt：必须输出引用、拒绝无证据扩展
  - KG 抽取 Prompt：必须受事件预算约束
  - Judge Prompt：只用于评测，不进入线上回答路径
  - 测试集生成 Prompt：只生成候选样本，需人工或规则审核后入库

## 验收命令

```bash
python scripts/rag_pipeline_quality_suite.py
```

输出套件计划，不访问网络。

```bash
python scripts/rag_pipeline_quality_suite.py --run --profile smoke
```

本机最小真实联调。

```bash
python scripts/rag_pipeline_quality_suite.py --run --profile server \
  --parser-fixture /path/to/sample.pdf \
  --parser-backends basic,markitdown,deepdoc,docling,mineru,magicpdf,paddle_vl,textin
```

服务器解析器和 RAG 联调。

```bash
python scripts/rag_pipeline_quality_suite.py --run --profile full \
  --kg-cases artifacts/kg/cases.json \
  --kg-thresholds artifacts/kg/thresholds.json \
  --answer-input artifacts/rag/summary.json \
  --answer-thresholds artifacts/rag/answer-thresholds.json
```

发布前完整门禁。

## 套件通过标准

- [x] API smoke 被纳入统一套件
- [x] Production readiness 被纳入统一套件，要求聊天答案有引用或明确降级原因
- [x] Chunking strategy matrix 被纳入统一套件，failures 非空时失败
- [x] RAG load test 错误率为 0；可按机器启用 P95 阈值
- [x] Parser live matrix 支持按需启用；未提供 fixture 时默认跳过，不阻断本机 smoke
- [x] KG regression gate 支持按需启用；未提供 cases/thresholds 时默认跳过
- [x] Answer quality gate 支持按需启用；未提供 input/thresholds 时默认跳过

## 当前风险

- OLMOCR 属于重解析路径，单文档可能分钟级，不应进入默认自动解析策略
- 外部解析器依赖容器网络、模型缓存和凭证，必须把失败原因写入报告
- KG 全量抽取会随文档数量非线性变慢，默认需要事件预算和重要片段采样
- 端到端质量门禁需要稳定测试集，不能只依赖临时上传样本
