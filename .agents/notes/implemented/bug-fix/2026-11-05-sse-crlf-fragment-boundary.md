# Agent Note: SSE 的 CRLF 归一化跨越网络分块

Status: implemented

## Problem

`sse-reader` 使用流式 UTF-8 解码，读取边界可以落在 CR 与 LF 之间。`sse` 原先只对新 chunk 替换 CRLF，因此上一块末尾的 CR 留在 buffer 中，合法的空行分隔符无法变成两个连续 LF。真实 `chatApi.streamChat` 在每字节读取 CRLF 事件时没有交付 token 与 done；相同内容的 LF 对照正常。

## Decision

现有 parser 在合并旧 buffer 与新 chunk 后归一化 CRLF，再按原来的空行与 `data:` 规则读取事件。UTF-8 decoder、回调异常处理、reset、认证与请求生命周期继续由原所有者负责。这里没有新 parser、重试或普通请求回退。

## Alternatives considered

保留每个 chunk 独立替换只需更少 buffer 扫描，但无法处理合法的网络边界。增加待处理 CR 状态也能解决问题，却给现有短函数增加了额外状态；原 buffer 已经保存未完成事件，合并后归一化足以修复本次复现。

## Consequences

网络分块不再丢失 CRLF 事件。归一化会扫描当前未完成事件的 buffer，原有字符串拼接本来也需要复制它；此处没有引入额外持久化或缓冲层。

回归使用真实 ReadableStream、Response、chat API 与 SSE reader，将包含中文的 token 和 done 按 UTF-8 单字节交付。旧实现的 CRLF 用例失败、LF 对照通过；修复后的边界与 SAML 组合回归共 14 项通过。证据保存在本批报告引用的 red/green JSON 中。

检索命中的[聊天 Hook 的会话与流式结果归属](2026-11-04-chat-hook-stream-ownership.md)持有 UI 请求发布、停止和回退规则，[OIDC 刷新结果的会话归属](2026-11-04-auth-refresh-session-ownership.md)持有认证版本。它们与本次传输文本分隔符问题相邻，本记录消费既有行为，不替代原决定；没有待处理的同主题 proposed 或 rejected 记录。
