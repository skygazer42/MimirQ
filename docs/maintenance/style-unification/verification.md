# 验证记录

## 干净基线（2026-11-02）

生产代码未修改时运行，提交为 `77b6adc1`。

| 检查 | 真实结果 | 归属 |
| --- | --- | --- |
| Ruff check app tests scripts main.py | 通过 | 原有检查范围 |
| Ruff format --check app tests scripts main.py | 815 个文件需要排版，942 个已符合 | 历史排版差异，含随后排除的上游代码 |
| 扩展为所有自研 Python 的 Ruff check | ci/download_verified_wheels.py 两处 T201 | CLI 有意向终端输出，改为精确文件豁免 |
| pytest -q -n 4 --dist worksteal | 2,994 通过、15 跳过、32 失败、16 收集错误，356.80 秒 | 基线失败见单独清单 |
| 用户认证、SAML 端点、配置快照样板测试 | 17 通过 | 首批切片基线 |
| 前端 ESLint | 通过 | 原有规则的干净基线 |
| TypeScript | 通过 | 干净基线 |
| UI/API checks | 全部通过 | 含严格 API 类型漂移基线 |
| Vitest | 127 个文件、420 个用例全部通过 | 干净基线 |
| 初次 Prettier 检查 | 704 个文件需要排版 | 新选定规则下的历史差异，后续分批处理 |
| 前端生产构建 | 通过，退出 0，bundle budget 通过 | 干净基线；有上级锁文件与 webpack 缓存提示 |

## 批次 1：工具与规则

- Ruff 范围覆盖全部 1,724 个自研 Python 文件；第三方和历史迁移明确排除。
- 原来的 docs 排除项会误伤 scripts/docs 下三个自研工具，已移除该宽泛排除。
- ci/download_verified_wheels.py 的终端输出是命令行契约，T201 只豁免这个文件。
- ESLint 配置加载、配置文件自身 lint 均通过；新增组件声明和 type 偏好规则。
- Prettier 使用根目录唯一配置，锁定 prettier 3.9.10 与 eslint-config-prettier 10.1.8。
- 依赖锁文件仅增加这两个开发依赖的 23 行记录，没有升级现有应用依赖。

## Python 纯排版提交

- 795 个自研文件重新排版，929 个原本符合；第三方和历史迁移未排版。
- 逐一解析全部 1,724 个自研 Python 文件，排版前后完整 AST 的 SHA-256 全部相同，差异为 0。
- Ruff check . 与 Ruff format --check . 均通过，覆盖 1,724 个文件。
- 认证、SAML、配置快照的扩大样板测试：32 通过（9.29 秒）。
- 本提交只更新排版。覆盖清单里的语义审核仍为 pending，后续按业务批次处理。

收集错误涉及缺少 huggingface_hub、trio、llama_index、nltk、pymilvus、torch、tencentcloud 等依赖。
未为本地风格重构启动解析器、模型或完整容器栈。32 个失败还包含平台、既有行为断言和并发用例，
不能统一归因于依赖；后续触及相应领域时逐项核对。

完整原始输出保存在本次执行工作区的 logs/；本目录保存可审阅的结果与用例清单。

## 批次 2：认证与数据集样板

- 用户服务改为模块函数，移除静态方法外壳；认证及 SAML 调用方一并迁移，配置由调用方明确传入。
- 400、401、403、404、409 和脱敏 500 回归通过；租户选择保留当前成员优先及旧 NULL 标记的排序。
- 认证范围 8 个测试文件、34 个用例通过；此前扩大范围 21 个文件、127 个用例通过。
- 数据集具名组件、共享 type、重复流水线映射及已知字符串类型的重复归一化统一。
- 初次加载、成功空列表、失败、后台刷新失败的状态分开；后台刷新失败保留已有缓存列表，并可原位重试。
- 6 个 Chrome 浏览器场景连续 3 轮通过（18/18）：成功、空、加载、失败重试、缓存列表保留、搜索排序刷新与创建入口。
- 已亲自查看真实加载、失败及缓存列表保留截图；沿用基线 Ocean 界面与现有语义颜色。
- 前端 128 个测试文件、421 个单元用例全部通过；TypeScript、UI/API 检查和样板文件 ESLint/Prettier 通过。
- Tailwind 原 ESM 配置仍使用 require，原生 Node ESM 回归先失败，再以正常插件 import 修复后通过。
- 数据集纯排版提交前后编译出的 JavaScript AST 相同，比较时只归一化括号和尾逗号。
- 浏览器默认 Chromium 缓存版本缺失，使用本机已安装 Chrome；开发首轮编译曾造成成功列表用例超时，预热后基线复跑通过。
- 浏览器 API 数据在浏览器边界模拟；未启动 PostgreSQL、解析器或模型服务。前端上报代理的本地 8000 端口连接拒绝属于未运行的 API 观测入口，未改业务逻辑为其兜底。
- 覆盖清单仅闭合本批实际审核文件；其他文件的语义审核仍为 pending。

## 原分支迁移与第三批回归（2026-11-02）

- 按用户最新要求迁回 `E:/MimirQ` 的 `codex/local-account-registration`。9 个已有提交通过快进保留，未产生合并提交；第三批 118 个待提交文件逐一校验 SHA-256 后迁移。
- 原工作区 1 处已跟踪文件修改和 1,625 个未跟踪文件逐一校验，全部原样保留；暂存区未变更。原有未跟踪文件没有纳入重构提交或此次检查范围。
- 在迁回的工作区运行 22 个认证、租户组、权限、配置及配额测试文件：134 通过、1 跳过，耗时 77.02 秒。跳过项是既有 `test_complexity_batch6.py` 中依赖 torch 的测试。
- 本次测试在第三批 Settings 读取替换之后执行；此前租户组的 22 通过结果在该替换之前，不能替代本次结果。
- 迁回的全部 118 个 Python 文件 Ruff check 和 Ruff format --check 均通过。完整输出位于本计划执行工作区的 `logs/branch-migration-*.log`。
- 第三批仍在进行；本次没有运行全量 pytest、前端构建或全项目验收，覆盖清单未因此标记完成。

## 第三批首轮提交（2026-11-02）

- 租户组服务与配置读取清理分开提交；原工作区历史残留和原有 `document.py` 修改未纳入提交。
- 提交前重新运行 22 个测试文件：134 通过、1 因缺少 torch 跳过，耗时 32.78 秒。118 个相关 Python 文件 Ruff 检查和格式检查通过。
- 111 个模块的 1,139 处已声明 Settings 读取改为明确属性访问；不移除值的业务默认策略。109 个仅涉及配置读取的模块逐一核对 AST，与精确替换后的提交前版本完全一致；另两个模块的租户组调用调整单独审阅。
- 覆盖清单仅闭合租户组服务、租户组路由、共享异常和新增回归测试；仅替换 Settings 读取的模块保留逐文件语义审核待办。


## 第三批：数据集服务（2026-11-02）

- 三个纯静态服务类迁为模块函数；文档、连接器、检索和 API 调用方直接依赖 `app.services.dataset_service`。同类结构与内部简化按用户要求归并提交。
- 最终 125 个相关 Python 文件（73 个生产文件、52 个既有测试引用文件）Ruff check 与 Ruff format --check 均通过，125 个文件语法解析通过。未执行 Python 测试。
- 122 个调用文件的 AST 与精确引用迁移一致；534 处可静态确定的调用参数与模块函数签名匹配。服务内部逻辑及两个特殊 fixture 的必要同步单独审阅，未将其算作纯结构等价。
- 组 ID 来自 `list[UUID]` schema 或 UUID ORM 列；成员 ID 来自 `list[str]`。删除重复转换，保留去空、去重、租户校验、组数量限制和审计。
- 已核对本地 owner 引导的开关、环境、认证模式、默认租户、请求来源和回环限制；创建与更新的 commit、refresh、rollback 顺序保持原样，现有 HTTPException 及错误转换保留。
- Git 跟踪的生产 Python 文件中旧三个类符号已无引用；既有测试只保留独立 stub。两个特殊 fixture 已核对 patch 的实际服务所有者，运行时行为仍未验证。
- 覆盖清单仅关闭已完整审阅的数据集服务；仅迁移引用的生产文件仍待完整模块审核。测试引用同步按用户暂缓测试的要求登记，不能视为测试质量审核。
- 自动结构审查所需 TruffleHog 未在当前 PATH 找到；本轮使用源码、AST、签名和 diff 审阅，不能宣称结构审查工具通过。最终日志位于计划工作区 `logs/task-3-dataset-final-*.log` 及 `task-3-dataset-final-static.json`。

## 第三批：权限、JWT 成员供应与配额（2026-11-02）

- 数据集类别已经提交为 `2c16dedf8`。本批仅整理 RBAC schema／路由／服务、JWT 成员供应、token 配额和配额服务，共 6 个生产 Python 文件；请求状态载体经完整源码审核后登记已符合。
- 6 个文件 Ruff check、Ruff format --check 和语法解析通过。21 个公开函数的参数形状保持一致，33 个文件中的 118 处可确定调用匹配签名，没有未解析的动态参数调用。
- 4 个 RBAC 路由的装饰器与 HTTPException 构造 AST 相同；schema 的外部角色校验保留。另行核对 nullable ORM 字段、最后管理员判断、锁顺序、组／数据集／文档权限清理、审计与 commit／refresh 顺序。
- JWT 成员供应的已验证身份入口、用户长度限制、租户存在性与已有成员分支保留；审计哈希只计算一次。数据库工厂类型明确，commit、异常 rollback 和 finally close 的既有 best-effort 政策保持原样。
- QPS 的 6 个结果字段由同一构造函数生成；只在配额禁用或已定义的失败降级时使用允许默认值，启用态显式使用 limiter 返回值。同步和异步检查／执行入口在归一化 await 与 check 方法名后的 AST 相同。
- 429、Retry-After 和带证据的后端失败策略各只有一份实现；fail-open、可配置 fail-closed、503、令牌消费边界、Redis 前缀／TTL／burst 策略和缓存配置指纹保留。3 个 SQL 聚合函数的执行体 AST 与修改前完全相同，仅移走重复局部导入。
- 嵌入任务继续使用 TenantQuotaExceededError；上传配额的文档数／字节数检查顺序、超限载荷及数据库异常策略保留。版本化 `mimirq.tenant_token_quota.v1` 字段保持原样。
- 覆盖表只关闭本批完整审核的 7 个生产文件，其他模块仍保持待审核；新增一篇权限与配额决定，并与已有数据集决定互链。
- 本批未新增、扩写或运行 Python 测试，没有启动业务模块、数据库或外部服务。静态检查不证明运行时回归通过；自动审查仍因既有 TruffleHog 依赖缺失而未运行，没有重复尝试或安装新工具套装。
- 静态核对证据：计划工作区 `logs/task-3-permission-quota-static.json`；完整修改前快照和核对脚本位于 `permission-quota-refactor/`。

## 第三批：SCIM 协议入口（2026-11-02）

- 完整审核 `app/api/v1/scim.py`，清理已声明 Settings／ORM 字段的重复转换；用户审计哈希只计算一次。外部 JSON 的布尔、成员和字段解析继续由协议入口负责。
- 三个仅使用一次的校验、写入和审计包装并入成员 PATCH；保留独立的操作解析，并由 GET 与 PATCH 共用组详情响应。模块由 39 个函数、1,030 行减为 36 个函数、973 行，未新增模块或业务抽象。
- Ruff check、Ruff format --check 和语法解析通过。14 个公开函数参数形状、13 个路由的参数及装饰器保持一致；4 个文件中 99 处可确定调用匹配签名，无动态参数调用待解。
- 42 处 SCIM／HTTP 错误构造的 AST 多重集合保持一致；协议常量、allowlist 缓存声明、查询过滤／排序／删除条件保持一致。成员写入与业务异常转换、外部 PATCH 校验及审计调用经明确归一化后 AST 一致。
- 13 个路由展开本地辅助函数后的事务及服务调用源码顺序一致；该检查不证明条件可达性或运行时事务结果。另行阅读 nullable ORM 字段、POST／PUT 的 externalId 缺失与清空区别、active 解析、成员去重与数量上限。
- SCIM 开关、多 token 轮换、sha256 与常量时间比较、IP allowlist 的拒绝策略、绑定租户和原协议 media type 保留；既有组审计提交及停用处理的 best-effort 范围保留，没有新增兜底或重试。
- 未新增、扩写或运行 Python 测试，未导入业务模块或启动外部服务；运行时行为未验证。完整修改前快照位于 `scim-refactor/`，静态结果位于 `logs/task-3-scim-static.json`。本次是单模块内部整理，未新增重复的决策笔记。


## 第三批：配置校验与热加载（2026-11-02）

- 完整审核配置声明、启动校验、环境读取、运维快照与热加载 5 个生产模块；其中 3 个调整，2 个已符合。运行时依赖直接从实际所有者导入，删除 14 项导入后注入；配置模块保留三个现有公共函数导出。
- 删除 8 个私有取值包装，132 处已声明字段的动态读取改为属性访问；按声明类型清理重复转换，保留原有 or 默认值及零值处理。校验模块的 57 个函数均有明确参数和返回类型，没有新增模块、Context 或规则解释器。
- Settings 完整类 AST 保持一致，覆盖 1,316 个字段及既有 27 段调用顺序。53 个原有校验函数经明确替换规则规范化后 AST 一致；4 个迁移函数及 8 项常量原样匹配。83 处范围包装调用的返回值均未被消费，439 项配置导入仍可用，313 处可确定校验调用匹配签名。
- 外部 JSON、URL、UUID、生产鉴权、可信租户来源、SCIM、CORS、MinIO、反序列化限制及 model_fields_set 语义保留；错误和警告随完整函数体比较核对。检索规则及其包初始化没有运行时反向配置依赖。
- 热加载直接使用必填快照属性与键；检索指纹实际是字典，因此保留原字符串表示参与 24 位组合哈希。两个函数体经已审阅的属性、键、命名与 None 判断规范化后 AST 一致；schema、结果字段及哈希输入顺序保留。快照脱敏与协议数值转换继续保留。
- 静态比较在首次改写后抓到一处表达式替换丢失括号的问题，已在提交前修复，全部函数比较重新通过。临时改写器与验证脚本仅留在 ignored 执行工作区，没有作为生产工具加入仓库。
- 最终 5 个模块 Ruff check、Ruff format --check 和语法解析通过；新增配置职责决定的目录、格式及归档检查通过。完整证据为执行工作区 logs/task-3-configuration-static.json 及 configuration-refactor/ 修改前快照。
- 按用户要求未新增、扩写或运行 Python 测试，未导入业务模块或启动数据库、解析器、模型；源码检查不能证明运行时回归通过。覆盖表只关闭这 5 个已完整审核模块，通用入口与后续批次继续执行。

## 第三批：通用 API、请求中间件与应用装配（2026-11-02）

- 完整审核 15 个保留生产模块，并删除无调用、导入、动态命名或注册的 error_handlers 模块及五个通用校验包装；5 个未修改模块登记已符合，其余 10 个登记已调整。原有 document.py 修改保留。
- JWT／请求头的 UUID 校验留在原入口，内部直接传递 UUID；日志输出字符串，请求状态直接保存 UUID。4 个公开认证／租户依赖签名、24 处错误响应构造和 5 个完整错误边界函数体保持一致；18 处确定认证调用匹配签名。
- 33 个认证／租户／异常函数经明确的类型转换与 UUID 表示规则规范化后 AST 一致。无效 claim、无效缓存回退、400／401、可选数据库线程工作及其既有 best-effort 政策保留，没有统一原有入口差异。
- 7 个完整中间件经已审阅规范化后 AST 一致；37 个函数的参数名和默认值不变。TokenBucket、RateLimiter、RedisRateLimiter 三个完整类 AST 原样匹配。上传流累计、413、429、Retry-After、安全头只补缺项、Redis fail-open、锁和线程边界保留。框架类型来自本地已安装 Starlette 源码。
- 完整 main.py 装配经明确配置、类型标注与目录字符串规则规范化后 AST 一致，覆盖 43 处声明配置读取与 30 个顶层函数；路由、中间件、启动与关闭顺序保留。两个探针补返回标注时显式 response_model=None；依据已安装 FastAPI 源码核对原推断行为，未运行 OpenAPI 导出。
- 最终 15 个保留模块 Ruff check、Ruff format --check 与语法解析通过；决定记录目录、格式及归档检查通过。覆盖清单仍精确对应 3,637 个最终跟踪路径：43 已调整、8 已符合、953 登记保留、2,633 待语义审核。
- 未新增、扩写或运行 Python 测试，未导入应用模块或启动外部服务；运行时回归未验证。证据位于执行工作区 common-api-refactor/ 及 logs/task-3-common-api-static.json、task-3-middleware-static.json、task-3-app-entry-static.json。

## 第三批：身份、令牌与 JWT 组同步（2026-11-02）

- 完整审核 10 个模块：5 个调整、5 个已符合。签发、校验与初始管理员直接使用声明的 Settings、字符串和 ORM 类型；租户模型只修正身份说明，列、约束、默认值保持一致。
- JWT 外部 claim、JSON 形状、逐跳 HTTPS、issuer、kid 和不可信 URL 校验保留；最多六把签名密钥、过期立即失败、kid miss 刷新、异步锁、有界 stale 和缓存列表复制策略保留。诊断解析与 bcrypt 验证继续采用原有失败契约。
- 组同步直接读取模型保证的名称和主键，已有组名用集合判重，去掉无作用别名与不可达的空主键分支。非空组名必在查询结果或 flush 后的新对象中；主键与成员 group_id 均不可空。外部 claim 的长度、去重和数量限制、租户条件、只增不删、失败限频及 commit／rollback／close 顺序保留。
- 10 个完整模块经已审阅的精确替换规范化后 AST 一致；35 个函数参数名与默认值、31 处错误构造及 jwt.encode／decode 调用保持一致，16 个文件中 69 处可确定调用匹配签名。临时核对器的一处跨函数别名规则已限定作用域后重新通过，未为通过检查更改生产策略。
- 最终 10 个模块 Ruff check、Ruff format --check 与语法解析通过；未新增、扩写或运行 Python 测试，未导入业务模块。运行时回归未验证。证据位于执行工作区 identity-refactor/ 与 logs/task-3-identity-*.log、task-3-identity-static.json。

## 第三批：数据库与共享运行资源（2026-11-02）

- 完整审核 9 个模块：6 个调整、3 个已符合。数据库池与 HTTP 选项直接读取声明配置；get_db 明确返回 Session 迭代器。数据库重导出层有明确的模块重载约束，保留单例、SQLite 参数分支及会话回滚与关闭顺序。
- HTTP 池保留四个连接槽、两把实际使用的锁、内外部请求头隔离、延迟创建和关闭顺序。删除没有调用、patch 或注册引用的旧请求头方法与锁；直接读取请求上下文的必填键及 httpx 响应状态码。请求重试仍按原网络异常、5xx／429、Retry-After、jitter、连接释放和最终抛错策略执行。
- Redis 类型只在 TYPE_CHECKING 下导入，延迟加载与可选依赖边界保留；已验证为正整数的租约 TTL 直接传递，2 段 Lua 原样匹配。锁、禁用开关、空 URL、失效重建、异常回调及各调用方选择的抛错／降级策略保留。
- 根路径的单次包装就地展开；路径穿越校验、环境覆盖与外部字符串适配保留。异步桥的线程、shield、重复取消、等待工作完成和异常消费经完整源码审核后保持不变；代理环境与数据库 facade 同样登记已符合。
- 9 个完整模块经精确规则规范化后 AST 一致，49 个函数参数名与默认值保持一致；扫描 1,799 个跟踪 Python 源码，删除的三个私有名称没有残留。Ruff check、format --check 与语法解析通过。未新增、扩写或运行 Python 测试，未导入业务模块；运行时回归未验证。证据位于执行工作区 resource-refactor/ 与 logs/task-3-resources-*.log、task-3-resources-static.json。

## 第三批：健康探针与观测（2026-11-02）

- 完整审核 10 个模块：9 个调整、健康响应 schema 原样符合。就绪缓存用明确的字段类型，命中返回载荷和状态码，未命中返回 None；保留现有字典重置方式、热加载缓存键、TTL、公共最小响应和管理员详情权限。三个路由声明及完整响应 schema 的 AST 原样匹配。
- 探针的配置对象允许缺省字段，有实际轻量调用对象与既有源码用例支持，因此保留相应 getattr 默认值；数据库工厂明确产生 Session。数据库版本检查、Redis 必需与可选区别、客户端失效重建、向量和对象存储状态及预热失败策略保持原样。
- 日志上下文的 Token、日志工厂和 ASGI 指标回调类型明确；移除声明配置的重复转换。日志清理、可选 trace 补充、路由模板与 sentinel 标签、finally 中的计数和 gauge 更新顺序保留。OTEL 的启用失败与 instrumentation best-effort 仍按原范围处理；Sentry 继续禁止默认 PII 采集。
- 费用事件直接使用本模块构造的必填字段与已归一化数值，保留 unknown 标签、外部事件适配、六位舍入、排序及原版本化 schema。脱敏只清理本地计数与已规范化 mask 的二次转换；正则、Luhn、对象递归和失败时掩码输出保持一致。流事件继续保留有状态 emitter、去重、线程调度与队列满策略。
- 10 个完整模块经明确替换规则规范化后 AST 一致，57 个函数的参数名与默认值不变；脱敏三个失败处理函数及流事件发送实现原样匹配。Ruff check、format --check 与语法解析通过。未新增、扩写或运行 Python 测试，未导入业务模块；运行时回归未验证。证据位于执行工作区 observation-refactor/ 与 logs/task-3-observation-*.log、task-3-observation-static.json。

## 第三批：其余核心工具（2026-11-02）

- 完整审核 12 个模块：10 个调整、2 个原样符合。utils 只有 parse_csv 被五个仓库模块导入，删除其余 14 个无引用的应用内部包装，338 行缩到 22 行；parse_csv 原函数体保留。扫描全部 3,637 个跟踪路径，没有被删除工具的导入或正则私有别名残留；未发现动态导入、通配导入或注册使用。
- 连接器密钥加解密共享一份字段遍历，分别传入实际转换函数；完整旧遍历先核对仅函数名称不同，再与新共享实现核对 AST。顶层及 auth 字典的复制、缺失与显式 None 区别、任意 JSON 值转换、密钥派生、当前密钥后最多五个旧密钥的轮换顺序及 InvalidToken 行为保留。
- 迁移引擎、DDL 列表和 token 编码器缓存类型明确；141 项 SQL 字面量及 token 完整算法 AST 原样匹配。迁移各语句独立事务、既有历史默认租户与启动 best-effort 保留；离线 tiktoken 降级、CJK 估算和供应商响应形状适配保留。
- 正则移除无外部引用的私有转发和内部重复转换；保留用户模式、替换与 flags 校验、数量与长度限制、嵌套量词判断、错误字段、编译错误、可调用替换的引擎选择及超时策略。安全随机采样用单个范围判断；53 位熵、随机调用次数与 Fisher-Yates 顺序保留。
- 常量命名空间有类别和覆写含义，保留其形式；OpenAI URL 归一化来自 SDK／配置边界，保留字符串适配和后缀顺序。代理环境合并及文档版本键只移除已声明字符串的重复处理，去重、版本选择与回退顺序不变。
- 12 个完整模块按明确规则规范化后 AST 一致，49 个保留函数参数名与默认值不变；Ruff check、format --check 与语法解析通过。未新增、扩写或运行 Python 测试，未导入业务模块；运行时回归未验证。证据位于执行工作区 utility-refactor/ 与 logs/task-3-utility-*.log、task-3-utility-static.json。

## 第三批：数据集分类与成员关系（2026-11-02）

- 完整审核分类服务、路由、schema 与模型 4 个模块：2 个调整、2 个原样符合；数据集主路由仅同步 3 处服务调用，仍待完整语义审核。纯静态类迁为模块函数，CRUD 名称明确所属分类，全部实际调用方同步迁移，不保留旧类转发壳。
- 分类分配直接消费 schema 已校验的 UUID 列表，保留首次出现顺序去重、同租户存在性校验、先校验后替换及提交顺序。分类关系的非空 UUID 列和唯一约束保证查询结果，移除重复解析、空 ID 过滤与重复判重。
- 树构建明确接收对象序列，字典／属性字段适配继续保留；新建 schema 节点后的排序、深度和父映射直接使用保证的字段。nullable 成员角色仍按空字符串拒绝，CRUD 权限、同租户父级、已有环拒绝、非叶删除限制及附加计数失败回零政策保留。
- 13 个服务及帮助函数参数名、默认值保持一致；完整函数、分类路由和数据集调用模块经明确规则规范化后 AST 一致。8 处服务调用匹配签名，5 个路由声明与完整 schema／模型 AST 原样匹配；全仓跟踪 Python 源码没有旧类引用残留。5 个涉及文件的 Ruff check、format --check 和语法解析通过。
- 现有数据集决定记录原地补充分类契约，没有另建计划或重复笔记。未新增、扩写或运行 Python 测试，未导入业务模块；运行时回归未验证。证据位于执行工作区 category-refactor/ 与 logs/task-3-category-{static,ruff,format}.log、task-3-category-static.json。

## 第三批：元信息、构建标识与依赖诊断（2026-11-02）

- 元信息路由、响应 schema 和依赖诊断 3 个模块完成审核，运维快照同步采用共享构建来源，新增标准库 build_info 模块。管线 provenance 只迁移 SHA 读取，文档处理领域语义审核仍待完成。
- 公开元信息、运维配置与 provenance 中五份相同函数体合并成两个共享函数，原样核对 AST；环境变量名称、读取优先级、先选中后去空白、无值 None 和调用时读取保持一致。元信息管理员校验是既有 patch 接口，保留函数与权限调用；公开字段没有增加诊断详情。
- 诊断移除无引用的私有时钟及已声明布尔、客户端版本的重复转换，MinIO 状态直接读取其全部返回分支保证的键；缺少 elapsed_ms 的 disabled 分支继续返回 None。数据库与 Redis 的版本适配、短超时、SQL 和清理、可选依赖延迟导入、逐项 best-effort、错误截断及探针顺序保留。
- 5 个原有完整模块经明确移动与表达式规则规范化后 AST 一致，5 份移出函数原样匹配；22 个保留函数的参数契约未变。6 个涉及文件的 Ruff check、format --check 和语法解析通过。临时核对器修正了规范化 AST 的复用和版本转换作用域后通过；生产代码未为检查修改策略。
- 覆盖清单精确对应 3,638 个跟踪路径；新增模块有明确的三处实际使用方。配置决定原地同步共享所有者，未新建重复计划。未新增、扩写或运行 Python 测试，未导入业务模块或启动依赖；运行时回归未验证。证据为 metadata-refactor/ 与 logs/task-3-metadata-*.log、task-3-metadata-static.json。

## 第三批：审计查询、清理与权限快照（2026-11-02）

- 审计路由、清理服务、事件服务与模型四个原有模块完成审核，新增所属 schema 模块。八个 Pydantic 类原样迁移，路由仍导入原名称；七个路由的路径、依赖、参数与响应约定保持一致。summary 补返回类型时显式 response_model=None，保留原响应模型推断结果。
- 列表、导出与清理复用同一份七条件筛选，数据库参数使用原生 datetime。三条删除路径使用已有删除函数；去重、租户限制、数量上限、顺序、dry-run、commit／flush／rollback 及 best-effort 政策保留。
- 修复清理候选的 tuple-only 适配：实际 SQLAlchemy 单列结果是 Row，现直接解包原生 UUID。依据已安装 sqlalchemy/engine/row.py 与 orm/query.py 的源码契约核对；这项是缺陷修复，未声称与原错误行为等价，也没有运行实际数据库清理。
- 权限快照使用实际 ORM 列和枚举，移除已验证整数／布尔值的重复转换与内部缺省值。敏感字段、哈希、八类顺序、分页游标、版本化 schema、UTC 时间表示和 gzip 规则保留；事件写入函数的原始截断和失败处理函数体未变。
- 八个 schema 完整 AST、38 个参数契约、七个路由声明及错误／权限调用、输出字段、筛选表达式和删除事务顺序静态核对通过；33 个文件中 123 处可确定调用匹配签名，无未解析动态参数。五个文件的 Ruff check、format --check 与语法解析通过。整理中发现并修复一次多行查询括号语法错误，随后重新运行完整本批检查；未将中间失败状态提交。
- 覆盖清单只关闭四个原有模块与新增 schema；审计候选行取舍单独记为缺陷决定。未新增、扩写或运行 Python 测试，未导入业务模块或启动数据库、解析器与模型。运行时回归未验证。证据位于执行工作区 audit-refactor/ 与 logs/task-3-audit-*.log、task-3-audit-static.json。

## 第三批：租户隔离与组输入边界（2026-11-02）

- 完整审核组请求 schema、组模型、组权限模型、RLS 生成器和授权指标五个模块；四个调整，一个原样符合。组模型仅修正已过期的说明，所有列、复合外键、唯一性与级联规则保持一致。
- 三个 Pydantic after 校验器直接使用已声明的字符串和列表；去空白、首次出现顺序去重、名称非空、255 字符限制及错误文本保留。200 项上限继续由原 Field(max_length=200) 执行，删除上限之后不可达的重复截断。
- RLS 生成直接消费字符串，保留名称分段、空表名跳过、默认 schema／admin role、标识符双引号转义、字面量单引号转义、SECURITY DEFINER 与 search_path。十段 SQL 插值 AST 原样一致，没有运行 SQL 或调整数据库策略。
- 授权计数直接读取已声明布尔配置，标签仍限定在原有限集合并将未知值归 unknown；Counter 名称、标签和调用顺序保留。移除只有一个调用的启用包装，没有引入新配置或指标。
- 五个完整模块经明确的精确源码规则规范化后 AST 一致；16 项 schema 字段、三个 after 声明、七个保留函数参数契约及错误文本通过核对。Ruff check、format --check 与语法解析通过。未新增、扩写或运行 Python 测试，未导入业务模块或执行 RLS。
- 覆盖清单精确对应 3,640 个路径：87 个已调整、23 个已符合、954 个登记保留、2,576 个待语义审核。证据为 tenant-boundary-refactor/ 与 logs/task-3-tenant-boundary-*.log、task-3-tenant-boundary-static.json。

## 第三批：设置模型、环境更新与服务状态（2026-11-02）

- 完整审核设置入口，26 个请求／响应模型和所属规则迁入 settings schema；路由直接导入原类名。188 项字段、默认工厂、范围和 before 校验经原始 AST 核对；LLM base 仍在构造时读取当前设置，MinerU 归一化保留单一维护点。
- 以声明类型清理 31 处 getattr 缺省属性访问、136 处同类型转换和 79 处等价空默认值。六项原有 Field 约束保证的重复夹取和不可达拒绝退出；请求原有 422 校验不变。非零默认、尚未约束的非负数值归一化、显式字段更新及敏感值掩码保持原样。
- 环境解析只接收真实的字符串，数字格式错误仍返回原设置；原子文件替换、锁、NUL／换行／长度限制、审计、写入和缓存／客户端重置顺序保持一致。HTTP 状态直接读取 httpx Response；JSON 载荷、SSRF、DNS pinning、权限和动态请求状态边界保留。
- 四个只用一次的包装退出：数值序列化在映射处直接执行，数据库／Milvus 状态按原顺序就地检查。三个无响应模型入口显式 response_model=None 后补返回类型，避免 FastAPI 推断变化。按 Revise 核对入口分组、局部依赖和命名，保留状态失败政策与可选依赖延迟导入。
- 完整路由模块在明确规则规范化后 AST 一致；84 个保留函数参数契约、四个路由及 26 个模型核对通过。六个跟踪源码文件中 239 处可确定调用匹配签名，27 处 schema 构造的参数名有效；Ruff check、format --check 和语法解析通过。没有新增、扩写或运行 Python 测试，没有导入业务模块或启动依赖，运行时回归未验证。
- 覆盖清单精确对应 3,641 个路径：89 个已调整、23 个已符合、954 个登记保留、2,575 个待语义审核。证据为 settings-api-refactor/ 与 logs/task-3-settings-{static,ruff,format-check}.log、task-3-settings-static.json。

## 第三批：共享权限、导航与聊天配额（2026-11-02）

- 完整审核共享权限、导航、聊天配额和路径安全；删除无继承、调用或注册的通用 CRUD 基类，其八个未用方法退出。三个预设路由的编辑检查直接由 RBAC 提供，角色继续只转小写、不去空白，原 403 载荷保留。预设模块其余业务仍待完整审核。
- 导航外部输入继续归一化、拒绝未知值并按产品顺序返回；设置保存直接使用 schema 已校验的列表。两个单次包装退出；环境配置读取仍使用归一化入口。聊天配额声明六项字段，保留三种返回、数据库数值适配、时间窗、SQL 和失败放行政策。路径安全源码保持原样。
- 7 个保留模块 Ruff check、format --check 与语法解析通过。109 个函数参数形状、12 个路由声明、角色规则和完整规范化模块 AST 核对一致；扫描 1,801 个跟踪 Python 源码，33 个文件中的 320 处确定调用匹配签名，没有已删名称残留。检查器跳过原函数说明字符串后通过，生产角色策略未为此改动。
- 覆盖表精确匹配 3,640 个跟踪路径：91 已调整、24 已符合、954 登记保留、2,571 待语义审核。已有权限决定原地补充；未新增、扩写或运行 Python 测试，未导入业务模块；运行时回归未验证。证据位于执行工作区 shared-policy-refactor/ 及 logs/task-3-shared-policy-static.json。

## 第四批：分块预设与文档访问（2026-11-02）

- 预设路由由 304 行减至 189 行；四个请求／响应模型移至 schema，五个数据库操作移至所属服务。现有私有名称直接导入服务函数以保留既有 patch 引用；未增加包装。列表 limit 的 1–200 校验留在 Query，非法 preset ID 保留 404，非法 payload／查询 dataset ID 保留原 400 格式。
- 两个纯静态文档权限类改为六个模块函数，全部三个实际调用模块同步。API 的 UUID 列表直接使用；连接器配置仍解析字符串，保留去空白、去重、数量上限、同租户校验、先校验后替换和已有异常指标。
- 批量 ACL 行声明真实 nullable 字符串、UUID 与时间字段；四处非空 UUID 查询直接解包。单文档与生命周期检查直接读取 ORM 字段；去掉四个无意义包装和无调用的 _check_member 兼容参数。权限 SQL、成员检查、未知模式拒绝、未分配文档规则、排序、指标、授权写入及审计事务顺序保持原样。
- 12 个 Python 模块 Ruff check、format --check 与语法解析通过；四个预设类 AST 和四个完整 ORM 模型原样匹配。七个完整业务模块经明确规则规范化后 AST 一致，58 个保留参数契约及六个路由声明保持一致；扫描 1,803 个跟踪及本批新增 Python 源码，43 个文件中的 156 处确定调用匹配签名，没有动态调用待解或旧 ACL 类引用。
- 权限领域文档同步真实服务与函数名称，既有数据集决定原地补充职责和字符串输入边界。覆盖精确对应 3,642 个跟踪路径：98 已调整、27 已符合、954 登记保留、2,563 待语义审核。连接器 ACL 只迁移调用，仍保持 pending；文档 schema 原有空行修改保留。
- 未新增、扩写或运行 Python 测试，未导入应用或启动数据库、解析器及模型；运行时回归未验证。完整基线和核对器位于执行工作区 document-access-refactor/，结果位于 logs/task-4-document-access-static.json。

## 第三批：SAML 交换、桥接与重放（2026-11-02）

- 完整审核三个 SAML 服务；数据库参数明确为 Session，身份解析返回 User 与字符串组列表。声明的配置直接读取，保留提供方 JSON 的形状校验与外部字段适配；清理内部重复字符串、整数和布尔转换，组 claim 使用已经过滤的非空列表。
- 桥接与重放的过期清理仍在原锁内，用同一个 monotonic 时间判断；清理后直接读取有效项，移除同一条件的二次校验。原 1～60 秒桥接期限、重放最低期限及配置零值取 300 秒规则保留；没有改变锁、Redis NX、四次碰撞重试和 Lua GET／DEL 单次消费。
- XML parser、签名验证、issuer／destination／status、audience、subject confirmation、时间条件和 replay TTL 七个完整函数 AST 原样匹配。两个数据模型、Lua、认证路由与请求／响应 schema 保持一致；40 处 HTTP 错误构造和 29 个保留参数形状静态核对通过。
- 三个完整模块经明确替换规则规范化后 AST 一致；扫描 1,803 个跟踪 Python 源码，七个文件中 52 处可确定调用匹配签名，无动态参数待解。Ruff check、format --check 与语法解析通过；一次替换缩进错误在提交前修正后重新核对全部本批文件。
- 仅作模块内部整理，没有新增业务层、包装或重复决定笔记。按用户要求未新增、扩写或运行 Python 测试，未导入业务模块或启动依赖；运行时回归未验证。证据为 saml-refactor/ 与 logs/task-3-saml-{static,ruff,format-check}.log、task-3-saml-static.json。

## 第四批：入库运行记录与状态通知（2026-11-02）

- 入库运行服务的五个无状态入口改为模块函数并位于私有帮助函数之前；四个生产调用文件同步，上传直接依赖所属服务。两个仅用于获取服务的整模块参数退出，原类没有兼容外壳。
- 明确七处 IngestionRun 参数及声明的 ORM／Session 契约；去除内部重复字符串和整数转换、重复统计副本、不可空 document_id 的过滤及同结果异常分支。外部 JSON 的形状与数值适配、元数据 UUID 解析和时区时长降级继续保留。
- 创建、绑定、状态通知与 intake 收尾维持各自失败策略。15 个锁、查询、去重和观测边界帮助函数，以及两个完整公共事务流程的 AST 原样一致（仅统一迁移造成的说明字符串缩进）；行锁顺序、幂等、唯一约束、提交／回滚与指标顺序、统计截断、空批失败和 required 抛错保留。flush 中非重复 IntegrityError 的既有返回规则本次未调整。
- 九个相关 Python 模块经明确规则规范化后 AST 一致；两个 ORM 模型字节原样保持。302 个保留参数形状、九个路由声明与 55 处 HTTP 错误构造核对通过；扫描 1,803 个跟踪 Python 源码，19 个文件中的 577 处确定调用匹配签名，无动态参数待解。Ruff check、format --check 及三个已有决定文档检查通过。
- 已有并发夹具仅补齐六处 config 字段、无操作 Session.flush 及旧服务引用；三个测试文件的用例、装饰器、参数与断言 AST 原样一致。没有新增、扩写或运行 Python 测试，没有导入业务模块、执行数据库事务或启动解析器与模型；运行时行为未验证。
- 覆盖清单只关闭完整审核的服务与模型，调用大文件保持 pending，两个测试文件按用户要求登记保留：3,642 个路径，101 已调整、28 已符合、956 保留、2,557 待审核。既有数据集／文档服务决定原地同步；原文档 schema 修改与未跟踪文件保留。证据位于 ingestion-run-refactor/ 与 logs/task-4-ingestion-run-*.log、task-4-ingestion-run-static.json。

## 第四批：文档元数据与批量操作（2026-11-02）

- 完整审核元数据服务、单文档修改与批量操作。原运行时元数据模块直接更名为 document_metadata_service，承接原路由中的四个用户 patch 函数；运行时图像／表格／块统计规则保留。上传、列表与详情直接导入同一所有者，没有增加重叠模块或旧入口转发壳。
- 两个路由模块退出动态 documents 装配器，直接调用实际 ACL、元数据、管线标识与单文档操作；三个 pending 判断归入现有生命周期服务。nullable 元数据、外部 JSON、任务与进度兼容、标签及备注限制、批量 best-effort、租户条件和两阶段业务／审计事务顺序保留。
- 去掉已由请求 schema 保证的空字典兜底、布尔／整数转换、字段集合缺省访问与不可达空列表返回；批量重试复用原有 HTTP 错误分类，公共入口位于帮助函数前。修复批量重新入库错误 await 同步 patch_document_pipeline 的既有缺陷，后续异步 retry 仍 await。这是行为修复，未声称与原 TypeError 等价。
- 迁移阶段 13 个原函数体 AST 原样核对；最终 15 个完整模块在明确迁移与简化规则下 AST 一致。311 个参数契约、17 个路由声明、86 处 HTTP 错误构造通过核对；扫描 1,803 个跟踪 Python 源码，92 个文件中 1,124 处可确定调用匹配签名，无动态参数待解。原有 231 条测试断言、用例参数和装饰器保持原样；只同步旧 import／patch 与同步假函数。
- Ruff check、format --check、diff --check 及三个决定文档检查结果见本批日志。按用户要求没有新增、扩写或运行 Python 测试，没有导入应用或启动外部依赖，接口运行时行为未验证。原文档 schema 的用户修改字节不变。
- 覆盖清单精确对应 3,642 个路径：104 已调整、28 已符合、957 保留、2,553 待审核；六个生产调用文件仅完成明确迁移，仍为 pending。已有决定原地更新，核对证据位于 document-metadata-refactor/ 与 logs/task-4-metadata-*.log。

## 第四批：文档列表、详情与读取视图（2026-11-02）

- 列表、统计的数据集可见范围与三个视图的生命周期筛选归到现有 document_access；逐份核对原查询分支后复用，不增加查询服务文件。各入口的成员检查、租户条件、数据集与文档 ACL、列表 count／稳定排序／分页顺序保持原样。processing 的特殊去空白小写匹配保留，其余 status 仍按原值筛选。
- 列表和重复文档查询先呈现入口，去掉 11 个参数转存变量和两个单次帮助函数；明确 ORM Query、SQL 表达式、Row、UUID 与返回类型。详情直接读取 ORM 元数据，管线帮助函数移到顶部导入；版本筛选、chunks_loaded 与分块顺序保持一致。
- MinerU 服务已保证七个状态字段，API 不再二次填 pending／零值。目录树直接使用已声明类型，保留深度夹取、可空路径、JSON 字段筛选和排序；统计保留 PostgreSQL SUM 所需的数值转换。重复文档保留 SQL 失败后的既有扫描、历史 JSON 适配与时间戳降级。
- 11 个完整模块经 62 条明确规则规范化后 AST 一致；59 个保留参数契约、七个路由、十处 HTTP 错误、两份数据集谓词及三处生命周期分支核对通过。扫描 1,803 个跟踪 Python 源码，91 个文件的 725 处确定调用匹配签名，无动态参数待解；五个边界模块字节不变。原有 91 条断言、用例及参数保持原样，只同步一个 patch 目标。
- Ruff check、format --check、diff --check 通过；没有新增或运行 Python 测试，没有导入应用或启动服务，运行时回归未验证。覆盖对应全部 3,642 个跟踪路径：111 已调整、29 已符合、958 保留、2,544 待审核。原文档 schema 用户修改保留，处理／队列和其余领域仍待继续；证据见 document-read-views/ 及 logs/task-4-read-views-*.log。

## 第四批：文档处理、重试与队列调度（2026-11-02）

- 状态、取消、重试与删除直接调用现有文档 ACL、生命周期、管线身份、解析器、对象存储及索引通道所有者；去除 `document_processing.py` 对 `app.api.v1.documents` 的动态反向依赖和整模块 `Any` 参数。上传、批量上传、URL 入库及重试共用 `app/api/utils/document_dispatch.py` 的调度实现。
- 任务 ID、队列启用与必需分支、空队列返回差异、状态提交与回滚、取消后的 best-effort abort、有限 JSONB 扫描、对象路径权限映射及对象存储临时文件 finally 清理保持原策略。队列配置读取与 ARQ 的 job/status 使用声明类型；worker 边界的 UUID 字符串化与选项快照保留。
- 完整核对 12 个 Python 模块的规范化 AST、309 个参数契约、7 个路由、64 个 HTTPException 构造、1,285 处静态绑定调用及 378 条既有断言；未发现未解的静态调用。两个原调度实现与共享所有者的对应完整分支已按 AST 核对。
- Ruff check、Ruff format --check、语法解析和 diff --check 通过。按用户要求未新增、扩写或运行 Python 测试，没有导入应用或启动队列、数据库、解析器及模型；运行时回归未验证。ARQ JobStatus 枚举在本机已安装库源码中确认使用小写 wire value。
- 覆盖表现为 3,643 个路径：116 已调整、29 已符合、961 按要求保留、2,537 待审核。测试文件只同步已删除所有者的 import／patch，既有用例和断言不变。原有 `app/api/schemas/document.py` 修改保留。静态快照及验证器位于忽略的执行工作区 `document-processing-dispatch/`。

## 第四批：Pipeline Options 请求转换（2026-11-02）

- `PipelineOptionOverrides`、legacy keyword merge 和 `DocumentPipelineOptions` 到 `PipelineOptions` 的适配从 `documents.py` 移到 `app/api/utils/pipeline_options.py`。手工入库、上传、文件预览和分块预览的五处调用直接依赖该所有者；既有 documents 类型名称由同一类直接重导出。
- 完整核对 7 个修改前模块 AST，并逐项比较迁移后的完整转换实现、17 个字段及默认值。schema 解析、override 顺序、None 过滤、生产错误脱敏、81 个 HTTP 错误构造、4 组路由声明与 response_model 保持一致。两个测试 fixture 的 patch 指向新函数所有者；125 条既有断言、用例签名和装饰器不变。
- Ruff check、Ruff format --check、语法解析和 diff --check 通过；tracked Python 源码不再引用旧转换函数。按用户要求未运行 Python 测试，运行时回归未验证。

## 第四批：批量文档生命周期（2026-11-02）

- 四个禁用／启用／归档／取消归档路由共用一个逐项状态更新函数；保留成员校验、文档写权限、按需生成单次批量时间戳、审计字段与动作、成功计数及条件提交。
- 批量删除直接调用现有文档生命周期服务，并显式使用路由原有的权限与成员约束。404 仍记入 not_found，401／403 仍记入 denied，其他异常仍向上传递。五个路由的路径、HTTP 方法、参数和 response_model 未变。
- 完整核对该模块规范化 AST：五个路由声明与参数保持一致，删除实现仅迁移到直接服务调用；其余模块内容 AST 原样不变。统一状态函数的四种字段／动作映射、单独一份审计调用、逐文档 HTTPException 分类和仅有更新时提交均静态核对通过；模型中的 disabled_at 与 archived_at 列声明已确认。
- Ruff check、Ruff format --check、语法解析和 diff --check 通过；按用户要求未运行 Python 测试，运行时回归未验证。没有触及用户 schema 修改或历史未跟踪文件。

## 第四批：可写数据集选择（2026-11-03）

- 将 `_resolve_writable_dataset` 的实现移入 `dataset_service.resolve_writable_dataset`；文档、手工入库、上传、URL／HTML 入库和连接器的 6 处生产调用直接使用该所有者，删除 documents 与 connectors 聚合层的转发。
- 指定数据集仍执行 tenant 限定查询和写权限检查；缺省时仍先 ensure_member，按 created_at 升序选择首个可写数据集；无可写项时仍以同一角色集拒绝或创建 ONLY_ME 默认集。原错误构造 AST 与事务来源未改变。
- 完整核对 10 个修改前模块规范化 AST；移动后的函数体与原函数在所有者及局部名称归一化后相同。10 个路由声明、81 个 HTTP 错误构造、162 条既有测试断言和 54 个测试用例保持不变；6 个调用按服务签名核对，所有旧函数名引用清零。
- Ruff check、Ruff format --check、语法解析和 diff --check 通过。按用户要求没有运行 Python 测试，默认数据集创建的运行时事务未验证。

## 第四批：手工分块与 Preview 图片所有权（2026-11-03）

- 将 15 个图片引用解析、文件查找／读取、owner sidecar 校验与提升、legacy 文档引用验证、MinIO 上传及 markdown URL 重写 helper 移入现有 `document_preview_utils`。documents route 保留 rewrite 函数的直接重导出；手工分块入口改为直接依赖 preview、pipeline、identity、lifecycle 与 dataset 所有者，不再动态导入整份 documents 模块。
- 服务的既有图片正则、大小和 inline image 数量边界、digest 去重、本地与 MinIO 分支、owner scope、403／422 错误、失败时跳过上传策略和资源关闭行为均按原函数体核对；MinIO 图片错误日志沿用 `api.documents` logger。为避免 utility 与 legacy lookup 的现存正则导入循环，只在归属校验函数中局部导入 legacy 查询。
- Ruff check、Ruff format --check、语法解析及 diff --check 通过；手工路由完成规范化 AST 与所有者检查，preview 图片测试 patch 已指向真实 utility。57 条既有断言和用例定义未变。
- 按用户要求没有运行 Python 测试、导入应用或连接存储；运行时验证未做。更新覆盖表中的手工路由与测试同步结论，较大的 preview utility 与 chunk preview 其他职责继续保留待审。

## 第四批：文档资产认证与响应（2026-11-03）

- 下载、preview image、image-url 的请求 tenant/account 解析移入 `document_assets`；ACL 直接调用 `document_access_service`，对象存储直接依赖现有 store。删除资产路由对 documents module 的动态解析及整模块参数。
- header auth 的匿名 opt-in、JWT header-only bearer 解析、tenant 优先级／冲突拒绝、403／404 隐藏 ACL、下载路径租户 containment、304 与 Range 返回、minio stat/upload 错误和 no-store 响应头保持原逻辑。asset error constants 与既有 root import 名称保持相同。
- 完整核对 asset module AST、七个 request/cache helpers、五个错误常量以及三个路由；现有资产鉴权测试的用例、装饰器和断言保持原样，patch 指向新的 route/service owner。
- Ruff check、Ruff format --check、语法解析与 diff --check 通过。没有运行 Python 测试或启动外部依赖，runtime behavior 未验证。

## 第四批：URL 入库请求 schema 所有权（2026-11-03）

- 将 `UrlUploadRequest` 从 `documents.py` 移到现有 `app/api/schemas/document.py`；`documents.py` 直接重导出旧名称，上传路由与七个连接器模块改为直接导入 schema。九处连接器构造点不再通过字符串解析从路由模块取得请求类型。
- `UrlUploadRequest` 完整 class AST 与 HEAD 中的原定义一致；字段、`extra="forbid"`、解析器和分块策略默认值不变。现有连接器配置测试只把 fake constructor patch 从动态 owner 移到 `connectors_drive_files.UrlUploadRequest`，断言未改。
- Ruff check 对 11 个 Python 文件通过，10 个文件 Ruff format --check 通过；schema 文件仅因保留的原有首行空行未通过文件级格式检查，去除该行的内存副本通过格式检查。diff --check 与决定记录 tree／format checks 通过。
- 按用户要求未运行 Python 测试、未导入应用；Pydantic 运行时 schema 与上传流程未验证。schema 和连接器文件保持待文件级语义审核。

## 第四批：连接器执行映射归属（2026-11-03）

- 队列服务是 connector ID 执行映射的唯一所有者；`connectors_runs` 路由直接调用该 resolver，不再维护重复的九项 dispatcher 名称表。原 HTTP 400 和队列 `False` 的 unsupported ID 处理保持不变。
- `ConnectorRun.connector_id` 在 ORM 中为非空字符串，worker 的公开入口参数也是 `str`；去掉两处 `str(connector_id or "")`，保留 `.strip()` 及大小写匹配方式。队列 resolver 仍在实际执行时延迟导入 connector 聚合器，以保留分拆模块的 helper 初始化。
- Ruff check、Ruff format --check、语法与 diff --check 通过；静态引用扫描确认 API 调用同一 resolver，worker 入口仍调用相同服务。没有运行 Python 测试或导入应用，连接器完整执行流程未运行。

## 第四批：上传 pipeline 配置所有权（2026-11-03）

- `pipeline_options` utility now owns the multipart pipeline JSON parser and chunk overlap validation next to the existing schema adapter. `documents.py` keeps direct exports for the parser, validator, constant and override type.
- `document_upload` directly imports ingestion policy and governance profile resolution, parser/chunker factories, pipeline merge/effective resolution, `PipelineOptions`, pipeline metadata helpers and identity functions. Its request parsing keeps the same unset tokens, form length limit, Pydantic schema and production-safe 400 detail; rule selection, override merge, parser defaults and integrated-strategy boundary are unchanged.
- Preview and chunk preview call the utility parser directly; the preview route retains its local documents import for separate parsing/governance helpers. Nine existing pipeline patch bindings in the upload concurrency test now target `document_upload`; test cases and assertions are unchanged.
- Ruff check/format, parser/validator AST comparison, error-message comparison, route signatures and diff check passed. Python tests and application imports were not run; runtime pipeline behavior remains unverified.

## 第四批：上传提交确认读取（2026-11-03）

- `_fresh_session_document_exists` 直接导入 `DBDocument`，以 `Callable[[], Session]` 表达 session factory 并调用 SQLAlchemy `Session.get`。删除从 `documents` 路由动态取模型以及对 `get`／`query` 的形状探测；factory 注入保持不变。
- session 创建或查询异常仍记录 warning 并返回 `None`，因此不会基于未知状态删除远端对象；成功创建后的 close 仍 best-effort。`False`、`True`、`None` 三类结果进入的对象清理分支不变。
- Ruff check、Ruff format --check 和 diff --check 通过。未运行 Python 测试或应用流程；运行时行为只做源码契约核对。

## 第四批：上传文件名与路径归一化所有权（2026-11-03）

- 文件名校验、路径段处理、Windows drive/FakePath 归一化、`..` 折叠和上传 key 上限迁到现有 `app/api/utils/upload.py`；原 error detail 与各函数 AST 保持一致。`documents.py` 继续直接导出旧 helper 和常量。
- 文件上传、批量 metadata map、staging path、文档预览和分块预览直接导入实际 utility。`document_preview` 仍从 `documents.py` 读取其他 parse/governance helper；只移除 sanitizer 对该聚合模块的依赖。测试只把三个 sanitizer 与 19 个上传保存 helper 的 patch 指向调用模块。
- Ruff check/format、AST 比较、diff --check 通过。已有 route、错误状态、source path 和文件名限制按原函数体保留。按用户要求没有运行 Python 测试或导入应用，上传与预览运行时未验证。
