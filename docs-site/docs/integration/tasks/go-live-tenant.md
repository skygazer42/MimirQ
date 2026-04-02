---
sidebar_label: "新租户首日上线"
sidebar_position: 1
---

# 业务剧本：新租户首日上线

## 业务目标

在 **第一个工作日** 内达成可演示结果：**有人能登录**、**至少一个数据集**、**能上传一份测试文档并看到处理进度**，便于向业务方证明环境可用。

## 前置条件

- 已部署可访问的 MimirQ 实例（或联调环境），Base URL 已知。
- 具备 **管理员或具备建库权限** 的账号（或可按环境文档完成首轮注册）。
- 已准备一份 **小体积、无敏感** 的测试文件（PDF/Office/纯文本均可，以环境支持的格式为准）。

## 建议步骤（业务顺序）

1. **身份与会话**  
   完成注册或登录，拿到 `access_token`；用「当前用户」接口确认会话有效。  
   （调用顺序见仓库 [workflows.md — 场景 A](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)。）

2. **创建数据集**  
   创建数据集并保存返回的 `dataset_id`，作为后续所有文档与配置的挂载点。

3. **上传测试文档**  
   将测试文件关联到该数据集；记录返回的 `document_id`。

4. **确认处理可见**  
   通过文档详情或列表轮询 `status`，直到进入「可继续下一步」的完成态，或明确停留在某中间态（便于次日排障）。  
   （入库主路径见 [workflows.md — 场景 B](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)。）

5. **（可选）Web 验收**  
   在浏览器打开数据集与文档相关页面，确认列表与状态与 API 一致。

## 验收标准

| 项 | 说明 |
| --- | --- |
| 登录与会话 | 能稳定拿到 token，且 me 接口返回预期用户 |
| 数据集 | 至少一个 `dataset_id` 可用于后续上传 |
| 文档 | 上传成功返回 `document_id`，且状态可查询 |
| 可追溯 | 团队内能复述「用的哪个环境、哪个数据集、哪份文件」 |

## 常见异常

| 现象 | 可能原因 | 建议动作 |
| --- | --- | --- |
| 401 / 403 | token 过期、权限不足、租户头缺失 | 对照 [集成模式：认证与租户](../patterns/auth-modes) 与 OpenAPI 要求 |
| 上传失败 4xx | 格式不支持、体积超限、multipart 边界错误 | 见 [multipart 上传](../patterns/multipart-upload) |
| 文档长期「处理中」 | 解析器未就绪、队列积压、单文档失败 | 转 [业务剧本：文档卡在解析或索引](./document-stuck) |

## 深入阅读

- [知识库可对用户问答](./knowledge-base-qa)（从「能传」到「能答」）
- [API 调用流程（场景化）](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)
- [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
