# Agent Note: 外部会话导入直接使用请求模型

Status: implemented

## Problem

外部会话的请求模型已清理标题、消息 ID、正文和元数据，服务再次执行相同转换，并为内部函数临时拼装四字段字典。会话查找返回对象和重复的新建标志，消息保存也先构造固定字典再解包成 ORM 对象，主流程的实际输入难以追踪。

## Decision

导入服务直接使用 ExternalConversationIngestRequest 和 ExternalConversationMessageIn 的已校验字段。元数据组装接收实际消息对象与已经采集的引用候选，保留原 conversation／message／citations 副本和消息级 source_run_id 优先级。原始嵌套引用仍由原来的 JSON、字面量和 UUID／内容／评分适配器处理。

会话查询只返回 Conversation 或 None，调用方在真正创建时维护 created_conversation，不再同时维护 should_create。标题取值直接由请求模型负责；账户 ID 仍按原规则去空白。单列 SQL 查询按实际行形状解包，租户、所有者、来源和外部会话 ID 条件保持。

消息直接通过 Message 的明确字段构造，token_count 的真实可空与显式零值策略保留。插入过消息的分支使用已生成的最后消息时间更新会话；起始时间、原始创建时间、微秒递增和跳过重复消息的顺序保持。请求 ID 在 API 入口归一化一次，异步深拷贝、线程池、Session 关闭与失败日志保持。

公开导入函数仍允许省略审计元信息，现有直接调用实际使用了这项契约；不按 None 数量删除这些默认值。请求／响应 schema、审计字段、提交顺序及同步／异步响应不变。

## Alternatives considered

- 继续传递临时消息字典：可维持旧签名，但字段已有请求模型所有者，不必再用 get 和空容器推测是否存在。
- 用新上下文类承接全部导入状态：能缩短参数列表，但消息模型和现有数据库实体已经表达所需职责，本批不增加管理器或新状态类型。

## Consequences

业务流程直接展示输入模型和保存字段，少一个标题转发函数及两份一次性字典。输入保证依赖原 Pydantic 校验，新增绕过模型的调用者必须明确自己的校验职责。

既有 [Dify 纯规则归属](2026-11-04-dify-helper-ownership.md)只持有相邻引用规则，[文档服务归属](2026-11-05-document-service-ownership.md)继续持有其他文档与解析边界；本篇不替代它们。没有同主题未决提案需要归档或撤销。

证据位于 E:/MimirQ/.superpowers/external-ingest-model-inputs-20261107/。完整模块 AST 对照覆盖私有返回值、模型传递、直接构造及已校验字段取值；原引用解析、时间策略、异步 worker、schema、授权和测试源码保持。Ruff、格式、语法与笔记门禁用于静态验收，未运行 Python 测试、导入业务、线程池、HTTP 或数据库。

提交前尝试 autoreview，预检因本机缺少 TruffleHog 而结束，没有调用第二模型。该技能禁止自动安装依赖；本批提交依据上述源码复核与静态证据，不声称通过自动模型审查。
