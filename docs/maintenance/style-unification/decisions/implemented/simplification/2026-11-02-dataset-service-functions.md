# Agent Note: 数据集与文档服务直接使用模块函数

Status: implemented

## Problem

数据集创建、成员权限、组权限和分类通过只有静态方法的类组织。部分文档与连接器代码还从 API 路由装配模块取这些服务，调用者难以看清实际依赖。服务在已经完成类型校验后重复转换 UUID，并为数据库必填列增加空值过滤。

## Decision

`app/services/dataset_service.py` 和 `app/services/dataset_category_service.py` 直接提供模块函数，调用者从实际服务模块导入。两个只调用一次且只转发参数或赋值的私有辅助函数并入调用处，权限同步规则仍由一个函数负责。

API 的 `DatasetBase` 与 `DatasetUpdate` 使用 `list[UUID]` 校验组 ID；复制数据集时组 ID 来自 SQLAlchemy 的 UUID 列。服务依赖这些类型契约，不再将 UUID 转成字符串后重新解析。成员列表仍保留去空白、去重以及所属租户校验；组列表仍保留去重、数量限制、租户校验和审计。

可写数据集选择由 `dataset_service.resolve_writable_dataset` 负责。请求指定 dataset ID 时仍用 tenant 限定查询并检查写权限；省略 ID 时先验证成员，再按 `created_at` 升序选择首个可写数据集。没有可写数据集时仍要求编辑角色，并创建权限为 ONLY_ME 的默认数据集。手工入库、文件上传、URL／HTML 入库及连接器直接调用该函数。

本地 owner 引导继续受开关、环境、认证模式、默认租户、租户来源和回环地址共同约束。请求状态属于可缺失的边界，原有缺失处理保留。创建与更新的提交、刷新和异常回滚顺序保持原样。

分类分配入口使用 `list[UUID]`，服务只保留稳定去重、同租户分类存在性检查和替换事务，不再次解析 UUID 或跳过无效项。数据库的原生 UUID、非空分类 ID 和租户内唯一成员关系直接用于查询结果。树构建帮助函数有明确的字典／对象输入契约，其字段适配保留；已构造节点的排序、深度和父级映射直接使用声明类型。环检测、非叶节点删除限制和分类列表附加计数的既有降级保持原样。

本批保留 `HTTPException`：现有调用链包含对该类型的捕获与转换。业务异常迁移需要连同这些错误边界单独核对，避免只替换服务端异常而改变已有响应。

文档成员与组 allowlist 同样由 `document_permission_service` 的六个模块函数负责；API、连接器和单文档检查直接调用实际所有者。API 的组列表已经是 UUID，连接器配置的组列表仍是字符串，因此保留字符串到 UUID 的边界解析，并直接复用已有 UUID。去重、200 项上限、同租户存在性校验及先校验后替换顺序保留，数据库非空 UUID 查询直接解包。

`document_access` 保留批量筛选和 SQL 条件，`document_access_service` 保留单文档／生命周期判断，`document_permission_service` 负责 allowlist 持久化；这三项职责不因命名相近而合并。内部使用 ORM 声明的 nullable 字符串与 UUID；去掉无调用的成员检查兼容参数、组查询转发和两个单次判断包装。未知模式的拒绝、未分配文档所有者规则、组指标和查询排序保持原样。

分块预设的四个模型归到 schema，五个数据库操作归到所属服务；路由只组织鉴权、数据集授权与响应。旧私有操作名称直接导入实际函数，保留既有 patch 引用，没有转发壳。列表上限继续由 Query 校验，非法路径 ID 仍返回未找到，payload 与查询中的非法数据集 ID 仍按原格式返回 400。

URL 入库请求 `UrlUploadRequest` 归入 `app/api/schemas/document.py`，与其引用的 `DocumentPipelineOptions` 及其他文档请求模型共用 schema 所有者。上传和连接器调用方直接导入该类型；`documents.py` 保留直接导出同名类型，兼容现有 Python 引用。字段、`extra="forbid"`、解析器与分块策略默认值不变。

文件名清理、上传路径段归一化与上传 key 生成由 `app/api/utils/upload.py` 负责；共享 streaming 上传逻辑仍在同一 API utility。控制字符、Windows drive 前缀、FakePath、`..` 折叠、路径长度限制、文件名叶子截取及其 400 文案保持原函数规则。`documents.py` 直接重导出被现有调用方引用的名称，上传与预览入口直接依赖 utility。

入库运行记录由 `ingestion_run_service` 的五个模块函数负责，入口位于私有统计与锁帮助函数之前。上传模块直接调用实际服务，不再从文档路由装配器取静态类；两个只为取得服务而接收整个模块的参数同时退出。数据库与模型已声明的字段直接使用，JSON 统计和文档元数据仍保留真实形状适配。

创建运行记录的数据库失败由调用方决定处理方式；绑定与收尾维持 best-effort，状态通知的 `required` 模式仍在回滚后抛错。运行行锁先于关联行锁、重复绑定幂等、唯一约束、提交与观测顺序、统计 top 上限及空批失败规则继续保持。已有并发夹具仅补齐模型的 config 字段和 Session.flush，并同步服务引用，不增加用例或断言。

用户元数据的 merge／replace、标签与备注规则和 API 临时统计由 `document_metadata_service` 负责；原 `document_runtime_metadata` 模块直接更名，未另增重叠服务。上传、单文档修改、批量修改、列表与详情从该所有者导入。真实 JSON 的形状检查、标签首次出现顺序去重、50 项上限与每项 64 字符限制、备注 20,000 字符截断继续保留。内部请求已经是 schema 声明的字典、布尔值和字段集合，不再重复转换或填空默认值。

批量操作与修改路由直接依赖权限、元数据、管线标识和实际操作模块，退出动态路由装配器。禁用、启用、归档和取消归档共用一个逐项处理函数，成员检查、写权限、审计及单次批量提交仍按原顺序执行；批量删除直接调用已有生命周期删除服务。待处理状态的三个判断归到已有生命周期服务；上传未排队、旧数据空闲、任务标记、处理进度及版本就绪的原条件保留。同步的 `patch_document_pipeline` 直接调用，后续异步 retry 继续 await；原调用对 ORM 返回值执行 await 会失败，这是明确修复的既有缺陷，不能把它当作重构等价性结论。

列表与统计的数据集范围由 `document_access.apply_document_dataset_scope` 统一维护；列表、统计与目录树的生命周期选择由同模块的 `apply_document_lifecycle_filter` 维护。调用方传入已经过 Query 校验的值，仍分别执行成员检查、文档 ACL 与租户限定；processing 的特殊匹配和其他状态的原值比较、count、稳定排序与分页顺序不变。共用 SQL 规则沿用现有查询所有者，避免再建一个服务层。

MinerU 的 `_normalize_batch_status` 已提供七个状态字段，API 直接消费完整内部结果；外部 HTTP／JSON 适配留在 MinerU。目录与重复查询使用明确的 Row／ORM 类型，保留元数据形状筛选、目录深度夹取、时间戳与 SQL 扫描的既定降级。

状态、取消、重试、删除以及上传、批量上传和 URL 入库共同使用 `app/api/utils/document_dispatch.py`。该模块负责 API 后台任务登记、进程内并发限制、线程桥接和队列必需时的失败状态及 503 转换；路由装配模块不再作为这些调用的间接所有者。URL 入库未提供 `BackgroundTasks` 时仍在请求内处理；有后台任务时，对象存储临时文件仍在处理结束后清理。队列任务 ID 保持 `doc:{tenant_id}:{document_id}:{pipeline_hash}`，任务元数据的提交和回滚时序不变。

状态查询和修改直接复用生命周期查询与读写权限函数；重试直接依赖管线身份、解析器、对象存储和索引通道所有者。普通文件来源以 `Path` 表达，对象存储来源以 store 与 object key 表达。重试的 400／403／404／503 转换、completed 强制重试、pending 可重处理条件、skip-if-unchanged 审计及回滚、对象路径权限与有限 JSONB 扫描降级保持原样。取消仍先提交 cancelled 状态，再尽力中止已有任务；仅保留原有超时抑制。

队列模块以配置声明和 arq 的 Job／JobStatus 类型表达契约；arq 状态值由枚举提供。文档、连接器及证据修复仍在空任务对象时返回请求的 job ID；KG、索引重建和审计协调仍返回空值；两类数据集扫描仍确认 job 接受状态后返回 ID。worker 边界的 UUID 字符串化和有效选项快照保持不变。

连接器执行器由 `connector_run_executor` 维护唯一的 connector ID 到函数名映射；队列执行和 HTTP 路由都调用同一 resolver。`connectors_runs` 不再复制九项映射或从路由模块按名称取 dispatcher。resolver 接收 ORM 非空 `connector_id` 字符串，保留去空格与未知 ID 结果，不再把任意值转成字符串或空串。服务仍在实际执行时延迟导入 `app.api.v1.connectors`，因为聚合模块会为分拆的 connector 模块设置 `_leader_module`；提前直接导入叶子模块会跳过这层既有 helper 绑定。

API 请求的 `PipelineOptionOverrides` 和 `to_pipeline_options` 由 `app/api/utils/pipeline_options.py` 统一维护。手工入库、上传、文件预览与分块预览都直接导入；`documents` 路由保留原有类型名称的直接重导出。外部 schema 解析、覆盖字段顺序、None 过滤、`PipelineOptions` 默认结果及 400 错误的生产文案继续保持一致。

multipart 表单的 pipeline JSON 解析与 chunk overlap 约束也由该 API utility 负责。解析保留空值／`null`／`none`／`undefined` 的处理、表单长度上限、schema 校验和生产错误脱敏；overlap 仍在非集成 chunk strategy 上与 chunk size 比较。上传直接依赖 ingestion policy、governance profile、parser、chunker、pipeline config、pipeline types 与 document identity 的实际所有者。`documents.py` 保留旧 parser、validator、常量的直接导出。

Batch precheck 的 staging tree、scan run 和 policy suggestion 由上传入口直接使用标准库、SQLAlchemy model/session 与两个所属服务。仍先创建 pending scan row、commit／refresh，再在线程内执行扫描；扫描异常时标记 failed 并重新抛出，调用层仍 best-effort 继续上传。policy suggestion 的 409 不告警，其他异常继续记录到 `api.documents` logger。finally 清理 staging root 的顺序保持不变。

tenant-scoped 重复文档查询和 bounded metadata scan 归入 `document_dedup_service`。查询先限定 tenant、dataset 和未归档状态，再按 updated／created 时间降序；可用时保留 JSONB fast path，数据库查询失败时仍扫描最多 5,000 份文档并按相同 identity 条件返回首个结果。`document_identity` 继续只负责 metadata hash/key，不接收 SQL 查询职责。`documents.py` 直接重导出旧 lookup 名称，上传流程直接导入服务。

preview 图片引用解析、本地临时文件读取与 owner sidecar 验证、legacy 记录查询和 MinIO 存储由已有 `document_preview_utils` 共同负责。手工分块直接导入该 owner，documents 对外保留原名称的直接导出。legacy 查询仅在 owner 校验路径中局部导入，因为 `document_preview_legacy` 的正则直接来自本模块，顶层互相导入会产生循环。

RBAC 与配额继续依赖这些成员契约，具体边界见[权限与配额决定](2026-11-02-permission-quota-contracts.md)。

文件下载、preview 和 image-url 的 tenant／account 解析归入 `document_assets` 路由模块，ACL 直接导入 `document_access_service`；手工 owner 与 legacy data lookup 继续留在对应服务。documents 只直接重导出仍有旧 Python 引用的错误常量和共享资产入口，不为资产读取、缓存或认证提供代理函数。header auth、JWT claim、查询 tenant、文件根目录和 Range 规则保持各自原有入口语义。

## Alternatives considered

- 继续把 JSON 表单解析与 chunk overlap 检查放在 `documents.py` 可以少迁移几个名字，但上传、预览和分块预览会依赖路由聚合器。单建 upload pipeline 模块则会与现有 API `pipeline_options` utility 重叠。当前沿用该 utility 作为表单到 pipeline 类型的边界，并从现有业务模块导入策略、parser、chunker 和 metadata 规则。
- 把 batch precheck helper 作为 `documents_module: Any` 传入可以少列几项依赖，但该流程直接使用标准库文件操作、扫描 model、session factory 和已有 scan/suggestion 服务。当前将这些边界直接导入上传模块，不另建 precheck service。

- 把文件名规则继续留在 `documents.py` 可以少搬函数，但上传模块需要由路由聚合器取验证逻辑。新建独立 filename service 又会把同一上传边界拆成两处。当前复用已有 `app/api/utils/upload.py`，它已拥有上传流和落盘规则。

- 保留静态类能缩小引用变更范围，但继续存在无状态外壳，与已确认的模块函数约定不一致。
- 增加旧类转发层可以兼容旧符号，但会保留两套入口。当前仓库调用方同批迁移，因此不增加这层维护点。
- 将三种文档访问职责合成一个服务能减少文件，但 SQL 过滤、单文档拒绝和 allowlist 写入有不同的输入与调用方式，当前维持明确所有者并删去无意义转发。
- 为用户 patch 新建独立模块能让旧运行时文件保持不动，但文档元数据又多一个维护入口；当前合入更名后的已有服务，三项公共操作直接导入。
- 将成员校验再抽出一个模块能够进一步拆分文件，但会同时影响本地引导与 RBAC 的所有者边界。本批维持现有所有者，减少跨领域调整。
- 将可写数据集选择留在 `documents.py` 或让 `connectors.py` 再转发，能缩小新调用范围，却会令共享 API 流程依赖路由聚合模块。当前把选择规则放在已有 `dataset_service`，与租户校验、写权限和默认数据集创建共用实际所有者。
- 把去重查询放进 `document_identity` 能让调用者只依赖一个模块，但会把 SQLAlchemy session、ORM filtering 和数据库 fallback 混入 metadata identity helper。保留在 `documents.py` 则继续令文件上传依赖路由聚合器。当前使用单独 persistence service，identity hashing 与数据库 lookup 各有明确 owner。
- 将 `UrlUploadRequest` 留在 `documents.py` 可以避免迁移导入，但 `document_upload.py` 需要从正在装配它的路由模块取请求类型，继续形成反向依赖。当前把请求类型放在现有 schema 所有者，并由路由直接重导出旧名称。
- 让连接器继续通过字符串名称解析 `UrlUploadRequest` 可以少改调用点，但会让类型来源依赖运行时路由注册。当前连接器直接导入 schema，其他业务 helper 的既有解析仍留待各自所有者迁移。
- 让 HTTP 路由继续维护 dispatcher 名称表可以避免依赖执行服务，但队列和路由各维护一份相同映射，新增 connector 时容易只更新一边。当前两者共同调用执行服务的 resolver，未知 ID 仍由 API 转成原有 400。
- 在 worker 导入阶段直接导入各 connector 叶子模块可以去掉运行时字符串解析，但会绕开聚合模块对 `_leader_module` 的初始化，也会在队列启动时加载所有 API 模块。当前保留执行时的延迟导入；彻底移除该依赖需先迁移叶子模块的共享 helper 所有权。
- 只让手工路由导入 documents 中的图片重写函数，改动较少但继续依赖路由装配器；建立新图片服务则会与已有 preview 图片归属和 materialization 分成两份 owner。当前把完整重写流程移入现有 `document_preview_utils`，按需延后 legacy 查询以断开其 regex 反向导入。
- 分别保留上传与 URL 的队列调度能让日志和入口参数各自独立，但会保留两套队列必需判断、任务元数据提交和后台任务注册流程；当前沿用 API utilities 所在层的一份调度实现，保留两种入口本来的同步与后台执行方式。
- 把 `BackgroundTasks` 和 HTTP 错误转换迁入任务队列模块会令基础队列依赖 FastAPI；当前由 API 工具层转换错误并调用既有队列所有者，队列客户端继续只管理 arq 连接与入队返回值。
- 保留 pipeline option 转换在 `documents.py` 可以少移动代码，但会让多个 API 入口继续依赖路由装配模块；移入 `app/services/pipeline_config.py` 则会把 Pydantic 请求校验和 HTTP 错误文案交给处理内部有效选项的服务。当前由 API utility 持有请求适配与 override 合并，内部有效管线解析仍由现有 pipeline config 服务负责。

## Consequences

调用者直接依赖业务所有者，数据集更新流程少两层跳转。内部函数要求与签名相符的 UUID 和字符串列表；将来新增非 API 调用者时，其输入适配应在自己的入口完成。

移除旧类涉及调用方和现有测试引用的同步。按用户 2026-11-02 的要求，不新增或运行 Python 测试；仅运行 Ruff、语法及调用方静态检查。静态检查不能证明运行时行为回归，完整后端批次仍未验收。

共享调度将并发与临时文件生命周期留在一个 API 工具所有者，相关入口不再重复维护队列交接。该批次运行 Ruff 和静态 AST、路由、错误、调用签名及既有断言核对；按用户要求，未新增或运行 Python 测试，运行时回归仍未验证。

共享 pipeline adapter 让调用方不再经 documents 路由模块取转换函数；documents 对外可见的 overrides 类型仍由原名称直接重导出。四个现有调用领域经完整 AST 与固定错误构造核对；必要的测试 patch 只改到新的函数所有者，没有修改断言或增加测试。

移动可写数据集选择器后，现有 404／403 映射、成员检查次数、数据集升序查询、默认角色拒绝及 ONLY_ME 创建调用顺序保持原样。10 个修改前模块按精确所有者／名称迁移规则核对，调用 fixture 只迁移 patch 目标；没有运行 Python 测试，运行时事务仍未验证。

15 个图片 rewrite helper 按原函数体迁移到已有 service owner；图片上传错误、body 和 start_index、reuse owner、无 MinIO 认领、大小限制及 HTTP 403／422 行为保持一致。57 条既有测试断言未修改，按用户要求没有运行相关 Python 测试。

资产请求 helpers 迁到实际 route owner 后，header／JWT 身份来源、租户选择、文件根目录约束和流式响应处理不再经过 documents module 参数；对外 HTTP 路由和错误文案维持原样。兼容重导出仅保留仍被追踪调用的 symbol 名称。

URL 上传模型的单一声明位于文档 schema；上传与连接器入口不再为构造该类型访问 documents 路由聚合器。兼容导出保留既有外部 Python 引用，模型字段与默认值维持原样。

队列和 API 路由共用一份 connector executor 映射。无效 connector ID 仍分别得到队列的 `False` 和 API 原有的 400；连接器聚合器仍只在实际执行时导入，直到共享 helper 绑定迁移完成。

上传文件名和来源路径规则集中在现有上传 utility；旧 route export 仍有效，直接依赖的入口不再为归一化加载 `documents.py`。输入边界、拒绝错误与字符串长度约束保持原样。

pipeline 的 JSON parser 和 chunk overlap validator 归入 `pipeline_options` utility 后，所有相关 endpoint 仍使用相同 schema、默认值、合并次序及 400 错误边界；上传配置流程不再从 documents 路由装配器读取其直接业务依赖。

batch precheck 不再传递整个 documents 模块；hardlink/copy fallback、scan 状态提交、失败标记、建议应用的 best-effort 和 staging 清理顺序保持原样。日志仍使用原 `api.documents` category。

文件上传与 URL 入库共用 tenant-scoped duplicate lookup。route 层只按各自的 commit/retry 约定处理结果；查询的 tenant/archive filters、排序、JSONB fast path 和 bounded scan fallback 只维护一份。
