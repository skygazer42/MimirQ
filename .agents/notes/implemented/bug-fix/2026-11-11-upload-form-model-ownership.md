# Agent Note: 上传表单由一个完整模型持有

Status: implemented

## Problem

文件上传在同一个路由参数表中同时声明独立 File 和两个 Pydantic Form 模型。本机 FastAPI 0.135.3 的 `_should_embed_body_fields` 在多个 body 字段时启用嵌入，`request_body_to_args` 只为唯一未嵌入的模型展开表单字段；原平铺 multipart 不能按这份声明取出上传选项和覆盖参数。将 dataclass 改成 BaseModel 后仅切换标记，没有同时核对这个组合条件。

审计导出和清理也分别使用两个 Query 模型；同版本 `request_params_to_args` 的字段展开条件是唯一模型参数，同样不能按预期读取原平铺筛选字段。

## Decision

单文件和批量上传各使用一个完整的 Form 模型，文件字段分别保留原 `file` 与 `files` 名称。已有 PipelineOptionOverrides 提供共同覆盖字段，表单子模型保留平铺的 parser、dataset、pipeline、metadata 和批量控制字段。路由只有一个 `Form(media_type="multipart/form-data")` body 参数，继续通过原 Request／Session 依赖获取请求上下文。

覆盖模型只从完整表单中按 PipelineOptionOverrides 的声明字段提取；`exclude_none=True` 保留 False、0 和空集合。业务函数继续接收原 `file`／`files`、form 和覆盖对象，只删除对同型覆盖对象的重复构造。原 parser 默认值、参数类型、限额及业务 400 错误位置保持。

URL 和本地 HTML 请求的真实定义归到 document_ingestion.py，替代它们在 document.py 中的定义及导入转发；生产调用方指向唯一所有者，不增加兼容别名。DocumentPipelineOptions 保留原 document.py 所有者。

目录按领域归类后，两处实际位置分别为 app/api/schemas/documents/ingestion.py 与 documents/models.py；模型及参数提取决定不变，归类依据见[Schema 领域布局](../architecture/2026-11-11-schema-domain-layout.md)。

审计导出／清理参数继承共同的筛选字段，每个路由只接收一个 Query 模型。进入原查询或清理流程前，按筛选模型声明投影出纯筛选对象，防止操作参数进入 SQL 筛选调用；管理员校验、时间窗口、游标、dry-run 和事务顺序保持。Skill 同步记录当前版本的单模型提取限制，避免仅依据较新文档假定任意参数组合有效。

本记录与[API 路由与输入归属](../simplification/2026-11-10-api-route-and-input-owners.md)部分重叠，继续沿用其服务／路由分工；本篇只负责 multipart 模型的框架提取条件和入库请求所有者，不取代请求体大小、并发租约或服务事务决定。

## Alternatives considered

- 保留多个 Form 模型能少改业务参数，但当前 FastAPI 实现要求独立表单键，不能满足现有平铺 multipart 契约。
- 恢复 dataclass＋Depends 可以逐项抽取旧表单，却重新引入两份字段声明；一个完整 Pydantic 模型同时表达文件和选项，现有服务仍可直接读取字段。

## Consequences

表单字段只有一个维护点，外部字段与业务对象的关系可顺序阅读。子模型包含文件和覆盖字段，路由必须按明确字段集合生成 PipelineOptionOverrides，不能把文件、parser 或 metadata 传给覆盖校验。表单未知字段沿原提取策略忽略；覆盖对象保持 extra="forbid"。未来升级框架或再次拆成多个 body 参数时需要重新核对提取条件。

## Verification

只读核对本机 FastAPI 的 `_should_embed_body_fields`、`request_body_to_args` 和序列表单取值实现；静态确认两个路由分别只有一个 Form body 模型，文件名、类型、覆盖字段集合与原声明一致。两个迁移请求类的完整字段、默认值和配置对照通过。限定 Ruff／格式、Python 3.11 AST／源码编译及生产导入检查按实际结果记录。

另核对 `request_params_to_args` 的唯一模型条件；两个审计路由只有一个 Query 模型，纯筛选投影使用原七个字段。未执行 HTTP 绑定或清理业务。

现有导出脚本在 OpenAPI 模式导入并装配应用，成功导出到本机临时文件。新旧四个参数接口的字段契约在规范化说明元数据和等价文件类型写法后相同；没有覆盖存量 web 产物，不声称共享树全量生成产物已同步。按用户要求未新增、修改或运行 Python 测试；未发起 multipart／审计请求、启动服务或执行上传／数据库。导出和契约检查不代替真实请求运行验证。
