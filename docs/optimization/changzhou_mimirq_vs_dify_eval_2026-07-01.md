# 常州政务知识库 MimirQ vs Dify 客观评估

生成时间：2026-07-01

## 评估口径

本次评估以原文档为唯一事实标准，不使用 LLM 作为裁判。

- 原始数据：`/data/temp50/20260522政务服务智能客服知识`
- 题集：`/tmp/changzhou_composite_100_cases.json`
- 题量：100 道复合题
- 题型：事项复合题 61 道，QA 多事实合并题 30 道，"一件事"指南题 9 道
- 原文审核：810 个 evidence clause required term 全部能在原始 source_file 中找到，缺失 0 个
- MimirQ direct v15：`/tmp/changzhou_composite_100_mimirq_direct_current_v15_top5_run.json`
- Dify 外接 MimirQ 3c1c8 v15 trace：`/tmp/changzhou_composite_100_dify_3c1c8_current_v15_trace_top5_run.json`
- Dify 外接 MimirQ a3c v15 trace：`/tmp/changzhou_composite_100_dify_a3c_current_v15_trace_top5_run.json`
- Dify 原生 a398 v15 trace：`/tmp/changzhou_composite_100_dify_native_a398_current_v15_trace_top5_run.json`
- 统一评分报告：`/tmp/changzhou_composite_100_current_v15_vs_current_dify_quality_report.json`

评分指标：

- Evidence coverage：top5 证据是否覆盖原文档关键条款。
- Subquestion coverage：复合问题每个子问题是否被证据覆盖。
- Wrong evidence rate：top5 中与原文关键条款无关的证据比例。
- Retrieval pass rate：是否达到每题设置的最低覆盖率和最高噪声阈值。
- Latency：接口或 trace 记录的端到端耗时。

## 总体结果

| 系统 | 成功率 | 通过率 | 证据覆盖 | 子问题覆盖 | 错证据率 | 平均延迟 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dify 外接 MimirQ 3c1c8 v15 trace top5 | 100/100 | 0.980 | 0.990 | 0.990 | 0.030 | 13037.9ms |
| MimirQ direct v15 top5 | 100/100 | 0.980 | 0.990 | 0.990 | 0.0325 | 4959.6ms |
| Dify 外接 MimirQ a3c v15 trace top5 | 100/100 | 0.980 | 0.990 | 0.990 | 0.0325 | 12694.4ms |
| Dify 原生 a398 v15 trace top5 | 96/100 | 0.420 | 0.813 | 0.813 | 0.708 | 12658.2ms |

Pairwise：

- Dify 外接 MimirQ 3c1c8 与 MimirQ direct：0 胜 / 0 负 / 100 平。
- Dify 外接 MimirQ a3c 与 MimirQ direct：0 胜 / 0 负 / 100 平。
- MimirQ direct 对 Dify 原生：22 胜 / 0 负 / 78 平。
- 两条 Dify 外接 MimirQ 对 Dify 原生：均为 22 胜 / 0 负 / 78 平。

## 客观判断

如果只比较“知识库召回是否精准覆盖原文答案”，当前 MimirQ direct 和 Dify 外接 MimirQ 已经打平，并明显超过 Dify 原生。Dify 原生主要问题不是完全不召回，而是 top5 噪声高、复合问题证据不完整，并且本次有 4 题稳定失败于 `bge-reranker-large credentials is not initialized`。

更准确的表述是：

- MimirQ 的知识库能力在结构化事项知识、QA 多事实聚合、一件事章节组合、低噪声和稳定性上领先 Dify 原生。
- Dify 外接 MimirQ 当前 trace 已经吃到 MimirQ 的检索结果，所以召回指标与 MimirQ direct 一致。
- Dify 外接路径平均延迟约 12.7-13.0s，主要来自 Dify workflow/LLM 生成链路；MimirQ direct retrieval 平均约 5.0s。
- 如果最终答案仍感觉不好，优先排查 Dify workflow 的提示词、答案节点、上下文拼装和输出约束，而不是先怀疑 MimirQ direct 召回。

## Reranker 与性能结论

当前代码保持“召回阶段 reranker 必须走”的原则：

- mixed intent 检索仍按 top5 限制候选，避免多子查询放大延迟。
- primary/subquery/expansion 的 RAG 检索都会显式按配置启用 reranker。
- 最终 rerank 只负责跨子查询合并后的二次排序，不替代召回阶段 reranker。

实测：

- 正常复合 direct 100 题：0 错误，平均 4959.6ms，p95 9773.0ms。
- 强制绕过 metadata preflight 走 RAG 的冷启动样本：74.4s，日志显示触发 `BM25 lazy-built 30000 chunks`。
- 同一强制 RAG 样本 warm 后：109ms，说明 74s 主要是 BM25 冷启动，不是 reranker 必然慢。

## 主要问题

1. 旧评估里 Dify 外接 MimirQ 只有约 0.50 的原因是旧 workflow/旧 trace 没有反映当前 direct 检索能力；当前 trace 已与 direct 打平。
2. Dify 原生 top5 wrong evidence rate 约 0.708，很多题能召回同主题文件，但答案条款不完整或夹杂非目标块。
3. Dify 原生有 4 个稳定失败样本，错误为 `bge-reranker-large credentials is not initialized`，这是 Dify 原生 app 配置问题。
4. MimirQ direct 的主要性能风险是冷启动 BM25 lazy build；warm 后 RAG 路径明显变快。
5. 业务 schema、事项字段、复合问题 slot 仍应放在插件 retrieval policy 内，平台只保留通用多路召回、metadata anchor、rerank、合并和排序能力。

## 下一步优化方向

优先做通用能力，不做业务硬编码：

1. 把 100 题复合评估纳入回归门禁，至少固定 retrieval pass、coverage、wrong evidence rate 和 p95 latency。
2. 对 BM25 冷启动做可控预热或持久化，避免首个强制 RAG 请求触发 30k chunks lazy build。
3. 继续保留插件内 schema/slot/policy，平台只做通用组合与排序。
4. 对 Dify workflow 生成层单独评估，区分“召回证据正确但答案漏写”和“召回证据本身错误”。
