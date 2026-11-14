# Agent Note: 数据库连接器按实际职责收敛

Status: implemented

## Problem

app/connectors 用十个文件维护两种数据库的连接探针和目录同步。通用 Connector 抽象要求 connect、文档迭代和文件类型，但生产代码只实例化两个无状态类来检查连接；文档迭代只有占位实现。目录同步在字典、TypedDict 和数据类之间重复转换。SQLAlchemy 的 mappings() 返回 RowMapping，原来的 dict 判断将正常表和列跳过，可能把有数据的目录同步记为空结果。

## Decision

目录保留 catalog.py、connectivity.py、store.py 和 profile_privacy.py 四个模块。仅服务探针的抽象与注册框架、无用占位文档类型、包聚合和无参数作用的 SQL 包装退出。API 与后台任务直接依赖定义模块，沿用项目已有的命名空间包方式。

base.py、registry.py、types.py 和两级 __init__.py 删除；db/catalog_connectors.py 收敛为 connectivity.py，db/catalog_runner.py 与 db/introspection.py 合入 catalog.py，db/catalog_store_sqlalchemy.py 迁到 store.py，db/profile_privacy.py 迁到同级。十个原文件均有处理结论，没有转发壳。

HTTP 连接探针接收入口已经验证的 Pydantic 模型，同步驱动在线程运行。保存配置和调度任务接收的原始字典有不同的实际契约：额外 odbc_driver 字段参与连接，省略 profile_enabled 表示关闭，权限哈希保留原始字段与缺省表示。这条路径继续使用原始 Mapping，在真实边界保留既有默认值和限额转换；不套用会填充默认值、忽略额外字段的 HTTP 模型，也不新增携带两种表示的配置包装。

目录 SQL 与读取归到 catalog.py，查询参数绑定、排序和标识符转义继续由此维护。RowMapping 在读取边界一次转换为 CatalogTableInput 和 CatalogColumnInput；持久化和行快照直接消费这些对象。列名校验与五千列上限保留在外部行边界，存储不再重复归一化。画像过滤保留独立所有者，因为存储与 API 读取都需要它。

存储持有真实 Session，任务继续负责提交、状态和审计。连接探针的失败结果与权限警告保留；可选行快照只跳过 SQLAlchemy 查询失败并记录具体表的警告，意外错误交给既有任务错误记录。连接、游标和引擎按各自作用域关闭，清理错误不再静默压掉。

相关的路由依赖原则见[API 调用与输入所有者](../simplification/2026-11-10-api-route-and-input-owners.md)；该笔记继续持有路由装配等其他决定，本次不吸收或归档它。

## Alternatives considered

- 保留通用抽象和注册器能容纳新增插件，但当前生产使用仅是两个无状态连接探针，其他协议没有真实调用方，保留会继续要求占位实现和注册副作用。
- 把四个职责合成一个文件能进一步减少数量，但画像过滤被读取与写入独立复用，存储有自己的 Session 生命周期；混合后会扩大导入和修改范围。
- 统一使用现有 HTTP Pydantic 配置能让字段访问更直接，但保存配置与调度实际传递原始字典，会丢失自定义驱动、改变画像缺省和权限哈希，校验异常还可能带出解密后的输入。因此保留两条真实入口契约。

## Verification

当前逐文件复核保留四职责。SQLServer include同时含qualified和name时按并集匹配，修漏读；存储只消费唯一catalog入口已限5000列及64位SHA，重复裁切退出。探针改等待线程资源关闭后传播取消，并在ODBC建cursor前设querytimeout3；login timeout不代表statement预算。固定pyodbc5.3.0源码与fake driver证明设置点，实际驱动未安装，不能宣称硬墙时限。四文件独立审查及P2窄重审通过，原始配置／hash／提交所有权保持。

八个生产文件按 Python 3.11 解析与编译；四条目录 SELECT 与起点字符串相同，存储查询谓词保持。Ruff、格式、OpenAPI、哈希及隐私规则的实际检查和环境限制记录在[重构验证记录](../../../../docs/maintenance/style-unification/verification.md)。独立审阅核对保存配置、手动执行与调度链，修正入口契约差异后复核未发现新增问题。

## Consequences

模块数量从十个降为四个，同一目录数据不再在多个字典形态间往返。内部导入位置和旧探针类退出，没有旧路径兼容壳；按用户要求保留的测试仍有旧导入与补丁点，需要在后续测试任务中迁移。本批不新增、修改或运行 Python 测试，不把导入或源码核对当作真实数据库运行通过。

原始保存配置边界仍需维护其真实默认值和字段规则。将来若保存接口统一写入规范化模型，必须同时设计字段、画像开关与历史权限哈希的迁移。真实新增连接器若需要共享会话或资源生命周期，再据实际协议组织，不自动恢复已退出的占位框架。
