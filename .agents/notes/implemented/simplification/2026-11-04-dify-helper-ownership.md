# Agent Note: Dify 纯规则使用同一份实现

Status: implemented

## Problem

Dify 的 API 辅助包和服务包各自保存记录去重、评分、锚点和内容压缩规则。调用方难以判断规则归属，修改一份后也容易遗漏另一份。

## Decision

纯规则由 `app/services/dify_integration/` 中现有的 `common`、`scoring`、`anchor_strength`、`compaction` 和 `records` 模块持有。API 和外部会话适配器直接导入这些实现；`integrations_dify` 原有名称继续指向同一业务规则。与这些规则共用的常量也使用服务包的定义。

客户端 IP 提取仍由 HTTP 适配器处理。`external_api._api()` 的既有回调绑定保留。原始引用、元数据和数据库行的解析仍在原来的输入边界；已声明为 `UUID` 的内部 fallback 和整数、布尔配置直接按其类型使用。

## Alternatives considered

保留两份辅助实现可以减少本次迁移的引用变化，但同一规则仍需两次维护。直接切换整条检索服务虽然能进一步缩小 API 模块，却同时涉及请求上下文、缓存、限流、追踪和会话持久化；这些职责需要各自核对，本次只合并已确认等价的纯规则。

## Consequences

五个重复 API 辅助模块退出，纯规则及共享常量各有一个维护位置。现有路由、检索阶段和 HTTP 错误转换保持原来的实现。

验证使用源码、AST、引用核对和 Ruff；按用户要求不运行 Python 测试。运行时检索、模型和数据库行为仍未验证。
