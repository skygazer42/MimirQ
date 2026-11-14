# Agent Note: API 路由、输入与限流实现的实际归属

Status: implemented

## Problem

连接器和文档装配入口维护大量无调用的服务别名，连接器还使用动态属性查找组装路由。相同的五项错误响应说明在多处复制。文档预览与上传分别维护管线参数解析、覆盖参数数据类和校验，预览代码继续通过动态属性读取已解析的配置，并将合法零值替换为默认值。HTTP 中间件还复制了一套已有的令牌桶实现。

## Decision

API 按用户确认的 Python 规约先删除无用代码，再简化保留流程。路由入口直接导入实际模块，API 总入口由单个 `@cache get_router()` 延迟构建路由，main.py 在注册时显式调用。单次转发的私有构造函数和通过模块 `__getattr__` 提供的 router 属性退出；不为旧 Python 导入保留兼容入口。连接器目录的空路径通过原有的 `routes.extend` 装配：FastAPI 拒绝在空前缀下使用 `include_router` 包含空路径。仍有实际生产Python调用方的具名路由导出才保留直接导入；documents装配入口九个仅测试消费的处理函数／常量／存储转出退出，24个include及其顺序保持，实际HTTP处理函数仍由各自模块持有。

完全相同的错误响应说明读取已有的 `app.api.utils.http_exception_responses`。具有额外状态码或不同集合的响应说明继续由各自模块持有。连接器的重复响应模块退出。

同一路由器的相同默认响应只在 APIRouter 声明，注册入口继承其已物化的响应元数据。运行列表的 skip、limit 和 dataset_id 使用 sources 领域的 ConnectorRunListQuery，由 Pydantic Field 持有原默认值和边界，通过 Annotated[Model, Query()] 平铺提取；不使用只保存三个属性的普通参数类。该来源只有这一个查询模型，符合当前 FastAPI 0.135.3 的提取条件，额外参数沿用原忽略语义。模型从既有公共包入口显式发布，服务 helper 和错误常量继续由实际业务 owner 持有，不通过路由重导出。

分块写路由只公开六个具名HTTP入口，退出13个私有helper及3个错误常量的API重导出；实际实现保留在原服务owner，生产调用直接使用owner。reembed四字段结果由已有响应模型校验；其余ORM返回使用明确模型类型，删除继续await并返回204空响应。

数据集分析的日期窗口与极性由同一schema基类声明，五个公开Query模型按真实入口增加分类、分页与ruleset，供九个适配器实际复用。每个查询来源仍只有一个完整模型，使用原始字符串／None交给报告owner，不增加解析或默认替代。分析输出是owner持有的版本化动态JSON，HTTP层保持导出方式，不复制一套报告字段。读写授权helper持有原成员检查顺序，PNG任务状态的404／503转换共用，结果读取前的409和结果缺失文案继续独立。

`app.api.utils.document_pipeline_input`持有表单管线解析和输入校验，覆盖参数使用documents领域公共入口的PipelineOptionOverrides。重复的pipeline_options.py和任意关键字兼容入口退出。分块预览外部输入由现有documents/models.py的Pydantic模型持有，解析预览完整multipart由ingestion.py持有；内部配置／执行状态继续dataclass；覆盖后的输入由请求模型校验，输入错误在实际入口转换400。真正未提供的表单值保留缺省，False和0直接传递。

分块预览按每来源一个完整模型提取：8字段ChunkPreviewQuery、20字段公共Form、包含file的上传Form与加4字段的by-sha Form。上传声明multipart，by-sha继续Form默认urlencoded；公共before validator只删除原始字典的精确空串，保持原独立Form默认值，不去空白或处理Query。策略相关size等业务校验仍按原400顺序，不能通过Field约束意外变422。配置构造直接接收Query和Form，统计十元组改为具名内部记录；缓存与by-sha共用实际parse／split／filter阶段，不把所有内部记录改成BaseModel。

文档详情的三项查询使用完整Pydantic Query；单一入口直接调用既有可读权限owner，不再复制dataset分支。include_chunks控制是否读取并赋值chunks_loaded，all_versions由既有版本resolver持有；runtime metadata仍在分块后通过原owner附加，其set_committed_value不产生数据库更新。详情返回原ORM，由已声明响应模型完成公开投影。

文档分块读取的三个入口共用文件内可读文档加载，dataset与文档ACL复用现有权限owner；两个列表的版本范围由单一查询构造持有，all_versions交给已有resolver。列表和匹配使用各自完整Pydantic Query及已有响应模型，模型放在既有chunk组，不再增加模块。详情保留跨版本读取，空白匹配保留授权后早返；同router默认响应不逐路由重复声明。

解析内容入口共用document与parsed-content读取及现有访问规则，以已有外部响应模型承载文本与截断标志，不再传递五项元组。max_chars由一个Pydantic Query声明原默认／范围；metadata的原始JSON边界只判断一次，已有persisted键（包括None）优先。文本扩展名仅决定资格，返回布尔；本地补读属于已有接口能力，其安全路径、字节预算、读取异常不可用和空白文本政策保持，不能因名称含fallback就删除。

死信列表的七项查询由一个完整Pydantic模型持有，返回已有列表／重放模型。可读文档与仅dataset记录两个SQL访问分支具名，保持原租户、NULL和ACL条件；自有四项错误响应只在router内声明，不擅自扩为共享五项集合。单调用prepare并入持有Session的worker，但授权读取和重放后标记保留两个独立worker Session，中间await既有重试owner，不让Session跨越异步重试生命周期。

重复文档检测的四项查询由一个完整Query持有，已有Item／Group／List模型组装返回；只校验最终选中和截断后的输出Row。PG计数、top分组与window文档复用入口已授权的Query，Session取自该Query；扫描路径按SHA保留原始Row再排序和截断。不增加内部记录类、字典构建转发或额外资源，两个已有后端路径及各自SHA／时间排序政策保持。

文件夹视图的dataset、lifecycle和深度由既有folders schema中的完整Query持有，Node与TreeResponse保留原定义。自引用模型自动完成后不再额外model_rebuild；根节点空名称／路径、子列表独立工厂和原深度／数量约束保持。来源路径由SQL TEXT／NULL投影给出，API只处理真实空值与空白；树owner继续持有分段、深度裁剪及排序，不把同一能力再拆模块。

健康卡直接复用可读权限与pipeline owner，range和semantic从同一已限定Query生成投影；范围统计全量，只有语义采样限额。既有quality仅dict与nullable计数None到0的规则放在health schema的data-only validators，主流程先规范数据再计算；空样本与关闭评分分开，非空后直接使用真实分母。三个可选KG／metrics／index调用保持独立缺项政策，失败记录UUID与异常类型，不记录异常消息或文本。

文档列表的11项查询由单个Pydantic模型持有，普通属性存储类退出。file_type／owner／q／source prefix的既有规范化放在after validators，原始字符串长度先验证；入口直接应用已规范化筛选，前缀二次截断和单调用包装退出。status的processing特殊集合与其他原字符串匹配分开，排序列由已验证Literal对应静态映射；count、稳定id次序、页和metadata附加保持，只有实际返回页构造输出模型。

解析预览的单一DocumentPreviewForm包含原14表单值和file，精确空串沿原Form缺省，不去空白或丢False／0；覆盖DTO只选择实际字段交集。授权读取由本文件worker with SessionLocal持有，取消等待关闭，不再无用地注入request db。生产者保证的documents／metadata／id等键直接消费，缺协议应报错；已报告artifact先写入请求持有set，文档构造或等待取消仍可收尾。

清理标记只在tenant_root相对parts内匹配，禁止祖先标记意外授权删除租户根／普通目录；已解析symlink逃逸仍拒绝。Path.resolve的原生symlink-loop RuntimeError与OSError／ValueError在窄解析边界跳过，不恢复无差别吞错。两段原5秒shield分别保留，nested finally确保重复取消时第二段也执行。非法dataset UUID由旧未处理500修成明确400且仍先检查成员。

状态／取消／重试／删除入口继续是四个具名适配，九个无生产消费者的服务转出退出；仍有真实调用的retry handler由文档装配入口具名发布。重试的force／skip_if_unchanged／parser_backend由一个完整Query持有，原值直接交原owner；删除继续显式权限检查、默认成员检查并204空响应，不通过通用dispatch或别名隐藏删除生命周期。

文档统计的五项查询沿同一Pydantic写法，原始长度先验证再规范化；q、file_type、owner顺序与原SQL保持，单用过滤转发退出。分组COUNT与COALESCE SUM仍用同一授权Query，聚合结果按total_chunks／total_size读取；file_size为BigInteger，实际PG SUM的Decimal到int转换保留，不将真实聚合边界误删为过度防御。空集合SQL零值和大整数精度由原规则维持。

时间线的查询上限由独立Query声明，SQL预读及合并后返回都用验证值；权限复用既有readable owner。敏感键／递归深度／每层20和未知值跳过是实际PII数据边界，不按过度防御删除。Item日期已经必填，排序key只处理真实timestamp转换边界并沿原0回退／id双降序；synthetic原始可空日期、审计字段投影和返回条数口径保持。

入库预览直接读取 `PipelineEffective`、匹配规则、预处理结果和已经加载的数据集，退出动态默认值读取和无职责的元数据包装。局部变量使用完整的解析器与分块策略名称。检索配置中的已声明字段直接读取；反馈与 Dify 中确认无调用的函数退出。

HTTP 限流与工作空间配额共用已有的 `app.core.rate_limit`。共享实现保留 HTTP 实现对零突发容量的处理，Redis URL 按必需字符串使用。中间件包入口不再预加载配置和 JWT。

请求体大小限制按“检查声明长度、累计实际读取量、超限报错”展开。请求头由 Starlette 的 `Headers` 读取，非法 Content-Length 在读取前返回 400，已知长度超限在读取前返回 413。按块读取超限时抛出框架 `HTTPException(413)`，由 FastAPI 的异常处理层响应；私有空异常类、外层捕获和仅一次调用的拒绝方法退出。每个请求的累计字节数保留在局部接收函数中，上传保持按需读取。Content-Length 允许缺省，None 判断属于这个真实的 HTTP 输入边界。

已有上传测试使用响应模型的 JSON 投影核对 HTTP 数据；数据库替身模拟预检查 UUID 的生成。只验证已删除别名的测试退出，输入行为测试直接导入实际校验函数。

后续上传输入的单模型提取条件与 URL／HTML 请求归属见[上传表单模型所有者](../bug-fix/2026-11-11-upload-form-model-ownership.md)，本篇保留其余路由与服务决定。

三个上传HTTP入口保留原201与六项错误响应，只由router声明相同响应集合。单文件与批量Form的相同投影由既有PipelineOptionOverrides父模型持有，只取父字段并exclude_none，False／0和字段提供状态保持；DocumentPreviewForm有不同None语义，继续使用自身转换。没有生产消费者的MinIO及锁错误常量API转出退出，真实锁与存储仍归原入库owner。

文档版本四入口复用同一文档读取与既有响应模型，diff三个查询由完整Pydantic模型声明，strip和空hash400仍在权限后。每个函数复用自己的租户／文档Query，激活仍读取exists、COUNT和metadata三次；COUNT直接使用原生整数，真实nullable metadata／日期及历史chunk的id签名保留。可选provenance边界只删已成立的重复类型判断，同一JSON字段只读取一次。激活与删除的主提交、刷新、二次附属审计及索引／KG清理失败规则保持。缺from/to时原生模型的422诊断input呈现参数字典，状态与type／loc／msg保持；这一对外表示变化明确记录，不追加全局转换或兼容包装。

## Alternatives considered

- 观测模型继续与26个入口混放可少一个文件，但32个公开契约及14查询模型、8稳定内层已经形成独立维护职责；集中在单个system/observability.py并按public包发布。网络与血缘少量只被各自入口使用的模型仍内聚，不为每模型新建文件。源文件数增加一项并明确登记，不以机械减少文件数量代替职责清晰。
- 健康检查保留仅转发SDK的对象可作为旧测试patch点，但没有生产消费者或自身状态；函数lazy回调保留同一导入／捕获时机，Redis slot等真正资源对象继续保留。文档存储关闭时仍可能通过MinIO存提取资源，这是两个实际存储职责，不能为删除fallback误删该路径。
- 外部会话入口自行生成第二个request_id可支持遗漏中间件的独立测试应用，但生产请求必经RequestContextMiddleware；入口直接使用实际所有者设置的ID，避免日志和响应另起身份。异步队列仍深拷贝请求并由私有Session持有后台写入，不改为复用请求Session；只去单用enqueue转发。
- 继续让反馈引用失败回到原引用可以避免旧数据被拒绝，但finalize_reference_sources实际承担ACL、租户与chunk／document／dataset一致性校验，HTTP400／403不能伪装正常入库。反馈提升到证据时以已验证suite.dataset_id为权威，HTTPException原对象传播且不写入；其他已定义的非HTTP补充失败降级保持，不扩大本批到共享服务重构。
- 保留胶囊existed与optional source_path两个状态可分别说明存在和来源，但二者恒定对应且产生重复判断；改为仅source_path。normal路径优先，normal错误不切换legacy，legacy仍须显式允许raw格式及匹配tenant／owner；不为减少分支删除已有存量读取或原子创建／替换。
- 版本入口保留重复TypedDict与裸dict可以避免提前构造模型，但已有VersionInfo／List／Diff已持有相同外部契约，复用能减少同一结构的维护点；SQL返回的实际整数／datetime和正常JSON输出经对照保持。每个函数复用未执行Query，不新增通用版本仓库或分发器。
- 为解析内容五元组再增加内部record可以具名访问，但已有响应模型已完整持有这些字段和合法缺省；直接填入实际响应，减少一套结构。读取原文件不是另一个权威缓存，只有既定无内容分支才补读；不以精简为由退出已发布能力。
- 死信status改为Enum／Literal或在Query中提前strip／lower会拒绝已有自由筛选，或把ALL／空白all改成原始精确all的特殊语义；保留现有字符串查询。把两个Session并成一个可以少开连接，却会令数据库资源跨越await重试边界，因此只合并无独立职责的prepare转发。
- 提前将全部候选Row构造成输出模型可以少一段最终映射，却会让未入选的nullable时间记录触发整个接口校验错误；输出模型只在最终边界构造。用SQL trim统一两个后端的SHA规范化或改变特殊日期顺序会改变既有group／total结果，因此本次只统一范围与数据组织，不混入规则变更。
- 将三个可选诊断统一进一个safe-call工厂可以少写except，但会隐藏不同依赖与验证边界，且易把KG／index的坏响应也改成None；保留具名边界并补安全日志。继续在调用方重复or 0不能表达真实nullable计数规则，改由模型只对None默认；字段坏类型因此在昂贵指标计算前失败，HTTP通用500保持。
- 使用会先strip再检查max_length的字符串约束，可能让原始空白超长请求从422变为接受；本项目在原Field长度校验后才规范化。将status也统一lower／strip会改变原始all和非processing状态匹配，因此它保留业务helper；不以表面统一混入查询规则修改。
- 解析预览沿用多个Form依赖会继续混淆外部契约，单个模型必须同时包含file，否则当前FastAPI不能正确平铺multipart。只改asyncio.to_thread调用位置不会保证取消时Session已关闭；用明确本地worker与既有等待桥。只给第一段清理加shield仍会在raw task.cancel后跳过第二段，必须由finally保证资源顺序。
- 将可读文档加载改为执行数据库查询的FastAPI依赖会使权限查询提前到Query参数校验之前，改变混合错误的失败顺序；保留普通函数在handler内调用。将详情也套用版本查询会拒绝原来可读取的历史chunk，因此详情保持独立。
- 预览继续用带Form／Query默认对象的dataclass可以避免组件名变化，但把两个HTTP来源和内部配置混在一起，也不满足当前外部Pydantic契约。将所有字段合成一个Form会改变既有8个Query参数；每来源一模型保留实际wire字段。新模型与原生错误呈现差异单列，不新增兼容wrapper。Query范围直接加ge／le虽然常见，却会改变本项目既有400，因此保留实际策略相关归一化边界。
- 保留全部兼容导出可以避免调整旧测试入口，但会继续让装配器承担服务目录职责。实际调用方决定保留范围，无调用名字直接删除。
- 统一重写所有请求模型和可选值处理可以得到表面一致的写法，但会改变 PATCH、表单未提供和正常无结果的含义。本次沿用真实边界，只清理已核验契约上的重复处理。
- 保留普通 Depends 参数类能保留既有查询提取方式，但字段默认值和约束继续散在构造签名与属性赋值中。当前仅一个完整 Query 来源，使用原生 Pydantic 模型并核对实际解析；不把多个模型当成自动平铺，也不增加未知参数禁止规则。
- 把分析的每组筛选参数留在九份入口签名里可使单处字段直接可见，但同样的日期窗口与范围需要重复维护；使用一个内聚schema文件和实际复用模型。必填ruleset的诊断input和两个文档参数顺序按原生模型呈现，不新增错误兼容层。
- 为预览另建配置适配器可以集中动态取值，但现有 `PipelineEffective` 已经提供明确字段。消费者直接使用它，减少一层规则维护。
- 私有异常能由中间件自行转换为响应，但实际 FastAPI 请求解析层会将它先改写为 400，外层捕获没有机会完成预期的 413 转换。当前生产宿主是 FastAPI，读取错误复用框架 HTTP 异常；独立 ASGI 测试挂载对应的异常处理层。

## Consequences

第58–63项将血缘加载按chunk→授权→权限明细／诊断日志展开，无权限仍404且不再读取诊断数据；单用loader和重复空摘要退出，真实summary owner统一处理空记录。血缘固定外层用两个Pydantic响应模型，schema别名保持，动态版本细节仍由原service构造，不镜像其全部嵌套规则。answer的dict／None和schema常量按实际producer消费，去未成立的数据类型伪404与重复500文案。

元数据公共／详情直接构造既有嵌套模型，详情先授权；name依既有品牌要求为Ragvia。唯一producer必提供的gzip／rate_limit／cors不再在响应中回填默认，三个值仍允许各自合法False／空列表。BuildMeta的真实可选构建信息保持。metrics仍使用同一constant-time比较及401／本地账号分支，去Settings字符串重复转换和数学上重复的空digest拒绝。

网络固定输出用内聚Pydantic模型，缺路径selector不再执行结果必空的DFS，其他权重／去重／排序／路径结果保持。20,000边限制输入数量，仍可能产生组合数量的路径；K12／66边／10跳为6,235,301条，现有完整输出契约未在本批增加静默截断或新错误状态。

观测32旧模型和14完整查询、8固定内层归单一领域schema；26响应的148字段按实际normal／disabled／empty／partial／error producer必须存在，不再设伪默认，nullable含义保持。JSON Schema的required／嵌套／UUID格式随之细化；旧测试替身缺键不作为恢复默认理由。trace、快照、外部诊断与自由报告仍按原JSON边界，worker Session、授权、审计／rollback与reconcile幂等状态不变。五个缺必填Query来源的原生422 input由null呈现为参数字典，其余诊断字段和状态不变。

解析Query／multipart／提取schema别名使用原生Pydantic契约，缺file的422只改变input呈现，upload组件改为ParsingDocumentUploadForm。固定parser／subprocess producer的必产出字段直接使用，存量JSON与可选增强边界保留。候选失败返回原被颠倒的tuple改为(error_entry,None)，失败记录和下一候选预算成立；SubprocessCancelled交既有499入口，选中空markdown不混初始内容，失败诊断仍用initial_backend。每个DB worker用with SessionLocal和既有等待桥，重复取消等待线程与会话退出，不改全局managed helper。

第51–56项把治理九字段、用户组两项分页和入库五字段查询放入各自既有schema，已成立的Literal／数值／COUNT／关系容器直接使用。治理原三个响应类搬迁不改字段，用户组成员投影复用OrmModel；真实NULL日期、metadata和已删除document关联仍按原语义处理，权限检查不提前或省略。公开包入口完整复核，leaf只记实际支持范围，不因新增模型推定整文件完成。

readiness缓存使用owner本来保存的payload／status二元组，不再额外返回重复Milvus；public探针只输出ok／status，details仍先检查观测权限。SDK加载在原检查函数的异常边界内，缓存命中不发探针，Redis失效、对象存储与预热检查保持顺序。无状态proxy／兼容转出退出，真正资源slot保留。

入库比较使用已经逐run读取和授权的两个ORM对象，删除第二轮复读及由此产生的空diff成功分支；compare owner仅读取config／stats。重放的关联收集持有2000上限，后续不重复截断；逐文档失败继续、rollback失败传播、取消与finally关闭保持。外部会话去未使用BackgroundTasks注入，后台Session由with关闭；executor.submit失败仍直接传播，不返回accepted。生产request_id只由全局中间件生成；旧测试的独立FastAPI夹具需补同一中间件，不恢复路由兜底。

2026-11-12并行批次中，评估、证据和反馈Query各归现有领域schema，输入的类型／默认／约束和真实JSON边界保持。6组评估及1组证据缺必填参数时，原生422的input从null变参数字典，状态与type／loc／msg保持。反馈请求集合由独立工厂提供，OpenAPI不再展示共享字面量default；闭环两个输出补模型，动态字段继续保留。动态Any中的UTC datetime按Pydantic输出Z，原+00:00表示相同时刻；参数展示次序和新增嵌套导出schema单列，不称完整OpenAPI逐字节不变。

训练导出先筛归档状态再排序／limit，修复旧默认分支在SQLAlchemy构造时抛错的次序；tenant／dataset范围、源内排序／配额、CSV／JSONL字节和套件导出数据保持。反馈引用错误现在明确拒绝而非写入；这是移除错误兜底的实际行为修正。评估生成器直接使用已保证的source_id／reference_chunk_ids，违约交原有failed边界，不再猜旧字段。仅测试调用的旧路由别名、私有helper和散装参数保持退出，测试维护欠项与业务集成未验证范围独立登记。

胶囊ID只在两个入口各规范化一次；私有路径构造信任此值，resolve／relative_to仍阻止符号链接逃逸。载荷读取／结构／tenant／owner验证顺序保持，单用tuple提取包装退出；新建仍O_EXCL，覆盖仍先授权再临时文件原子替换。四个仅本路由使用的Pydantic模型保持内聚，不为目录形式新增小文件。可预期文件／编码／JSON错误保留原500转换，意外实现错误直接交全局处理。

分块读取收敛后由同一helper持有原权限顺序，两个Query模型保留原外部字段和限制。原生OpenAPI保持；缺少必填q时原生422的input由None变为查询字典，状态、loc／type／msg／ctx保持，呈现变化单列。不为旧散装Python调用或错误详情再引入兼容层。两类输入只是对1523行models.py的局部支持，不替代全文审核。

第27项预览输入从两个外部dataclass迁为四个Pydantic契约，公共入口原72对象身份保持并新增4个，入口169行已全文复核；models1498行仍只新增支持而全文pending。原Body_*组件改为具名Form，继承导致字段排列变化；缺必填的error.input由None变为模型字典，by-sha多错误顺序变化，loc/type/msg与字段／默认／媒体类型保持。旧私有参数类和散装Python调用不保留兼容别名。

API 目录由 147 个 Python 文件、59,790 行变为 145 个文件、58,151 行，本次净减少 1,639 行。连接器装配入口从 492 行变为 20 行，文档入口从 413 行变为 76 行。HTTP 输入校验、真实可选字段和资源清理仍按各自职责处理。

本次需要同步两处目录外的实际调用：共享限流实现和配额服务的导入；它们承担共用实现的归属。功能删除、服务层全面重构和本地环境配置整理保持独立。已有相关决定见[API 数据集与管线值归属](2026-11-05-api-dataset-pipeline-owned-values.md)。

运行列表的默认值、原范围、UUID 缺省及错误位置保持；内部 Python 调用应使用当前模型，旧参数类及私有路由补丁不再作为兼容接口。schema 文件只完成本次新增输入契约，其余模型仍需按当前全 app 清单复核；公开一个类型不等于已经审核整个定义模块。

分析的必填ruleset缺失时，原生422诊断input由None变为查询对象，loc/type/msg不变；两个相关OpenAPI参数数组的展示顺序改变。字段及有效值契约保持，但不能宣称错误详情逐字节不变。新的31行契约文件集中五种实际查询输入，公开包保留原对象身份；既有分析／任务owner未在此被重新审核。

分块写入口的旧私有导入不再提供兼容转发。已有两个测试文件仍引用这些名字，按用户要求保留原字节且不执行；这是已披露的测试迁移欠项，不把保留历史测试当作生产别名存在的理由。服务与schema仅完成调用契约核对，仍需各自全文复核。

解析内容的available、空字符串、补读和截断状态沿原契约区分；无需新增响应／内部状态类。Query及响应字段在同一既有模块中，1529行schema仍只做局部支持。旧复杂度测试的私有ACL名和max_chars散装Python调用留待测试迁移，按本轮约束不改、不跑，不增加兼容层。

死信重放仍先授权读取，再await重试，最后独立标记。线程桥的取消政策保留：等待当前worker关闭后传播取消；标记阶段取消不会撤销已经开始的worker。数据库／重试失败保持可见，只有原owner的refresh附属失败按既有日志政策处理。新增Query只是对1541行schema的局部支持，相关服务仍待全文复核。

重复检测保持SQL和scan两条已有路径，PG失败不会切换实现或返回伪造空数据。缺少dataset_id时，原生422的input呈现为查询字典；其余错误位置／类型／消息保持。仅返回项使用现有模型，坏输出继续经通用500入口；1565行schema仍待全文复核。

健康卡的正常值与缺项形状保持；两个业务数据规则集中后，坏内部数据会更早停止计算。语义0关闭不查询内容，正限额空结果仍有原空摘要；不将scorer或SQL失败转换成空数据。optional调用异常新增安全日志，retrieval的内部校验和KG／index的外层校验政策继续分开。136行health schema已全文复核，具体服务owner仍待各自处理。

文档列表的新模型接收实际HTTP来源，内部四个筛选值可直接使用；原参数类和其Python导入退出，旧测试按约束保持原字节，不增兼容别名。原始长度、Unicode lower结果、LIKE通配符、权限和页后数据处理均保持；1591行models.py仍只新增输入增量，全文待复核。

解析预览的正常字段／解析／治理／返回顺序保持，body组件改具名Form，缺失file的原生input呈现变化单列；非法dataset为400，成功协议缺键不再伪装空结果。取消现在等待当前worker并执行两段清理，删除授权按租户相对标记收窄；相关I/O与子进程owner未因此视为全文已审核，managed helper全局问题归其pending项。131行ingestion schema已全文复核，没有新增请求模块。

## Verification

余21份schema和四connector逐文件闭合，文档管线字段改field validator避免污染fields_set；回归PATCH保selected base遗漏项，消融先验证全部变体再写，避免输入400留下已commit无响应run。真实owner AST／原生model和假Session前后证明支持，保持显式清空／replacement边界，不新增数据库失败原子性承诺。报告诊断四真实缺失字段nullable，经exclude_none省略；完整报告及执行gate不变，不靠空串或默认成功隐藏缺失。

25新全文加一既有API两函数增量，四scope独立review及caller/querytimeout窄重审通过；59文件Ruff／format、26源码AST／compile、全app358路径／422路由／671schema、九公共领域owner身份及157完成SHA通过。模型/诊断显示差异明确，真实DB／驱动／队列／前端运行未认证；max_changes只约束返回明细，不能称写入预算已验。

六API工具全文复核后，管线模型输入窄转400，不再把外部无效JSON当500；None和False／0保持，旧sentinel测试不恢复。上传／下载由同一file_io函数持有关闭规则，新取消不能因已有普通错误而被吞。URL与allowlist按HTTPX统一IDNA身份，连接IP不替换HTTP域名，输入解析／编码错误400、DNS／HTTP失败可见。三个独立review及两资源P2窄重审通过；20原资源／9取消／27URL／9下载组合及真实模型与上传owner证明支持修正，六文件Ruff／format／AST／compile、全app358路径／422路由／671schema和132完成SHA通过，未运行应用测试或真实传输。

生产错误仅固定消息，非prod旧200字符诊断可能含输入，结论不扩大为所有环境隐藏值。pipeline证据从旧工具输出补存后核读，不伪称另行重跑；批量override仍是逐项失败，不把其内部分类说成整个请求状态。

七份会话／数据集schema完整审核后，六份原字节符合；tables只补齐真实单表group_by字符串与多表对象联合类型，旧正常分组响应验证失败已离线复现并修正。typed字典不以删诊断或置None掩盖真实形状。precheck允许的六项0值在runner不再被默认覆盖；样本已开启而context/cap为0时拒绝复用旧记录，防止旧样本绕过新选择。该配置会重扫，旧artifacts不删除；服务全文及旧format问题仍pending。

三组独立审查及两处窄重审、原生helper／model／schema、4旧复用轨迹／7受影响／7未受影响证明支持修正。完整app358路径／422路由／671schema只新增group_by字符串文档分支。仅两源码变化、126完成SHA及全文件集合通过，不把一个partial服务算完成；未运行应用测试、SQL、扫描或模型业务。内部同名RAG配置的差异另挂原owner，不因本次API契约符合就宣称已合并。

API81–83以四组独立审查闭合，SCIM保留真实扩展JSON及自有错误协议；设置的六外层响应与用量Query有实际schema owner。状态DB probe复用worker Session，修旧第二Session在query失败时泄漏。889设置断言、1692+38 SCIM及60原生HTTP、用量真实Row／大整数／顺序float对照通过；两callback注解及Query归属发现已纠正，相关函数体不变。完整app冷导入358路径／422路由／671schema通过，未运行handler或应用测试；锁释放／audit／runtime等原尽力策略明确保留，旧测试需迁移而不恢复兼容。

基础入口批次12文件另行全文复核，11份原字节符合，根包去掉固定SDK已不消费的LangChain旧globals补丁；native Conda预载及版本保留。真实SDK getter／model消费者和全appOpenAPI支持删除。五中间件、15基础模型及本地依赖都有实际框架／服务边界，未为产生diff强改。agent包重复补丁仍归其pending owner；[离线规则记录](2026-11-05-offline-retrieval-ltr-owned-rules.md)的当前启动事实同步，不改变CLI隔离决定。

权限列表先做实际User关联再构造最终DTO；外部subject无本地身份时username／email明确required nullable，不用空字符串或合成账号。修复合法成员在补资料前即model_validate报500，其他非法NULL合同不扩大。指纹的rewrite值直接取实际Settings owner，修复读取不存在请求属性的500；不恢复ChatRAGConfig伪字段、不删除输出key。成功指纹参考仅修正那两处owner读取，不能称旧版本真实成功输出。

API75–80通过10文件Ruff／格式／AST3.11／compile及三组独立审查；两个schema全文完成，公共28→29及95→98对象identity保持。75实际内存ORM及原生500→200、权限／last-admin／事务轨迹，76的70绑定／18真实producer／内存ZIP资源，77的8指纹及原500→200，78的13场景／必产出协议，79的3字节／hash输入，80的11假流程均有证据。组合13路径／14操作／47schema，仅两nullable字段和profile三组件文档变化。没有应用测试或真实数据库／删除／检索／模型业务，global managed-session与RTBF ticket持久化不在此认证。

模板列表用各自完整Query，五处提示词租户查询合为一个真实复用点；RAG预览的两入口共用47字段映射，专属参数仍明确。普通元数据worker自有Session并等取消关闭，检索许可继续原owner。三个既有conversation leaf全文复核，retrieval保持170行原字节。相似度五个必产出字段required，真实条件失败字段仍nullable；矩阵键和异常detail由实际producer保证，不设第二套空结果。

API71–74通过10文件Ruff／格式、8完成源码AST3.11／compile及三组独立审查。共同15路径／20操作／29schema仅列表description和五响应required／default文档变化；旧45及现47公共对象身份通过。模板19／16原生Query和真实NULL／AB0／事务差分、预览47参数／真实消息及取消轨迹、相似度42契约均有离线证据。没有运行应用测试或实际数据库／模型／检索／矩阵业务。

管线预览的四个完整multipart输入和治理列表Query归现有schema，普通DB worker自有Session并等待取消关闭；重复同期限清理收敛为一个真实owner。root路由及六个support全文复核，公共68项显式导出可解析，两个大leaf仅新增配套契约仍pending。原生缺必填字段的422 errors[].input采用经现有handler清理的模型字典，区别于旧null；保留原生诊断而不为旧形状增加wrap校验器，状态与type／loc／msg保持。ZIP响应模型校验放在旧异常转换之外，仍归通用500。

API64–70通过12文件Ruff／格式、10变化源码AST3.11／compile和四组独立spec／quality审核。原生23路径／26路由／78schema除四Form组件名称／标题／引用外保持；31Form及14Query、301root值／SQL／事务、4267自动标注、3485能力输出及清洗／记录／映射对照通过。7Session／5清理及旧双期限比较证明取消先等关闭；5秒是协作式期限，不保证终止阻塞线程。未运行应用测试或真实业务I/O，610测试及起点分支／HEAD／暂存保持；全局limiter继续pending。

并行批次58–63的9份完成源码（含一个新领域文件）通过Ruff／格式／AST3.11／compile及三个独立spec／quality复核。root血缘3成功／2拒绝／3answer及2原生序列化、meta4／指标72，图111×8×6=5328实际算法与原生序列化及72请求绑定；观测158Query／28真实producer或ORM序列化／6请求schema及全部148键真实分支；解析17绑定／5别名／3非法别名、候选两失败预算／499一次记录／重复取消等待资源均有隔离证据。六路由合并42路径／44操作／79schema，请求参数与状态集合保持，响应文档及诊断呈现差异单列。没有运行应用测试、真实图大规模枚举、SQL、日志文件、探针、解析器、线程业务／子进程或外部网络。

并行批次51–56通过12文件Ruff／格式／AST3.11／compile和三个独立spec／quality复核。治理29原生Query、60无连接SQL／投影及5错误；用户组18原生Query和权限／audit AST；健康18静态及13纯隔离缓存／失败／权限路径；行业6操作OpenAPI与自由YAML投影；入库12Query／ACL／audit／retry AST；外部会话26同步／异步／header／submit轨迹及4私有Session生命周期对照均通过。六路由组合22路径／26操作／34schema，除Ragvia描述外OpenAPI相同；没有执行应用测试、实际探针、SQL、线程提交或其他业务I/O。

并行批次46–50按不重叠写入范围和精确起点执行，公共导出由主智能体持有。46的24子router对象及完整装配AST保持，51路径／57操作OpenAPI相同；49的15组ID、22组载荷授权、38组存取／验证和6组异常轨迹保持，四个本地模型及两个原子资源函数AST保持，3路径OpenAPI相同。47的306组原生Query／19行为切片、48的32组Query／训练与套件导出字节、50的35组Query／真实响应往返及8组ACL／一致性拒绝均有离线证据。三份独立只读复核通过；未运行Python应用测试或真实业务I/O，检查日志和环境限制见maintenance验证记录。

2026-11-12第45项三文件Ruff／格式／AST3.11／编译、26组原生Query及4路径／12schema完整OpenAPI通过；四组missing诊断input对外变化明确保留。列表56、diff16、激活36、删除24、四组活动／处理中409拒绝及47组错误、86组provenance和四组行加载对照保持，记录器只构造980次SQL、比较提交／回滚调用，不执行真实SQL或索引I/O。公共入口92个旧对象身份保持，新公开后94项可解析；大models.py除新增Query外AST保持，全文仍pending。独立只读复核除已记录诊断表示外无待修项；Python应用测试不改不跑。

2026-11-12第44项两文件Ruff／格式／AST3.11／编译通过；26组原生输入、12组投影、3个适配器与24组错误／取消对照、3路径／17schema完整OpenAPI保持。独立只读审查另核对30组投影，无待修项；未运行Python应用测试或真实业务I/O。

2026-11-12第43项三文件Ruff／格式／AST3.11／编译通过，9组native及1路径／4schema OpenAPI保持。96脱敏／150事件合并排序／6故障／1 NULL日期500对照通过，两个sanitizer／keys／sentinel完整AST与两个输出类序列化schema保持；旧91导出身份与现92解析通过。37行timeline schema已全文复核，独立只读复核无待修项，未运行应用测试或真实业务I/O。

2026-11-12第42项三文件Ruff／格式／AST3.11／编译通过，29native／9无效完整错误及1路径／3schema OpenAPI相同。160组SQL／内存聚合、5故障与大Decimal精度通过；只去新增两个投影标签比对SQL表达式，旧90导出身份与现91项解析、排除新Query的schema AST保持。独立只读复核无待修项；1619行models及真实owner继续pending，未运行应用测试或真实业务I/O。

2026-11-12第41项三文件Ruff／格式／AST3.11／编译通过，24组原生Query和完整4路径／4schema OpenAPI保持，204无body原生规则确认。16组重试／3其他适配／27异常取消对照相同，三handler完整AST与规范化retry body保持；九转出退出，旧89导出身份与现90项解析、除新增类的schema AST保持。独立只读复核无待修项；1599行models与实际服务仍pending，未运行应用测试或真实业务I/O。

2026-11-12第40项三文件Ruff／格式／AST3.11／编译通过；57组native Form、DTO3及纯序列化3／材料化6／治理4／analytics16／错误20／虚拟清理4通过，body组件与2组input展示变化单列。64正常API／9故障／3个UUID400修正／2协议修正／1位置保留及10组实际bridge重复取消验证通过；symlink-loop窄捕获回归已修复。旧88身份与现89解析、五个旧schema AST保持；独立复核无剩余项，未运行应用测试或真实业务I/O。

2026-11-12第37项三文件Ruff／格式／AST3.11／编译通过；53组原生Query完整错误及1路径／10schema OpenAPI保持，7组值将原Body规范化前移。88状态／scope与96筛选排序、6错误、4页验证对照一致，实际纯metadata附加无dirty；旧87对象身份和现88项解析、排除新增类的schema AST保持。独立只读复核无待修项，未运行应用测试或真实业务I/O。

2026-11-12第35项三文件Ruff／格式／AST3.11／编译通过；23组原生Query及完整1路径／10schema OpenAPI保持。冻结旧schema核对parsing94／计数25与八个序列化schema，140语义／2评分失败／120卡片／18主故障／11optional／6导入／3早失败场景和17条安全warning通过。scorer为实际启发式，tokenizer和I/O为替身；旧86导出身份与现87项解析保持，独立只读复核无待修项；未运行应用测试或真实业务I/O。

2026-11-12第34项三文件Ruff／格式／AST3.11／编译通过；24组原生Query及完整1路径／4schema OpenAPI保持，3组缺dataset_id的input变化单列。128组路径／生命周期／深度与6组错误对照相同；两个模型递归schema、7组校验／序列化及独立children默认验证通过，旧85导出身份与现86项解析保持。小schema29行已全文复核，树服务继续pending；独立只读复核无待修项，未运行应用测试或真实业务I/O。

2026-11-12第33项三文件Ruff／格式／AST3.11／编译通过，23组原生输入、完整1路径／5schema OpenAPI与56组PG固定结果／72组scan／10组失败／5组日期对照保持。SQL只规范化WHERE合取顺序；未入选坏数据不提前校验，4组缺dataset_id的input变化单列。旧82对象身份与现85项解析通过，timestamp AST保持；独立只读复核无待修项，没有运行应用测试或真实业务I/O。

2026-11-12第32项三文件Ruff／格式／AST3.11／编译通过；23组原生查询（7无效）及完整1路径／9schema OpenAPI保持。240组SQL／内存ORM响应、28组权限与异常组合相同，真实纯metadata附加不产生字段dirty历史；旧81导出身份、现82项解析及排除新类后的schema AST保持。独立只读复核无待修项，未运行应用测试或真实业务I/O。

2026-11-12第31项三文件Ruff／格式／AST3.11／编译通过；39组原生输入及完整2路径／7schema OpenAPI相同，原prepare主体、mark与重放顺序AST保持。233组SQL构造与内存响应、4组列表错误、33组重放及2阶段实际bridge重复取消对照相同；旧80导出身份和现81项解析通过，独立只读复核无待修项。未运行应用测试或真实DB／队列／文件／模型业务I/O。

2026-11-12第30项三文件Ruff／格式／AST3.11／编译通过；14组原生Query解析及完整2路径／3schema OpenAPI保持。metadata16／扩展名180／内存读取147／内容280／DOCX56／权限异常28组离线对照相同，DOCX尾部和截断函数AST保持。旧79导出身份及现80项解析通过，独立只读复核无待修项；未运行应用测试或真实文件／DB／渲染业务I/O。

2026-11-12第29项限定单文件Ruff／格式／AST3.11／编译通过；六参数与owner调用、五handler完整主体AST保持。原生5路径／7schema OpenAPI相同，44组适配器记录与4组reembed响应对照通过；独立只读复核无待修项，未运行应用测试或真实写入。

2026-11-12第28项三文件Ruff／格式／AST3.11／编译通过，78组原生输入与完整3路径／6schema OpenAPI核对；1008组无DB连接的SQL构造与内存响应、48组权限／缺失／异常组合前后相同。21组缺必填q的input呈现变化保留；旧76导出身份保持，现79项可解析。独立只读复核无待修项，未运行应用测试或真实业务I/O。

2026-11-12第27项三文件Ruff／格式／AST3.11／编译通过，62组原生解析包含42无效输入；30组input展示与6组错误顺序差异明确记录，8个Query／全部Form字段及媒体类型一致。配置184／raw192／实际内置chunk-response96／缓存291／API组合64组离线对照通过，公共入口72对象身份保持；没有运行应用测试、真实数据库、文件发送／解析进程或网络。

2026-11-12第14项完成三文件Ruff／格式和Python3.11 AST／编译，88组原生参数解析与51组离线适配器对照验证值、权限顺序、导出内容、PNG状态及错误边界；独立复核无正确性发现。局部11路径／2schema除两个parameters数组顺序外相同，8种缺失必填诊断input差异明确记录；旧公共导出67个对象身份保持，新增五个真实模型。没有调用真实SQL／Redis／渲染器／HTTP／后台任务或Python应用测试；新文件已登记，源码总范围因此增加一个。

2026-11-12 第 11 项以原生 FastAPI solve_dependencies 和无 I/O 的上下文／Session 覆盖核对 17 组查询，包含 8 组无效输入；默认值、边界、重复／额外参数、错误内容与位置保持。六个 handler 主体及返回注解、五个其他签名相同，局部 OpenAPI（5 路径／7 schema）相同。除新增 Query 模型外现有 schema AST 一致，旧公共导出 35 个对象身份保持；三文件 Ruff／格式和 Python 3.11 AST／编译通过，独立只读审查无待修项。没有执行 handler、Python 应用测试、真实 HTTP／数据库／队列或生命周期；旧历史测试结果不作为本步重跑证据。

v1 逐文件复核的第一步只处理包入口和必要的 main.py 调用方。路由构造体 AST 与改动前完全相同；冷导入包不加载业务路由或应用配置，重复调用工厂返回同一个缓存对象。422 个应用路由对象的顺序／契约及完整 OpenAPI（358 路径、637 schema）前后相同。Python 测试不改、不跑，其他 82 个 v1 文件保持本步起点字节；逐文件清单与环境限制见 docs/maintenance/style-unification/api-v1-review.csv 和 verification.md。

416 条路由的顺序、路径、方法、处理函数、响应模型、标签、状态码及响应状态码集合与改动前一致。路由清单 SHA-256 为 `4a9003d7a0dc3a2f8ac6b0e19c62e0c0d02560b7dba3a3b71f1ed0bee2fec452`。OpenAPI 成功生成 356 个路径和 637 个模型；中间件包独立导入不加载 Settings 或 JWT。全部 API 文件通过 Python 3.11 语法解析；这项检查只证明语法，不代替该版本的运行验证。

最终聚焦的 20 个测试文件共 173 项测试通过，覆盖管线输入、真实零值与关闭值、入库预览、上传并发与锁交接、连接器、限流和请求上下文。Ruff 检查、154 个文件的格式检查以及本次范围的 diff 检查通过。

请求体限制的 18 项定向测试通过。其中真实 FastAPI 分块 JSON 和 multipart 两项回归先复现原实现错误地返回 400，再确认调整后返回 413；另验证零值／负值关闭限制、按需接收、声明长度低报，以及响应已经开始时不再发送第二个响应。后者交给框架明确传播错误，不能把已经发送的状态码改成 413。

运行验证使用隔离测试配置：`ENV=test`、专用测试签名键和 `EVIDENCE_POST_RERANK_PROVIDER=none`，没有修改本机 `.env`。真实数据库、对象存储和完整应用启动不在本次运行验证中。

记录格式检查通过 147 篇记录，归档检查通过。记录树检查报告十条历史失效链接，目标涉及已经不存在的 FAISS、Chroma、解析模型退出记录和直接取值契约记录；错误列表没有本篇的新链接。这些历史记录没有在本次 API 修改中顺带改写。

扩展检查另记录九个失败用例，来自不同轮次，不能当作完整测试集的结果：

- `tests/test_document_upload_object_storage.py` 的六个持久化测试替身缺少必需的文档、租户或数据集标识。
- `tests/test_api_service_complexity_batch2.py` 的历史文件路径断言固定使用 Linux 路径字符串，Windows 返回本机路径分隔符。
- `tests/test_retrieval_query_and_runtime_shards.py` 向检索门面绑定已经不存在的 `emit_stream_event`。
- `tests/test_document_governance_options.py` 的一个调用形态断言要求单独的 `options` 参数，现有入库服务仍传入展开的治理字段。

已将三个相关服务模块以及评估 API 的全部函数体与 HEAD 进行 AST 对照，确认上述实现未由本次改动改变。这些扩展失败保持可见，后续应根据各自真实契约修正测试或实现。
