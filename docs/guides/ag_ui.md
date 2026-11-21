# AG-UI 聊天接口

Ragvia 的 `POST /api/v1/chat/stream` 使用 AG-UI 1.0。Python 使用 `ag-ui-protocol==1.0.0`，前端使用 `@ag-ui/core@1.0.4` 的官方类型与运行时 schema。

## 请求

鉴权和租户 Header 沿用现有 API。`threadId` 使用小写、带连字符的规范会话 UUID，新会话由调用方生成，后续轮次继续使用同一个值；`runId` 每次运行生成新值。已有会话仍校验租户、账户和文档权限。

```json
{
  "threadId": "10000000-0000-4000-8000-000000000001",
  "runId": "20000000-0000-4000-8000-000000000001",
  "messages": [
    {
      "id": "30000000-0000-4000-8000-000000000001",
      "role": "user",
      "content": "这份文档的主要内容是什么？"
    }
  ],
  "state": {},
  "tools": [],
  "context": [],
  "forwardedProps": {
    "dataset_id": "40000000-0000-4000-8000-000000000001",
    "rag_config": { "retrieval_mode": "hybrid" }
  }
}
```

`messages` 由既有 `user`、`assistant` 纯文本历史和末尾的本次 `user` 消息组成，保留原有消息 ID。RAG 配置、文档范围、提示词和记忆开关通过 `forwardedProps` 传递；不能在那里覆盖消息、会话、租户、账户身份或旧的 `stream` 开关。`document_ids` 仍可独立指定有权限的文档范围。

当前支持文本聊天及服务端已经注册的工具。非文本内容、其它消息角色、客户端提供的工具、非空共享状态／上下文及中断恢复输入会明确返回 422，避免将尚未实现的能力当作执行成功。非流式 `/api/v1/chat` 的请求格式保持原有合同。

## 响应

响应为 SSE，数据由官方 `EventEncoder` 编码。一次运行先发 `RUN_STARTED`，正常结束发 `RUN_FINISHED`，失败发 `RUN_ERROR`。文本使用 `TEXT_MESSAGE_START`、`TEXT_MESSAGE_CONTENT`、`TEXT_MESSAGE_END`，增量位于 `delta`，以 `messageId` 关联。

服务端工具使用真实且唯一的 `toolCallId`，依次发送 `TOOL_CALL_START`、`TOOL_CALL_ARGS`、`TOOL_CALL_END` 和 `TOOL_CALL_RESULT`。`TOOL_CALL_END` 表示参数传输结束，执行结果由 `TOOL_CALL_RESULT` 表达；当前结果内容保留既有公开的成功／错误摘要，不额外暴露内部工具返回数据。

引用和既有进度通过 `CUSTOM` 保留：`name` 为 `ragvia.citations`、`ragvia.event`、`ragvia.route` 等领域名称，`value` 为对应数据。`metadata` 携带 `requestId`、`threadId`、`runId` 和 `assistantMessageId`；HTTP 请求追踪 ID 与 Agent 运行 ID 分开使用。

完成事件等待实际流收尾，包括已定义的持久化步骤。发生错误、未完成断流或取消时不会补造成功。客户端按标准事件及运行／消息身份消费数据，旧的 `token`／`done` 网络事件格式退出。

`RUN_FINISHED` 的 `outcome` 缺省或为 `success` 才表示完成回答；`cancelled` 保留为停止状态，`interrupt` 明确提示当前聊天不支持继续该中断，二者都不会提交普通成功回答。标准可选的 `metadata` 和 `result` 可以省略，项目扩展不成为消费合法标准流的前提。

## 验证

`scripts/api_smoke.py` 使用标准输入，并读取到 `RUN_FINISHED` 才判定流成功；`RUN_ERROR`、标识不匹配、重复生命周期和无终止事件的断流均判为失败。该脚本会操作真实 API，仅在明确授权的测试环境中运行。

协议参考：[官方事件规范](https://docs.ag-ui.com/concepts/events)、[官方服务端示例](https://docs.ag-ui.com/quickstart/server)。
