# RAG Python 逐文件审查

状态：**RAG 规范审查已完成，以下保留该轮验收快照**。

后续运行问题修复已更新部分源码；原有指纹不再代表这些文件的最新字节。增量修改、验证与限制见 [Ponytail 审计修复记录](ponytail-audit-fixes.md)，没有将原阶段的静态审查升级为真实服务运行验收。

原始范围 666 个 Python 文件；当前源码与审查记录一致的文件 666 个；已保存 7615 条具名声明判断。

完整文件、类、函数和嵌套声明记录保存在 [覆盖清单](rag-guidelines-progress.json)。每个文件记录源码指纹、处理结论和验证来源；删除、迁移及后续增量分别登记。

| 模块 | 原始文件 | 当前已审 |
| --- | ---: | ---: |
| `agents` | 14 | 14 |
| `embedding` | 15 | 15 |
| `evaluation` | 89 | 89 |
| `feedback_loop` | 4 | 4 |
| `industry_rules` | 9 | 9 |
| `ingestion` | 2 | 2 |
| `ingestion/chunking` | 100 | 100 |
| `ingestion/governance` | 37 | 37 |
| `ingestion/indexing` | 14 | 14 |
| `ingestion/parsing` | 125 | 125 |
| `kg` | 52 | 52 |
| `llm` | 21 | 21 |
| `package` | 1 | 1 |
| `pipeline_plugins` | 8 | 8 |
| `policy` | 14 | 14 |
| `retrieval` | 4 | 4 |
| `retrieval/cache` | 3 | 3 |
| `retrieval/configuration` | 6 | 6 |
| `retrieval/evidence` | 9 | 9 |
| `retrieval/expansion` | 6 | 6 |
| `retrieval/planning` | 14 | 14 |
| `retrieval/ranking` | 14 | 14 |
| `retrieval/recall` | 15 | 15 |
| `retrieval/reranking` | 12 | 12 |
| `retrieval/stages` | 14 | 14 |
| `runtime` | 28 | 28 |
| `safety` | 14 | 14 |
| `tracing` | 6 | 6 |
| `workflows` | 16 | 16 |

本轮实际整理包括：业务清理入口改为直接模块函数；移除重复检索状态搬运；在模型与 JSON 边界明确数据契约；保留真实零值；区分正常无结果、未知测量和失败；集中表格行扫描；按实际 SDK 协议管理客户端、任务、文件与图片生命周期。

格式调整另有 AST 等价记录。涉及取消、异常、来源身份、数据库作用域及算法边界的整理，使用各批次的有限源代码端口和内存样例验证。

验证范围：Ruff 规则、Ruff 格式、Python 3.11 语法与内存编译、源码导入绑定、必要的守护导入与隔离行为样例。完整结果以当前源码指纹对应的验收记录为准。

按本轮约定，未运行 pytest、真实模型、业务 HTTP、数据库、Docker 或应用 lifespan。本地缺少 NLTK 与词典资源；分词功能实际启用时需要这些部署依赖。真实 SDK 和模型质量的集成验证不在隔离样例的证明范围内。

最终验收：661 个当前 Python 文件的 Ruff 规则、格式和 Python 3.11 语法／内存编译通过；3,072 项显式 RAG 导入绑定及 78 项实际懒加载导出通过。原始 666 文件／7,475 声明及当前新增、迁移、删除声明均已闭合，无待办增量。完整结果见 [验证记录](rag-guidelines-verification.json)。
