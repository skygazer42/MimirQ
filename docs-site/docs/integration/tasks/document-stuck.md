---
sidebar_label: "文档卡在解析或索引"
sidebar_position: 3
---

# 业务剧本：文档卡在解析或索引

## 业务目标

在 **不猜测** 的前提下，尽快判断文档是 **正常排队**、**可恢复的失败** 还是 **需环境/配置修复**，并给出可交给研发或运维的 **证据链**（文档 id、状态、时间、相关请求）。

## 前置条件

- 已知 `document_id`（及关联的 `dataset_id`）。
- 具备读取文档详情、（如适用）解析/流水线相关接口的权限。
- 若为多租户部署，已按环境要求携带租户相关头或上下文（见 [tenant-headers](../patterns/tenant-headers)）。

## 建议步骤（业务顺序）

1. **读文档权威状态**  
   通过文档详情或列表接口查看 `status`、错误字段、更新时间；确认是卡住、失败还是重试中（[workflows.md — 场景 B](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)）。

2. **判断是否在进入解析/流水线**  
   若环境暴露 Parsing Workspace 或 Pipeline 类接口，按 OpenAPI 核对当前任务与阶段（[workflows.md — 场景 C](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)）。

3. **环境与健康**  
   查看 Health、Meta、Observability 等路径是否报告依赖不可用（解析器、队列、对象存储等）（[workflows.md — 场景 J](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)）。

4. **缩小范围**  
   - 仅单文档失败 → 优先怀疑 **格式/内容/大小** 或该文档任务日志。  
   - 批量卡住 → 优先怀疑 **Worker/队列/下游配额**。

5. **输出简报**  
   整理：环境、数据集、文档 id、首次上传时间、当前状态、已尝试动作、相关 trace/request id。

## 验收标准

| 项 | 说明 |
| --- | --- |
| 状态明确 | 能用接口字段说明当前阶段，而非仅「页面一直转圈」 |
| 有下一步 | 要么已恢复，要么有明确升级路径（配置/扩容/缺陷） |
| 可复现信息 | 第三方无需登录你的脑内上下文即可接手 |

## 常见异常

| 现象 | 可能原因 | 建议动作 |
| --- | --- | --- |
| 解析器相关 5xx | 依赖未启动、镜像/版本不匹配 | 对照部署文档与 [dependencies 指南](https://github.com/skygazer42/MimirQ/blob/main/docs/guides/dependencies.md) |
| 长时间无状态变化 | Worker 未消费、死信队列 | 查 Observability / 运维 Runbook |
| 仅部分格式失败 | 解析器插件或驱动缺失 | 换格式试传以二分定位 |

## 深入阅读

- [新租户首日上线](./go-live-tenant)（确认基础路径无误）
- [知识库可对用户问答](./knowledge-base-qa)（处理完成后检索侧验收）
- [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
- [API 冒烟说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_SMOKE.md)
