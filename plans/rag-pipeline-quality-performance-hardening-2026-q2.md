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

## 必做项

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

- [ ] 服务器长跑留存基线
  - `smoke`：3 份入库、12 次检索、4 次聊天
  - `server`：20 份入库、80 次检索、20 次聊天
  - `full`：100 份入库、300 次检索、60 次聊天
  - 每次结果保存在 `artifacts/rag-pipeline-quality-suite/`

- [ ] 解析器性能基线固化
  - core：basic、markitdown、deepdoc、docling、mineru
  - heavy：magicpdf、paddle_vl、olmocr
  - external：marker、etl4llm、textin
  - heavy/external 不作为默认失败条件，但必须记录耗时、错误、输出字符数和空 Markdown 风险

- [ ] KG 抽取规模控制
  - 入库默认只抽重要片段，不按全文无限抽 events
  - 每文档 KG 事件数、实体数、图谱边数要有预算
  - 查询阶段默认用 KG 作为 RAG 的辅助召回源，不让图谱遍历成为主路径瓶颈

- [ ] 治理和切块真实有效性回归
  - Markdown 噪声清洗不破坏表格、代码块、标题层级
  - PDF/HTML/Office/纯文本分别覆盖至少一个 fixture
  - 每个切块策略至少验证：块数、平均长度、覆盖率、重叠浪费、空块数

- [ ] Prompt 与答案质量门禁
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

## 通过标准

- [ ] API smoke 无失败
- [ ] production readiness 无失败，且聊天答案有引用或明确降级原因
- [ ] chunking strategy matrix 的 failures 为空
- [x] RAG load test 错误率为 0；server profile 下检索 P95 和聊天 P95 进入报告
- [ ] KG regression gate 达到 Hit/MRR/Recall 阈值
- [ ] answer quality gate 通过当前阈值
- [ ] parser live matrix 不出现空 Markdown；heavy parser 超时只记 warning，不阻断 core 发布

## 当前风险

- [ ] OLMOCR 属于重解析路径，单文档可能分钟级，不应进入默认自动解析策略
- [ ] 外部解析器依赖容器网络、模型缓存和凭证，必须把失败原因写入报告
- [ ] KG 全量抽取会随文档数量非线性变慢，默认需要事件预算和重要片段采样
- [ ] 端到端质量门禁需要稳定测试集，不能只依赖临时上传样本
