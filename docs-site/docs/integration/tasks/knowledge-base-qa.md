---
sidebar_label: "知识库可对用户问答"
sidebar_position: 2
---

# 业务剧本：知识库可对用户问答

## 业务目标

用户在前端或通过 API **提问时能命中已入库内容**，回答有据可查（或至少能解释「为何未命中」），满足「知识库可用」的验收口径，而非仅「文件已上传」。

## 前置条件

- 已完成 [新租户首日上线](./go-live-tenant) 或等价步骤：有效会话、`dataset_id`、至少一份 **处理完成** 的文档。
- 明确本环境 **检索 / RAG** 是否启用及默认策略（以 OpenAPI 与部署说明为准）。

## 建议步骤（业务顺序）

1. **确认文档在「可检索」路径上**  
   文档状态为完成态；若环境依赖解析、切块、流水线，确认相关步骤无失败（详见 [workflows.md — 场景 B、C](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)）。

2. **检索配置（如有档案概念）**  
   按环境创建或选用检索 profile，必要时用 explain / config-hash 类接口验证配置与预期一致（[workflows.md — 场景 D](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)）。

3. **试跑 RAG 或 Chat**  
   使用与业务相同的数据集上下文发起一次非流式请求，确认返回结构符合集成预期；需要调试时再打开流式或 RAGViz 相关路径。

4. **验收问答**  
   用文档中 **可唯一命中的短语** 提问，记录请求 id 或 trace（若环境提供），便于与运维/研发对齐。

## 验收标准

| 项 | 说明 |
| --- | --- |
| 内容可检索 | 针对已知片段的提问能返回相关片段或合理引用 |
| 配置可重复 | 同一数据集上可复现相同检索/RAG 行为（配置未静默漂移） |
| 可解释未命中 | 能说明是内容未进索引、过滤过严、还是模型/策略问题 |

## 常见异常

| 现象 | 可能原因 | 建议动作 |
| --- | --- | --- |
| 回答与文档无关 | 数据集/会话错配、profile 指向错误集合 | 核对 `dataset_id` 与检索参数 |
| 始终空结果 | 切块未生成、索引滞后、权限过滤 | 查文档状态与流水线；必要时 [文档卡住](./document-stuck) |
| 延迟极高 | 嵌入或向量服务慢、并发过高 | 对照 [可观测性与请求关联](../patterns/observability-requests) |

## 深入阅读

- [检索示例（仓库）](https://github.com/skygazer42/MimirQ/blob/main/docs/examples/retrieval_api_examples.md)
- [workflows.md — 场景 D、E](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)
- [SSE 与流式](../patterns/sse-streaming)（若前端使用流式）
