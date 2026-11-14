# 模块职责与调用约定

维护目标是让一个业务改动集中在明确的位置，并能通过模块本身验证。

- API 路由处理请求解析、身份与权限入口、状态码和响应模型。
- 请求模型按领域放在 `app/api/schemas/{identity,conversations,documents,datasets,sources,pipelines,evaluation,integrations,system}/`，各领域是具有显式公开入口的普通包。域外消费者从所属领域包导入，域内继续从定义模块导入；共享 ORM 基类保留在 schemas/base.py。schemas 根入口不聚合所有领域。表单转换与 HTTP 输入约束放在 `app/api/utils/`。
- 业务操作放在对应服务模块，使用已声明的参数和返回类型；直接导入真实依赖。
- 路由装配模块只供入口组成路由，业务代码不反向导入它。不把整个模块通过 `Any` 参数层层传递。
- 内部数据沿用其确定类型；HTTP、JSON、Redis、插件等外部值在实际边界校验。
- 同一组业务选项只有一个映射位置。真实语义差异由调用方明确给出，例如切块预览关闭跨页公共行过滤。
- 不为拆文件增加代理、运行时属性转发、注册器或无实际变化的兼容层。只保留当前仓库确有调用者的旧入口，并让它引用实际所有者。

普通包入口直接导入实际公开对象并显式声明 __all__，新增或调整公共契约在此维护，不新增转发函数、动态 getattr 或全局模型入口。utils 根入口发布基础文件和响应工具；管线及 URL 保留具名公共子模块，避免普通文件工具引入应用配置。包标记和公开入口承担导入契约，不按减少文件数量删除。

文档模块的首批落点：

| 职责 | 位置 |
| --- | --- |
| URL / HTML 入库请求与覆盖参数 | `app/api/schemas/documents/ingestion.py` |
| 文件保存、文件名和来源路径规范 | `app/api/utils/file_io.py` |
| pipeline 表单验证与类型转换 | `app/api/utils/document_pipeline_input.py` |
| 治理选项统一映射 | `app/services/document_governance.py` |
| 分段访问、索引操作结果与一致性处理 | `app/services/document_chunk_operations.py` |
| 上传/重试调度、队列交接与本地源清理 | `app/services/document_processing_dispatch.py` |
| 文档状态、取消、重试与pending可重配策略 | `app/services/document_processing_operations.py` |
| 解析 / 切块预览 HTTP 流程 | `app/api/v1/document_preview.py`、`document_chunk_preview.py` |

重构验证既包括行为回归，也包括依赖方向：子模块可先于路由装配器导入，独立执行时不加载装配器，原有 OpenAPI 保持一致。不要为了通过测试重新加入模块查找；将测试依赖替换指向实际所有者。

文件与 URL 工具的边界：

- `app.api.utils.file_io` 持有上传、文件哈希、来源路径和部分文件清理。上传与 URL 下载共用 cleanup_partial_file；关闭／清理仍使用五秒的有界取消屏蔽，清理 OSError 记录来源操作后保留原传输失败。
- 包外从 app.api.utils 导入 normalize_upload_key、normalize_upload_path_parts、sanitize_upload_filename 等已公开基础工具，不通过私有名别名或转发函数组装依赖。URL 的 ValidatedFetchTarget、validate_fetch_target 与 build_pinned_http_clients 从具名 url_ingest 子模块导入，管线转换由 document_pipeline_input 子模块发布。
- URL 下载继续逐跳验证 DNS 与目标地址、固定 Host／SNI，并在跨 origin 时去掉敏感头。管线输入、URL 默认参数和响应头保留各自实际职责；真实的 None／0／False 语义不为统一外观改写。
- URL 模块先展示公共记录和校验／下载入口，再展示内部策略。下载主循环区分正常响应和跳转；状态检查、实际字节限额、写入、关闭文件和元数据构造由同一个响应保存函数顺序完成。正常结果在响应／客户端关闭后返回，跳转目标在旧客户端退出后重新校验。普通格式错误在入口统一为 400 Invalid URL；系统解析与传输异常直接交统一异常入口，下载只负责清理后原样抛出。
- 下载大小、超时和跳转设置由 document_ingestion_sources 直接提供必填参数，不经过可空选项对象或第二次默认值回填；只有实际可选的 User-Agent 与额外请求头保留可空语义。普通响应和跳转按状态码分流，跳转解析返回确定的网址。
- 初始网址在 document_ingestion.ingest_url 中校验为冻结的 ValidatedFetchTarget，经过文档来源服务直接传到下载器；下载使用同一个已验证 IP，不再丢弃目标后重复解析。数据集权限检查与来源原始 URL 语义保持；每个新跳转仍完整校验。跳转预算只使用剩余次数，文件与响应关闭仍由原来的拥有者负责。
- 下载数值在 Settings 加载时校验，工具不重复处理无效配置或超时回填。实际保存的解码字节在写入前按 max_bytes 检查，Content-Length 不单独触发应用级拒绝；传输协议有效性仍由 HTTPX／h11 负责，该限额不代表网络接收量或解码峰值。
- 文件响应使用 file_response_headers 和 set_content_disposition；attachment 是已有默认行为，下载调用不再另设相同默认值的包装。

数据库连接器的边界：

- HTTP 验证入口将已解析的配置交给 `app.connectors.connectivity.check_database_connection`；同步驱动在线程执行，连接失败和无法读取权限继续使用既有检查结果与警告格式。
- 保存配置与调度任务保留原始配置字典，交给 `app.connectors.catalog.run_catalog_sync`。不能用 HTTP 模型的默认值替换这条路径原有的画像开关、额外 ODBC 配置及权限哈希内容。目录 SQL 返回的 Mapping 只在读取边界转换成 CatalogTableInput／CatalogColumnInput，存储和快照直接使用这些对象。
- `app.connectors.store.SQLAlchemyCatalogStore` 持有调用方的 Session，只 flush，不 commit。任务层继续负责状态、审计、提交和失败处理。
- 画像隐私过滤由 `app.connectors.profile_privacy.sanitize_db_profile_snapshot` 持有，供存储与 API 读取共同使用，保留原始 JSON 的必要校验。同步查询失败继续传播；可选行快照只跳过明确的 SQLAlchemy 查询错误并记录警告，其他错误交给已有任务入口处理。
