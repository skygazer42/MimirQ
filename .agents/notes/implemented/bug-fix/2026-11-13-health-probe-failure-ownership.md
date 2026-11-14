# Agent Note: 健康诊断持有启用判定与探针失败

Status: implemented

## Problem

对象存储是否启用由区域配置和实际客户端共同决定，判定过程本身可能在导入 SDK 或构造客户端时失败。若 API 在健康诊断之外先做判定，异常不会成为依赖不可就绪的诊断。数据库 schema 查询失败若被解释成空 revision，也会丢失真正原因。

## Decision

`check_object_storage` 只接受两个必填回调：判定启用与执行探针。两个动作在同一个健康检查错误入口执行；API 的具名启用回调继续采用 MINIO_ENABLED 或实际 document_object_storage_enabled 的短路规则，保留区域 profile、文档存储和旧 MinIO 资产的选择。

未启用返回 disabled、enabled=False 和成功；启用后检查失败返回 disconnected、enabled=True 和失败。若启用判定本身失败，返回 disconnected 和失败，省略尚未得出的 enabled。合法探针结果原样交付；必填 status 缺失等内部数据错误继续显式失败。没有真实调用的 mode、Settings 默认判定和 override 选择退出该内部函数，生产调用方一起迁移。

其他健康检查直接消费实际 Settings 和客户端回调。数据库 schema 查询失败返回 schema_check_failed；连接或 Session 关闭的 SQLAlchemyError 仍判为不可就绪。正常空 revision 与查询失败分别表达，合法零条集合数仍是已连接。迁移拒绝非法默认租户，已支持的逐语句 SQL 降级记录警告，原 SQL 和事务策略保持。

## Alternatives considered

在 API 和核心探针各加一段异常转换可以保留原签名，但同一依赖的失败诊断会有两个维护点。只看顶层 OBJECT_STORAGE 开关能避免构造客户端，却会漏掉区域 profile 的真实启用结果。将启用与探针作为必填回调交给一个入口，保留实际配置所有者。

使用 None 哨兵跟踪尚未确定的 enabled 也能正确表达未知；诊断字典只在取得启用结果后写入该字段，不需要额外状态和分支。迁移改为整体强事务可以更早失败，但与现有逐条容错策略不同，本决定仅让既有降级可观察。

## Consequences

区域对象存储构造失败会成为 503 不可就绪诊断；正常响应、授权、缓存、探针结果与 MinIO 短路规则保持。内部旧 mode 与不完整 Settings 的测试接缝需要独立维护，本任务不修改或运行 Python 测试。

假 Session、引擎、配置及实际 API 函数的离线探针检查 SQL、启用、探针、缓存和错误轨迹。没有连接真实数据库、Redis、对象存储或 SDK。Milvus 的 get_collection_count 由实际存储 owner 传播初始化、RPC 和转换失败，健康检查可以沿现有错误入口判为不可就绪。已经连接但尚未创建集合的合法 col=None 仍表示零条数据，和故障分开；此处依据已安装 LangChain Community 0.4.1 的构造／初始化源码与假 SDK 链路，没有声称真实 pymilvus 或部署健康已经验证。
