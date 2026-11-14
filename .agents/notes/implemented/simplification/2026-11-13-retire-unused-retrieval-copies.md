# Agent Note: 未使用的检索与管线副本退出

Status: implemented

## Problem

`app/types` 中三份请求模型与管线模型复制了 API 领域模型，却没有实际生产调用。RAG 和 evidence 的两份类型只被同样没有生产入口的旧 evidence 服务引用。两套相似实现的默认值、校验器、字段集和弃用功能已经不同，维护者难以判断应修改哪份；开发验证文档还把这些副本写成当前所有者。

## Decision

删除 types/document_pipeline.py、types/rag_config.py、types/evidence_retrieval.py，以及 services/evidence_retrieval.py。实际 HTTP／Dify／预览和 explain 继续调用 retrieval_requests.py，范围检查由 retrieval_scope.py 持有。请求模型继续由 API 九个领域包的实际定义模块持有，不把已验证的生产契约再迁移一次，也不保留旧路径转发。

引用核查覆盖 app、scripts、Alembic、配置、动态导入入口、公开导出和开发文档。旧 Python 测试直接导入这些副本，不算生产调用；用户已排除测试维护，不因冻结用例恢复重复实现。当前的 schema、字段默认值、校验顺序、字段集与检索预算没有通过这次删除改变。

只有一行空导出的 app/middleware 包也退出；实际中间件仍在 app/api/middleware。模型公共导出与完整 metadata 注册各有实际调用，分别保留 __init__.py 与 _all.py；后者的说明包含真实的应用启动用途。

## Alternatives considered

继续重构副本能让两套代码看起来一致，却仍没有生产使用者，后续仍会再次分叉。保留转发模块可以满足旧导入，但继续增加路径和兼容责任，违背此次只保留实际维护点的目标。

把生产 API 模型再迁入 types 可以尝试减少 API 依赖，但需要同步全部真实使用方并重新证明字段、schema、初始化与导出行为。当前任务已有明确工作的领域公开入口，本次清理只删除未使用实现，不为删除副本重做架构。

## Consequences

当前 app 减少五个无实际调用的模块，清单将退役与完成区分：删除路径不计成已完成源码，也不把存在重复实现的历史验证报告当作当前证据。旧直接导入测试会失效，测试文件保留原字节、未运行。历史开发验证记录保留原日志来源，文字说明指向当前所有者。

完整应用冷导入、OpenAPI、模型导出和 PostgreSQL DDL／索引／default／关系快照用于核对实际组装；这些操作不执行数据库、检索或模型。若将来需要对外发布独立 Python SDK，应明确公共包与支持窗口，不能根据这次内部删除推导已有客户端兼容承诺。
