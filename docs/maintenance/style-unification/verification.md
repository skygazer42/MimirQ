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

## 第四批：Batch precheck 资源所有权（2026-11-03）

- Staging link/copy and cleanup use `os`/`shutil` directly; scan rows use `DBDatasetPrecheckScanRun`; isolated scans use `SessionLocal` plus `run_dataset_precheck_scan`; policy suggestions use `apply_ingestion_policy_suggestion`. The three helpers no longer receive the documents module.
- Hardlink fallback to copy, staging-root containment, pending-row commit/refresh order, background-thread scan, failed-row update/rethrow, outer best-effort continue behavior, policy-suggestion 409 handling and cleanup remain in the same order. Scan/policy warnings retain the `api.documents` logger name.
- Ruff check/format and diff check passed. Three existing test fixtures now patch the upload module's scan and policy owners; precheck `SessionLocal` patches follow the direct binding. No Python tests or application imports were run; full precheck integration remains unverified.

## 第四批：文档去重查询所有权（2026-11-03）

- Four tenant-scoped duplicate query helpers moved from `documents.py` to `document_dedup_service`; the commit-conflict lookup also uses its declared `DBDocument` input. `documents.py` retains the old function names as direct imports, while `document_upload` calls the service owner.
- The four query bodies match their previous AST. Tenant/dataset/archived filters, updated/created ordering, JSONB fast path, legacy content/file SHA keys, 5,000-row cap and Python scan fallback remain unchanged. Conflict handling still runs after rollback and returns the same found duplicate.
- Existing upload fixtures patch the direct lookup owner; the conflict fixture patches both the initial route binding and service lookup used after commit failure. Test declarations and assertions are unchanged. Ruff/format/AST/diff passed; no Python tests, application imports or database calls were run.

## 第四批：上传 ORM 模型所有权（2026-11-03）

- Batch document construction, single-file construction and batch-ingestion finalization now use the imported `DBDocument` model directly. `_build_batch_document` no longer accepts the documents module solely to construct the ORM row; batch finalization keeps the same tenant/document predicates and commit sequence.
- Four existing concurrency fixtures patch `document_upload.DBDocument` at the same construction owner. Route declarations and model field values are unchanged. Ruff check/format and diff check passed; Python tests and database calls were not run.

## 第四批：上传提交确认读取（2026-11-03）

- `_fresh_session_document_exists` 直接导入 `DBDocument`，以 `Callable[[], Session]` 表达 session factory 并调用 SQLAlchemy `Session.get`。删除从 `documents` 路由动态取模型以及对 `get`／`query` 的形状探测；factory 注入保持不变。
- session 创建或查询异常仍记录 warning 并返回 `None`，因此不会基于未知状态删除远端对象；成功创建后的 close 仍 best-effort。`False`、`True`、`None` 三类结果进入的对象清理分支不变。
- Ruff check、Ruff format --check 和 diff --check 通过。未运行 Python 测试或应用流程；运行时行为只做源码契约核对。

## 第四批：上传文件名与路径归一化所有权（2026-11-03）

- 文件名校验、路径段处理、Windows drive/FakePath 归一化、`..` 折叠和上传 key 上限迁到现有 `app/api/utils/upload.py`；原 error detail 与各函数 AST 保持一致。`documents.py` 继续直接导出旧 helper 和常量。
- 文件上传、批量 metadata map、staging path、文档预览和分块预览直接导入实际 utility。`document_preview` 仍从 `documents.py` 读取其他 parse/governance helper；只移除 sanitizer 对该聚合模块的依赖。测试只把三个 sanitizer 与 19 个上传保存 helper 的 patch 指向调用模块。
- Ruff check/format、AST 比较、diff --check 通过。已有 route、错误状态、source path 和文件名限制按原函数体保留。按用户要求没有运行 Python 测试或导入应用，上传与预览运行时未验证。

## 第四批：批量上传 session 所有权（2026-11-03）

- `_process_saved_batch_upload` 与 `_process_live_batch_upload` 移除未使用的 `documents_module: Any` 参数；`upload_documents_batch` 直接调用现有 `app.core.database.SessionLocal` 创建每个 worker 使用的 session。
- 同步更新两处批量入口和 live-to-saved 转发；路由声明、并发限制及 worker 的 session 清理顺序不变。批量入口不再动态导入 documents 路由聚合模块。
- Ruff check、Ruff format --check、AST 语法解析与 diff --check 通过；没有运行 Python 测试或导入应用，批量上传运行时未验证。

## 第四批：上传重复文档重试所有权（2026-11-03）

- 上传路由直接调用 `document_processing.retry_document_processing`；commit acknowledgement 不确定时使用现有 `SessionLocal`；处理中 duplicate 的 409 文案归入 `document_dedup_service`，`documents.py` 保留同名直接导出。
- 更新四个现有并发流程 fixture 的 retry patch 目标；重试参数、权限检查、409 文案、rollback／提交确认及对象清理顺序不变。URL 上传的 documents 路由调用仍单独待审。
- Ruff check、Ruff format --check、AST 语法解析与 diff --check 通过；没有运行 Python 测试或导入应用，重试和提交确认运行时未验证。

## 第四批：URL 与 connector HTML 来源入库所有权（2026-11-03）

- URL 上传与本地 HTML 入库共用的来源解析、管线策略、metadata、配额、dedup、持久化和处理调度迁到 `document_source_ingestion`。`document_upload` 和 connectors 直接调用该 owner；`documents.py` 保留入口、请求 schema 和相关数据类型的直接兼容导出。
- `LocalHtmlIngestRequest` 移到文档 schema。dedup constraint、identity match、integrity-error 判断与 persisted-duplicate 异常由 `document_dedup_service` 统一持有；原 409、SSRF 校验和功能开关状态、tenant/write 检查、quota 次序、commit/rollback、对象及临时文件清理、queue/inline 路径按原 AST 保持。
- 49 个移动定义 AST 相同；schema class AST 相同；`upload_document_from_url` 的路由参数、装饰器和响应配置不变。Ruff、格式、AST 语法与 diff 检查通过。只同步现有 patch 目标，没有运行 Python 测试、导入应用或连接存储。

## 第四批：预览流程直接依赖（2026-11-03）

- 分块预览直接调用 parsing `run_subprocess_worker`，原文预览也直接使用同一 parsing owner；两者都直接调用现有 `governance_processor`，日志保留 `api.documents` category。位置标记来自 `parsing.artifact_stats`；分块输入归一化和 chunker 参数过滤 helper 移到 `document_chunk_preview`。
- 移除分块预览 5 个内部 helper 的 `documents_module: Any` 参数、所有转发及 endpoint 局部聚合器导入；原文预览不再向 parse、governance 或错误转换 helper 传递模块对象。缓存锁、disconnect 检查、subprocess timeout/cancellation、治理结果和临时目录清理顺序保持不变。
- 五个分块预览 helper 与位置标记 AST 相同；两条公开路由签名和 decorator 不变。现有 subprocess/governance fixture 的 patch 指向实际调用模块，断言未改。Ruff、格式、语法与 diff 检查通过；按用户要求没有运行 Python 测试或导入应用。

## 第四批：Chunk-write owners（2026-11-03）

- `document_chunks_write` 直接导入 ORM models、`Indexer`、ACL、审计、`settings` 与 index-audit helpers；chunk 查询、写权限、strictness、结果序列化、drift persistence 和 reconcile queue helpers 从 `documents.py` 移到实际写路由模块。`documents.py` 保留直接兼容导出。
- 六个路由的参数、decorators 和 response metadata 保持一致；12 个移动 helper 的 AST 与原实现匹配，active-pipeline resolver 与 index-audit service body 相同。Vector/BM25 尝试、commit/rollback、audit 与 drift reconciliation 顺序不变。
- 更新三组既有权限、chunk vector 和 drift fixture 的 patch owner；用例与断言未改。Ruff、格式、语法和 diff 检查通过；没有运行 Python 测试或连接数据库/索引服务。

## 第四批：Connector worker ID contract（2026-11-03）

- `ConnectorRun.connector_id` 是 ORM 中声明的非空 `String(80)`。`connector_run_job` 直接读取并 `.strip()`，保留未知 ID 的 `unsupported_connector_id` 失败状态；移除 `getattr`、`str` 和空串默认转换。
- Ruff check、格式和语法检查通过。未运行 Python 测试或 connector queue 集成。

## 第五批：索引向量写入 owner（首个切片）

- `app.services.indexing.vector_writer` 统一持有 Milvus 模式判断、shadow writer 配置与缓存、embedding-space hash、双写和 dataset-scoped runtime 异常。`indexer.py` 与 `chunks.py` 直接调用该 owner；移除 `indexer.py` 中重复的 shadow writer 实现，并将四处旧异常工厂调用改到共享定义。
- shadow hash 失败时记录 warning 并停用可选 shadow writer；主向量写入仍保持成功路径，不再将空 hash 写入 shadow metadata。外部 embedding 与 Milvus adapter 的既有 best-effort 降级保留，主向量写入的 retry 顺序不变。
- Ruff check、Ruff format --check、`git diff --check` 及 owner 引用扫描通过。未运行 Python 测试、应用导入或数据库／向量库调用；运行时行为未验证。三份文件的覆盖状态只记录本切片，文件级审核仍待完成。

## 第五批：Reranker factory 错误边界

- `reranker_factory` 使用 `RerankCandidate` 的声明字段并在一次遍历中构造 identity 结果；分数字段的标准转换错误仍按既有策略落为 `0.0`。
- 空 provider 与 registry 的 `none/off/false/0` aliases 明确映射到 identity；可选 provider module 缺失仍降级为 identity，结果带 `fallback=identity`。真实 factory 的未知 provider `ValueError` 和其他初始化错误不再被宽泛捕获。
- Hybrid ranking 在调用 factory 前跳过关闭的 provider。两份相关文件 Ruff check 与 format 检查通过；未运行 Python tests 或模型流程。覆盖表只关闭 shim 文件的本次审核，hybrid ranking 文件仍待完整审核。

## 第五批：KG sync wrapper 结果契约

- `KGEngine.search` 与 `app.rag.kg.pipeline.kg_search` 都声明返回对象；orchestrator 的 KG chunk-injection wrapper 直接返回 pipeline 结果，不再把错误类型伪装成空对象。KG query expansion 保持其 `KGResponseContractError` 校验。
- 修改文件 Ruff check、Ruff format --check 和 `git diff --check` 通过。未运行 Python tests、KG backend 或数据库流程；orchestrator 全文件审核仍待完成。

## 第五批：KG query expansion owner 文件审核

- `kg_query_expansion.py` 的同步／异步路径共用相同 scope、实体校验、筛选和排名；non-object response 以 `KGResponseContractError` 区分，optional KG failure 记录在 expansion outcome 并不生成查询。
- Ruff check 与 Ruff format --check 通过。本文件标记为已符合标准；未运行 Python tests 或 KG runtime。

## 第五批：共享 numeric coercion owner

- 删除 `common.py` 中与 `_safe_int`／`_safe_float` 重复的 optional wrappers；orchestrator 与 KG merge 调用改用既有 owner，并显式传入原有 minimum。KG merge 的本地 metadata int helper 保留，因为缺失值必须返回 `None`，与默认整数转换不同。
- KG merge 的 optional metadata int helper 只捕获标准 numeric conversion failures；缺失值仍返回 `None`。
- `Document.id` 来自 LangChain 声明的 `str | None` 字段，去掉 `getattr`。数值转换只把 `OverflowError`、`TypeError` 和 `ValueError` 归一到已有默认值。
- 三份文件 Ruff check、Ruff format --check 和 `git diff --check` 通过；Python tests 未运行。`common.py` 本批审核完成，`orchestrator.py` 与 `kg_merge_boost.py` 的完整文件审核仍待继续。

## 第五批：Channel budget policy 文件审核

- `channel_budget.py` 的 JSON summary、schema version、profile selection、per-channel allowlist、budget bounds 与 missing/invalid policy 结果均有明确归属；错误 optional entries 保持跳过，部分有效预算仍按既有策略应用。
- Ruff check 与 Ruff format --check 通过。本文件标记为已符合标准；未运行 Python tests 或 retrieval runtime。

## 第五批：Citation quality typed metadata

- Parse-quality helpers read LangChain `Document.metadata` and `Document.id` directly. The typed document list explicitly skips `None` entries; metadata score parsing continues to the next supported field only for `OverflowError`, `TypeError` or `ValueError`.
- Ruff check、Ruff format --check 和 `git diff --check` 通过。本文件标记为已调整；Python tests 与 retrieval runtime 未运行。

## 第五批：Dataset route planning state

- `_apply_dataset_route_hints` returns a frozen `_DatasetRouteState` with tuple fields. `plan_dataset_scope` reads typed attributes while retaining route order, dataset deduplication, strict scope, matched routes, and primary/expansion selection.
- The category branch was merged to `codex/local-account-registration` as merge commit `8c001010e` (source commit `6e2f788de`). Ruff check/format, syntax scan, caller scan, and diff check passed. Python tests were not run.

## 第五批：Query variant budget type boundary

- `QueryVariantStageInput` budget fields now use int/float optional types from `QueryExpansionBudget`; the duplicate broad-catching coercion helpers are removed. `None` and zero still mean no configured limit; invalid numeric values no longer silently become an unlimited budget.
- Existing query-planning, option-parser, and test constructors retain their field names; the only current production caller passes the normalized budget. Ruff check/format and `git diff --check` passed. Python tests were not run.

## 第五批：Query option adapter file review

- `query_options.py` keeps the mapping-to-typed-request boundary in one owner. Rewrite and budget numeric conversions reject malformed values; documented KG expansion defaults and multi-query caps were cross-checked against config and `.env.example`.
- Ruff check 与 Ruff format --check 通过。本文件标记为已符合标准；Python tests 与 runtime retrieval 未运行。

## 第五批：Query contract input review

- `QueryContractNormalizationInput` 和层级设置保持具名 dataclass；四个生产构造点同步消费同一 `normalize_query_contract` owner。RAG template 的可选 version 字段只在标准整数转换失败时省略，超出转换边界的异常不会被吞掉。
- Ruff check、Ruff format --check 和 diff 检查通过。本文件标记为已调整；Python tests 与 retrieval runtime 未运行。

## 第五批：Query invocation record types

- Query invocation records now use their declared string, boolean, float, integer, and Document-list fields directly. Empty kind still maps to `main`, optional docs still map to an empty list, and error truncation is unchanged.
- Ruff check、Ruff format --check、diff check 与调用方引用扫描通过。Python tests 未运行。

## 第五批：Metadata exact-anchor typed fields

- Anchor annotation reads the declared `Document.id` and metadata fields directly; optional list elements are still skipped unless they are `Document` instances. Float metadata retains defaults for standard numeric conversion failures, including overflow.
- Ruff check、Ruff format --check、diff check 和 stale-guard scan 通过。本文件标记为已调整；Python tests 与 retrieval runtime 未运行。

## 第三批：Conversation title service

- Conversation title/title_source 与 message content 按声明 ORM 字段读取；title_source 的 migration 是 NOT NULL。自动标题派生保留 None/空标题处理，latest-user query 保持 tenant/conversation/role 过滤及时间、ID 排序。
- Ruff check、Ruff format --check 与 `git diff --check` 通过。本文件标记为已调整；Python tests 和数据库流程未运行。

## 第三批：Conversation access and scope

- Access helper reads the declared owner, legacy user ID, dataset ID and update timestamp fields. The legacy UUID-to-account string owner fallback remains; unused database/tenant parameters were removed from the private owner check.
- Chat scope uses direct Conversation fields and explicit query-not-found handling. Tenant filters, owner denial, dataset readability, missing-document pruning/commit, and existing 403/404/409 responses remain in their original order.
- Ruff check、Ruff format --check、stale-guard scan 与 diff check 通过。Python tests 和 database flows 未运行。

## 第三批：Dataset defaults document scope

- Dataset inference queries document IDs together with dataset IDs, compares the found IDs with the deduplicated request set, and returns a default only when every requested document exists in the tenant and all share one non-null dataset. Dataset JSON metadata is read through its declared ORM field.
- Seven production callers were mapped. Ruff check、Ruff format --check 和 diff check 通过；Python tests 与 database runtime 未运行。

## 第三批：Package initializer review

- The API utility and Dify package initializers contain documentation only; submodules are imported explicitly. Dify support's parent-module boundary is documented, with the facade responsible for re-exports.
- 三个 initializer 的 Ruff check 与 Ruff format --check 通过；import 扫描未发现隐式 package-level utility imports。Python tests 未运行。

## 第三批：Indexing schema compatibility module

- `app/api/schemas/indexing.py` contains no schema or business logic and re-exports the internal dataclasses from `app.types.indexing`. No in-repository imports of the old path remain; it is retained for external Python import compatibility.
- Ruff check 与 Ruff format --check 通过。本文件按兼容性理由标记为保留；Python tests 未运行。

## 第三批：Dataset profile schemas

- Dataset profile summary and health response schemas use typed fields/default factories and compose the declared profile and ingestion owners. The dataset health route returns the matching response model; the profile service declares `DatasetProfileSummary` as its return type.
- Ruff check 与 Ruff format --check 通过。两份 schema 标记为符合标准；Python tests 和 API runtime 未运行。

## 第三批：Chat and integration request schemas

- Chat fusion validators rely on Pydantic's declared `dict[str, int/float]` field types while retaining channel allowlists, value bounds, empty-map policy, retrieval-profile application, and TokenUsage `model_fields_set` behavior. `MessageSchema.citations` uses a per-instance default factory.
- Connector ACL after-validators consume typed principals/rules directly; list bounds, `anyone` normalization, explicit opt-in, and fail-closed defaults remain. Evidence patch models read Pydantic v2 `model_fields_set` directly and still reject empty patches.
- External conversation validators trim declared string fields after Pydantic type validation; source allowlist, string/list bounds, and non-empty requirements remain. Request/response schema fields did not change.
- Ruff check、Ruff format --check 与 diff check 通过。Python tests 与 API runtime 未运行；invalid-input responses remain schema validation failures, but exact payloads were not runtime-tested.

## 第三批：Timeline, document health, and evidence schemas

- Document timeline schemas expose the route's audit/synthetic fields and PII-minimal details. Document health schemas compose route-created parsing/chunking objects and optional best-effort diagnostics. Evidence audit and repair schemas match their service/API response constructors; repair controls keep explicit dry-run defaults and bounds for items, references, and changes.
- Ruff check 与 Ruff format --check passed on all four files. Schemas are marked conforming; Python tests, API runtime, and database behavior were not tested.

## 第三批：Table SQL fingerprint utility

- Fingerprint normalization consumes its declared string input directly; whitespace, identifier normalization, literal preservation, and default digest length remain unchanged. The four production callers pass SQL text; the table-store boundary performs its explicit conversion before calling.
- Ruff check、Ruff format --check 与 `git diff --check` 通过。本文件标记为已调整；Python tests 未运行。

## 第三批：Router Prometheus metrics helper

- Helper now declares `dict[str, Any] | None` and uses the typed boolean value directly; malformed/missing telemetry layers still produce bounded `unknown` labels so optional metrics do not affect retrieval.
- Ruff check、Ruff format --check 与 diff check 通过。本文件标记为已调整；Python tests 与 metrics runtime 未运行。

## 第三批：QA, feedback, and ingestion-run schemas

- QA generation request bounds and response fields align with `document_qa_service`; feedback request/output fields align with the route and ORM model; ingestion-run response models align with the route projection and use factories for JSON/list defaults.
- Ruff check 与 Ruff format --check 通过。三份 schema 标记为符合标准；Python tests 与 API runtime 未运行。

## 第三批：Ingestion policy, industry rules, and RAG template schemas

- Ingestion policy schema owns the declarative shape while `ingestion_policy` service owns supported-step validation/normalization. Industry rules retain the `schema_` alias for the `schema` wire field. RAG template patches reuse `DatasetRAGDefaults` and retain existing version/traffic bounds.
- Ruff check 与 Ruff format --check 通过。三个 schema 与 route/service 构造点核对一致；Python tests 与 API runtime 未运行。

## 第三批：Dataset precheck and report schemas

- Precheck request constraints align with the privileged local-scan route; its response models match the precheck service and route constructors. Dataset report models cover every field built by `ReportService`, and the API declares `DatasetReportOut` as the response model.
- Ruff check 与 Ruff format --check passed for both files. Schemas are marked conforming; Python tests, API runtime, and filesystem/database flows were not run.

## 覆盖清单重对齐

- 用 `git -c core.quotePath=false ls-files` 与 `coverage.csv` 按完整路径比较：tracked 3,755，coverage 3,755，缺项 0，stale 项 0。先前出现的中文文档路径差异来自 Git 路径转义，重对齐时已消除。
- 新纳入的 84 个生产 Python 文件 Ruff check/format 通过，但逐文件语义审核仍为 pending；10 个 tracked Python test 文件按用户要求标记 preserved，没有运行或评价测试质量。9 个 tracked agent decision notes 作为文档保留。
- `web/types/settings.ts` 纳入 Task 6 待审核；当前 `web/node_modules` 中无 Prettier 安装，故格式状态保留 pending。前端类型检查未运行。

## 第三批：Dataset schema module audit

- `DatasetRAGDefaults` relies on its `dict[str, int/float]` field contracts for shape and value typing. Its after-validator retains the dataset-specific allowed-channel check; redundant dict checks and discarded numeric casts were removed. Effective fusion value bounds remain in `ChatRAGConfig` after dataset defaults merge.
- Dataset request/response models were mapped to route/service owners: create/update distinguish optional field presence, dataset out/list/ingestion stats have matching builders, config bundle import/export covers its nested policy/default fields, and clone/purge request/response types match their endpoints.
- Ruff check、Ruff format --check、diff check and stale-helper scan passed. Python tests and API/database runtime were not run.

## 第三批：FLS, DB catalog, KG diagnostics, evaluation, and prompt schemas

- FLS rule bounds/defaults align with the dataset schema and FLS service normalizer. DB catalog outputs map to ORM-backed route serialization. KG diagnostics and evaluation request limits/types match their route and engine/service constructors. Prompt template models retain their field bounds, version, and traffic-weight constraints used by the route.
- Six schema/package files passed Ruff check and Ruff format check; all route/service usages were mapped. Schemas are marked conforming; Python tests and API runtime were not run.

## 第三批：Corpus cache invalidation transaction

- Single-dataset lookup now returns no token when the tenant-scoped dataset row is missing, matching document and multi-dataset scope behavior. Cache invalidation requires `Session.flush()` and propagates database failure; the service does not take ownership of commit.
- The observability endpoint commits the revision update. RTBF retries the full dataset set after rollback; retention keeps cache invalidation best-effort but rolls back and logs before continuing. KG-job invalidation retains its existing commit/rollback behavior.
- Ruff check、Ruff format --check 与 diff check 通过。未运行 Python tests、database runtime 或 Redis；observability、RTBF、retention 文件仍待完整审核。

## 并行类别分支：聊天运行时与批量入库

- Chat runtime 分支 `1e69e726e` 已合并到 `codex/local-account-registration`。5 个生产文件将请求、RAG 配置、模板 ORM 和数据库依赖写为明确类型；dataset metadata 直接使用 loader 的字典契约。Redis payload 校验、缓存降级、singleflight、事务顺序、超时与取消策略保留。
- Document batch ingestion 分支 `3324df667` 已合并。批量构造、快照、完成与去重流程使用 `DBDocument` 的 ORM 字段；nullable owner 映射保留，删除无调用包装及重复导入。
- 合并后对 6 个生产文件运行 Ruff check、Ruff format --check；全部通过。`git diff --check e85d308e1..HEAD` 通过；调用方与 schema/ORM 契约已静态核对。按用户要求未运行或新增 Python tests；Redis、数据库及解析运行时未验证。
- KG query expansion 决策记录移除指向 `.agents/` 忽略文件的本地链接，避免干净 worktree 中出现断链；被忽略的本地文件未纳入提交。
- 覆盖表与 Git 跟踪路径复核后均为 3,757 项，无缺项或过期项；两个新决策记录登记为保留文件。

## 并行类别分支：设置 API 与共享类型

- 分支提交 `cd3eae192` 经独立审查通过并合并。`settingsApi` 的 `get`、`update`、`getStatus`、`testLLM` endpoint、方法、请求体和错误传播保持原样；`settingsApiLegacy` 仍从原路径导出。设置响应的公共 `success`／`message` 字段使用明确共享类型，`updated_keys` 保留。
- `git show --check` 通过；静态调用点和兼容导出核对通过。工作树没有 `web/node_modules`，因此 ESLint、Prettier、TypeScript 与前端 tests 均未运行；未安装依赖。两个文件已完成语义审阅，format_status 保留 pending。

## 并行类别分支：共享 API 核心

- Task 6 分支提交 `dd346a767` 经独立审查通过并合并。`api/core.ts` 将 request preparation 与 unexpected HTML response guard 提取为具名内部 handlers，并以原顺序注册；auth header、preferred language、request ID、OIDC retry/redirect/session clearing、cancellation、rate limit、HTML guard 和错误传播边界保持。`api-client.ts` barrel 的导出与 legacy aliases 未变。
- Direct importer scan、`git diff --check` 和 `git show --check` 通过。工作树缺少 `web/node_modules`，Corepack pnpm 为 12.4.1 而项目要求 10.26.0；因此 ESLint、Prettier、TypeScript 和前端 tests 未运行，未安装或绕过依赖限制。format_status 保留 pending。

## 并行类别分支：Auth 与 Access API 类型

- Task 6 分支 `a8363fbd` 经独立审查通过并合并。`auth.ts` 的 register/login/SAML payloads 与 `access.ts` 的 tenant/member/group requests 直接引用 generated OpenAPI owners；`tenant-permissions.ts` 复用 `TenantAccessOut`，并保留 optional `permissions` 的现有检查。
- Bootstrap-token trimming/header、SAML text response、endpoint/method/body/path encoding 和 Axios/OpenAPI error propagation 均经 caller/schema scan 核对。无 UI 或测试更改。
- `web/node_modules` 缺失且 Corepack pnpm 12.4.1 不符合项目要求 10.26.0，故 ESLint、Prettier、TypeScript 和运行时 API checks 未运行；未安装或绕过依赖。

## Settings Switch 组件审阅

- `web/components/settings/settings-switch.tsx` 已符合具名组件导出、局部 props type 和 shared Switch owner 约定，全部直接调用点已静态扫描；当前无需改代码。
- 未修改 UI；本地 `web/node_modules` 不存在，Prettier 检查未运行，format_status 保持 pending。

## Settings Section Audit

- `feature-flags-section.tsx`、`frontend-preferences-section.tsx` 与 `system-status-section.tsx` 经静态审阅后登记为符合：具名组件、局部 props 类型、直接依赖 settings/API owners。SettingsSwitch、ParserDropdown、ChunkStrategyDropdown 等现有组件保持使用；没有改 UI 或交互。
- 受影响视觉行为为零；没有页面截图。本地 `web/node_modules` 不存在，Prettier 未运行，format_status 保持 pending。

## Settings Integration Sections

- Task 6 integration-section branch `a700447b` 经独立审查通过并合并。Dify、object-storage、parser-service sections 仅把 settings/parser types 改为直接 owner imports；model-providers section 经审阅符合标准且未修改。
- JSX、props、state、callbacks、submission/error flows 和 visible UI 未变。依赖 `web/node_modules` 缺失且 pnpm 版本不符，ESLint/Prettier/TypeScript/browser checks 未运行；format_status 保留 pending。

## Governance Settings Type Imports

- Task 6 branch `7f2ab3e3` passed independent review and merged. Governance, industry-rules, LTR registry, and observability sections only change type-import ownership; rendered JSX, state, callbacks, form submit/error paths and public component exports remain unchanged.
- `web/node_modules` is absent and pnpm is version-incompatible; frontend ESLint/Prettier/TypeScript/browser checks did not run. No UI behavior changed and no screenshots were required.

## Remaining Settings Control Type Imports

- Task 6 branch `b32ff49f` passed independent review and merged. Navigation, RAG, runtime-controls and URL-ingest sections changed only type/API imports; layout, state, callbacks, forms and visible behavior are unchanged.
- Frontend tooling/browser checks remain unavailable because `web/node_modules` is absent and pnpm is version-incompatible; no UI change or screenshot was required.

## Shared Common Frontend Types

- Task 6 common-types branch commit `5aa80b6e` 经独立审查通过并合并。`PermissionEnum` now aliases the generated `DatasetPermissionEnum` schema; the literal union matches exactly. `DocumentAccessMode` retains `inherit`, while `LooseString` and `JsonObject` remain unchanged; direct consumers and the public barrel retain the same names.
- No UI or runtime change. `web/node_modules` is absent and pnpm is mismatched, so ESLint, Prettier, TypeScript and tests were not run.

## Chat API Type Owner

- Task 6 chat API branch commit `2ae11295` passed independent review and merged. `chat.ts` imports the existing chat contracts directly from `web/types/chat.ts`; no request body, OpenAPI/Zod validation, endpoint, auth, SSE transport, event ordering, abort, error, or compatibility export changed. `streaming.ts` was reviewed as conforming and remained unchanged.
- No visible UI change. Frontend tooling/tests/runtime are unavailable because `web/node_modules` is absent and pnpm does not match the project version.

## Document API 与 Preview Helpers

- Task 6 分支 `80a8d97a` 经独立审查通过并合并，改动仅在 `documents.ts` 与 `document-helpers.ts`。审查确认 endpoint/method/path、FormData、relative filename、parser resolution、timeout/abort、Zod/OpenAPI responses 和 error propagation 保持；branch name 与 brief 相差一个复数 `s`，不影响代码或目标分支合并。
- web/node_modules 缺失且 pnpm 版本不符，故 ESLint、Prettier、TypeScript、测试和 live document/upload runtime 未运行。

## Diagnostics 与 Smoke CLI

- Task 7 分支 `63da2012c` 独立审查通过并合并；`compose_diagnostics.py` 复用 `_collect_compose_ps`，但 services/ports 仍各自调用一次并保留命令参数、错误记录、JSON/JSONL 输出和主函数始终返回 `0` 的既有契约。api_ping/api_smoke/check_parsers 审阅后符合标准，没有代码改动。
- Ruff check/format、四脚本 AST、caller scan、diff check 和独立审查通过。Docker/API/parser/network CLI 均未执行；Python tests 未运行。

## 并行类别分支：Health、Metadata 与 Usage API

- Task 6 system API branch `6f3c5014` 经独立审查通过并合并。health endpoint 使用 generated response owner，同时保留 Zod validation；usage token/cost methods 共用与两条 OpenAPI operation 完全相同的 window 参数；meta aliases 和 api-client barrel 未改。
- Endpoint、methods、query fields、response/error propagation 和兼容导出经 diff/caller/schema review。因 `web/node_modules` 缺失且 pnpm 版本不符，ESLint、Prettier、TypeScript、tests 和 live API checks 均未运行。

## 并行类别分支：文档处理派发

- Task 4 分支已合并。`app/tasks/jobs.py` 的文档处理 handoff 显式传入文件、文档、租户、parser 和 chunk strategy，并沿用 worker 的 session 所有权；`process_document_flow.py` 的 31 个 `service` 参数使用 `TYPE_CHECKING` 下的 `DocumentProcessorService` 前向引用，避免 `processor.py` 的反向导入形成 runtime cycle。
- Task review 要求补齐该类型迁移和 Ruff 证据；两项 fix finding 均经复审关闭。明确从 `style-doc-dispatch` worktree、使用其 `ruff.toml`，对 6 个目标文件运行 Ruff check 与 format check，全部通过；六文件 AST、caller scan 和 `git diff --check` 通过。
- Python tests 未运行。仅 `jobs.py` 与 `process_document_flow.py` 在本类别分支中有代码 diff；`document_ingestion.py`、manual ingestion、dispatch service 和 worker 的其他职责仍待语义审核。

## 并行类别分支：聊天轮次持久化

- Task 3 分支提交 `6c5a8248` 调整 execution、turn persistence 和 streaming persistence contracts，修复提交 `657442d9` 补上 `UUID` 导入并整理 stream imports。独立审查未发现租户、会话、授权、事务或事件顺序回归；修复复审通过。
- 在 `style-chat-turn` worktree 根目录使用该分支 `ruff.toml`，对 9 个变更文件运行 Ruff check 和 format check，全部通过；九文件 AST、调用方扫描与 `git show --check` 通过。Python tests 未运行；真实数据库、队列与缓存运行时未验证。

## 并行类别分支：模型引导 CLI

- Task 7 分支仅修改 `scripts/bootstrap_parsing_small_models.py`，将重复的 `task`、`model_id`、`kind` 字段归到 `_model_record()`；JSON 字段集合和插入顺序、`hf_repo_missing` 的差异保持。`scripts/bootstrap_mimirq_models.py` 经审阅后登记为符合标准。
- 两个脚本的 Ruff check、Ruff format、AST 与 diff check 通过，独立代码审查通过。CLI、下载、ONNX 转换未运行；Python tests 未运行。

## 并行类别分支：Hybrid 候选融合

- Task 5 分支 `229928a95` 合并后只包含 `hybrid/dedup.py` 和 `hybrid/post_process.py` 的代码 diff。重复 identity key 转发到 `result_values.result_key`；anchor annotation/order 转发到 `metadata_ordering.order_metadata_anchors`。`candidate_ranking` 的 protected result、排序、dedup、rerank mapping、多样性和诊断调用顺序保持。
- 在 `style-rag-fusion` worktree 根目录使用其 `ruff.toml`，两文件 Ruff check/format 通过；AST、调用方扫描、review 和 `git show --check` 通过。未运行 Python tests、vector/lexical/database/reranker runtime。

## 并行类别分支：Hybrid Channel Results

- Task 5 channel retrieval branch `d9528115` 仅改 `hybrid/channel_results.py`：已声明 channel lists 直接迭代，局部初始化的 `annotated`/`promoted` 计数直接递增；provider item shape check 与 vector normalization boundary 保留。
- 独立审查通过，Ruff check/format、四模块 AST、caller scan 与 `git show --check` 通过。未运行 Python tests、vector/lexical/sparse/ColBERT/cache/reranker services。

## 并行类别分支：Lexical 与 Sparse Search

- Task 5 branch `753ff540` 仅调整 `bm25_index.py` 与 `sparse_index.py`：统一复用 `result_values.candidate_metadata_from_doc`，BM25/sparse 专属分数与结果构造保持，消除 sparse 通过 mixin MRO 获取私有映射函数的耦合。`text_preparation.py` 与 `lexical_search.py` 审阅后符合标准，未修改。
- Root 用 `style-rag-lexical-sparse` worktree 的 Ruff 配置对两个改动文件补跑 Ruff check/format；AST/caller scan、`git show --check` 和独立 review 通过。Python tests 与数据库/BM25/sparse/vector/model services 未运行。

## 并行类别分支：Context Expansion

- Task 5 branch `2cda543d` 独立审查通过并合并；仅移除 `context_expansion.expand_reranked_ids_by_score` 转发 wrapper，并让 `rerank_expand_rerank.py` 直接调用 `neighbor_expand.expand_neighbors_by_score`。Hierarchy wrapper 保留，因为它补充 `framework`/`strategy` diagnostics。
- Worktree Ruff check/format、六个 scoped context modules 与直接 caller 的 AST、caller scan 和 `git show --check` 通过。没有改 tenant/document scope、ordering、dedup、spans/budgets/provenance/failure policy。Python tests 和 runtime services 未运行。

## Rerank Result Cache Ownership

- Task 5 rerank-cache branch `230e9507` plus import-order fix `7f419794` passed independent review and merged. `orchestrator.py` imports the canonical `app.rag.rerank_result_cache`; the former orchestration path re-exports the same public symbols. Corpus-token invalidation now clears the cache populated by the orchestrator.
- Cache key scope, TTL, provider behavior, serialization, best-effort I/O and ranking policy are unchanged. Ruff check/format on both changed files and `git show --check` passed after fixing I001; Python tests, Redis/cache and reranker services were not run.

## Retrieval Intent and Policy Gates

- Task 5 branch `2cf14439` passed independent review and merged. `kg_merge_boost.py` directly consumes `is_kg` and `kg_score` from the local row owner; promotion order, score, thresholds, and diagnostics are unchanged. `intent_router.py` and `out_of_scope_live_gate.py` were audited as conforming owners; normalization, policy precedence, scope, and provider failure boundaries remain.
- Ruff check/format on `kg_merge_boost.py`, AST/caller scan for the three scoped modules and orchestrator, and `git show --check` passed. No Python tests or graph/vector/database/model services were run.

## Hierarchy Retrieval Owner

- Task 5 hierarchy-owner commit `55e872c2` passed independent review and merged. The optional `if refill` guard remains before direct iteration, preserving `None`/empty refill behavior; primary-before-refill order, duplicate removal, ancestor-wins logic, stable survivor order and metadata remain.
- Ruff check/format on `hierarchy.py`, AST/caller scan, `git show --check` and review passed. Python tests and graph/database/vector/model/cache runtime were not run.

## 并行类别分支：解析模型缓存与 Manifest

- Task 4 分支提交 `a39c1ce48` 的路径输出问题经复审后修复为 `c7d792bb9` 并合并。`load_small_model_manifest` 仍按进程工作目录解析输入路径，`base_dir` 只决定 manifest 中模型资源的根目录；bootstrap 使用返回的 canonical `manifest.path` 序列化结果，保留显式相对 CLI 路径原有的绝对输出。
- `hf_cache.py` 直接使用 path-like 下载结果，manifest 的字段解析、默认选择、cache path 和异常策略保持。Ruff check/format、四文件 AST、调用方扫描、diff check 和修复复审通过；未运行 Python tests、模型下载、HF/ONNX 加载或 parser service。

## Parser Structure Cleanup

- Task 4 branch `387bf59e7` 独立审查通过并合并。Noise rules、region algorithms、header/footer remover 与 reading-order fixer 只移除契约已保证的重复转换；pattern/threshold/page boundary/field/ordering behavior 保持。
- Ruff check/format、四文件 AST、直接 caller scan 与 diff check 通过。未运行 Python tests、OCR/parser providers 或模型服务。

## 并行类别分支：Chat Memory Runtime

- Task 3 chat memory commit `418da77a` 独立审查通过并合并。long-term、summary 与 structured-memory 输入使用已声明的 tenant/conversation 类型；flag gating、检索顺序、limits、事务边界及 best-effort 路径保持。
- Ruff check/format、AST、调用方扫描和 diff check 通过；未运行 Python tests、数据库、Redis 或 memory/model services。

## 并行类别分支：Parser Backend Resolution

- Task 4 backend resolution branch `1d39083f` 经独立只读审查通过并合并。仅在 `diagnostics.py` 将自身 sampling helper 保证返回的字典字段直接读取；`backends.py`、`factory.py`、`errors.py` 分别维持 canonical alias、stateful parser cache/plugin factory、subprocess error classifier owner。
- 四文件 Ruff check/format、AST、caller scan 和 diff check 通过。未运行 Python tests、parser providers 或 runtime services。

## 并行类别分支：查询准备与扩展

- Task 5 的查询准备分支提交 `589e5b6f` 经审查发现 Important 顺序回归：模型覆盖参数中的 `int()`／`float()` 解析可能早于 KG 扩展失败。修复提交 `f38123ea` 让同步和异步路径都在 KG 扩展后解析模型参数；解析错误仍显式传播，KG 诊断顺序恢复。
- 修复经定向复审通过并合并；Ruff check/format、AST、调用方和阶段顺序扫描及 diff/show check 通过。未运行 Python tests；实际 KG、模型和流式运行时未验证。四个目标模块中只有 `query_planning.py` 本轮发生代码调整，其他三个仍待语义审核。

## Query Model Expansion Type

- Task 5 query-contracts branch `9adb1019` passed independent review and merged. Only `model_query_expansion.py` changes a local dedup set to `set[str]`; validated model output, normalization, truncation, first-seen ordering and output shape remain.
- Ruff check/format, AST/caller scan, `git show --check`, and review passed. No Python tests or model/provider runtime were run.

## Query Variant Contract

- Task 5 commit `b26d9793` passed independent review and merged. `QueryVariant` names the existing `(kind, query)` pair; `QueryPlan.queries` still returns the same retrieval-stage list by reference and order.
- Ruff check/format, AST/caller scan and `git show --check` passed. No Python tests or model/provider services were run.

## Parser Table Structure and Rendering

- Task 4 branch `fbdf728eb` 独立审查通过并合并。Four table helpers removed only contract-redundant conversions while preserving row/cell order, padding, page/bbox metadata, OCR normalization, escaping, thresholds and renderer error policies.
- Ruff check/format, four-file AST, caller scan and `git show --check` passed. Python tests and parser/OCR/model services were not run.

## Feedback Type Ownership

- Task 6 branch `7429355fa` passed independent review and merged. Nine feedback DTOs moved unchanged into `web/types/feedback.ts`; `chat.ts` re-exports the old names so both `@/types/chat` and the root `@/types` barrel remain compatible. API requests, chat feedback controls, and feedback inbox behavior did not change.
- Type content comparison and caller/barrel checks passed. Frontend tests/lint/Prettier/TypeScript/runtime checks were not run because the web dependency tree is unavailable and pnpm is mismatched.

## OCR Enrichment

- Task 4 OCR branch `bf87f0db` passed independent review and merged. Formula/image text helpers and OCR redaction consume declared local contracts directly; provider inputs, caps, redaction, image order, thresholds, region/page metadata, and best-effort behavior remain.
- Ruff check/format on four files, AST, caller scan, diff check, and review passed. No Python tests, OCR/PIL/PDF/model services, or downloads were run.

## Retrieval Trace Diagnostics

- Task 5 branch `6fe43912` passed independent review and merged. `finalize_trace.py` increments local counters directly; `debug_sanitize.py` retains validation at raw debug/PII boundaries. Trace keys/order, optional fields, and error diagnostics remain.
- Ruff check/format on the changed finalizer, three-file AST, caller scan, diff check, and review passed. No tests or data services were run.

## Dataset Profile Service

- Task 3 branch `dffd9c137` passed independent review and merged. Profile scan/service read declared ORM/schema fields directly; profile-utils conversion remains at serialized metadata boundaries. Tenant/read ACL scope, scan order, cache keys, diagnostics, transactions and failure marking are unchanged.
- Ruff check/format, three scope modules and direct caller AST, caller scan, and diff check passed. No Python tests or DB/queue/parser/model/storage services were run.

## Document Identity and Lifecycle

- Task 4 branch `1c76da483` passed independent review and merged. ACL provenance uses explicit `DBDocument`, and deletion-audit detail reads non-null ORM fields directly; external hash/serialized metadata validation stays at its boundary.
- Tenant/ACL checks, tombstones, transactions, rollback, best-effort policy, direct error paths and callers were reviewed unchanged. Ruff/AST/caller/error-path scans passed; Python tests and DB/object-store/queue services were not run.

## Governance Settings Type Imports

- Task 6 branch `7f2ab3e3` passed independent review and merged as `acb0e767`. Four settings sections now import API/model contracts from their owners; JSX, state and submission/error behavior are unchanged.
- Frontend tests, ESLint, Prettier, TypeScript and browser checks were not run because the web dependencies are unavailable and pnpm is mismatched.

## Image Enrichment Contracts

- Task 4 branch `b798e94a` passed independent review and merged as `9bea7b14`. Five enrichment modules consume validated string/page values directly while retaining raw metadata checks, image/path/network limits, provider handling, fallbacks and audit types.
- Ruff check/format, AST, caller scan and `git diff --check` passed in the branch. Python tests and image/OCR/VLM runtimes were not run.

## Watermark Helper Contracts

- Task 4 branch `fc12d6f2` passed code and caller review and merged as `bf44f575`. Duplicate result/page/coordinate conversions were removed after validation; parser input coercion, thresholds, removal order and image handling remain.
- Ruff check/format, AST, caller scan and `git diff --check` passed in the branch. Python tests and parser/image runtimes were not run.

## Verified Wheel Downloader Import

- Task 7 branch `bb9dfea8` passed independent review and merged as `28c60db0`. The change uses a direct `dataclass` import; pinned URLs/hashes, retries and security checks are unchanged.
- `git diff --check` passed. No commit-specific Ruff/AST result was recorded; Python tests and downloader runtime were not run.

## Chunk Statistics Contracts

- Task 3 branch `codex/style-unify-task3-chunk-stats` commit `8c847727` passed independent review and merged. It removes redundant conversions of locally computed and typed integer values, and removes a duplicate histogram-bin copy. Invalid raw lengths are still skipped and duplicate counts remain clamped at zero.
- Ruff check/format, AST, caller scan, and diff/show checks passed in the branch. Python tests were not run; implicit coercion of out-of-contract typed arguments is no longer preserved.

## Doctor CLI Checks

- Task 7 branch `codex/style-unify-task7-doctor-cli` commit `b1a332c6` passed independent review and merged. File existence is checked once per path, while required-file exit status, optional-file warnings, and Windows `mbcs` decoding fallback remain unchanged. `_decode_output` now catches codec lookup and Unicode decode errors only.
- Python 3.14 AST, direct-reference scan, and diff/show checks passed. Ruff was unavailable; the doctor CLI and Python tests were not run.

## Parsing Artifact Counts

- Task 4 branch `codex/style-unify-task4-artifact-stats` commit `aee1e5b3` passed independent review and merged. Locally derived page/table/image/block counters now use their integer values directly; PDF page count still crosses the existing `_coerce_int` metadata boundary.
- Caller and response field contracts plus `git diff --check` passed. Ruff and AST tooling were unavailable in that worktree; Python tests and parser runtime were not run.

## Pre-POC Quality Gate

- Task 3 branch `codex/style-unify-task3-ingest-quality` commit `ec1b0844` passed independent review and merged. The gate now uses declared Path/config/analyzer result types directly; mode fallback, UTF-8 partial-tail handling, GB18030/Latin-1 fallback, sample caps, thresholds and strict blocking remain unchanged.
- Caller/config/analyzer type review and `git diff --check` passed. Ruff, AST, runtime and Python tests were not run in that worktree.

## Chunk Quality Gate

- Task 3 branch `codex/style-unify-task3-chunk-quality` commit `8a0e5e2b` passed independent review and merged. Persisted/`Any` statistics retain numeric validation; typed scalar inputs and internally constructed reason, patch and recommendation values no longer use redundant coercions or exception suppression. Thresholds and all 10-item caps remain.
- Ruff check/format, AST, caller scan and diff/show checks passed. Python tests were not run.

## Chunking Grid CLI

- Task 7 branch `codex/style-unify-task7-chunking-grid` commit `80e989c1` passed independent review and merged. Declared chunker, document, token estimate and cliff output types replace redundant guards while JSON field casts, empty stats, encoding, ordering, output and exit behavior remain.
- AST, direct-reference scan and diff/show checks passed. Ruff was unavailable; Python tests and CLI runtime were not run.

## Ingestion Policy Diff

- Task 3 branch `codex/style-unify-task3-policy-diff` commit `20d7e5c0` passed independent review and merged. Required string IDs and schema-owned rule lists are used directly; canonical JSON comparison, the conservative serialization-failure-to-changed policy, sorted IDs and response shape remain.
- Schema/caller review and diff/show checks passed. Ruff and AST tooling were unavailable; Python tests were not run.

## Chunk Coverage Metrics

- Task 3 branch `codex/style-unify-task3-chunk-coverage` commit `92b0cee1` passed independent review and merged. Malformed range pairs still undergo conversion and skip handling; clipping, merge, gaps and empty-range behavior remain. Internal arithmetic no longer repeats integer conversions or nonnegative clamps already established by clipped integer ranges.
- Ruff check/format, AST, caller/producer scan and diff/show checks passed. Python tests were not run.

## Batch Preview CLI

- Task 7 branch `codex/style-unify-task7-preview-batch` commit `868b26c6` passed independent review and merged. The script consumes declared `Document`/preview-helper results directly and catches only filesystem I/O errors when skipping candidate files. Offset fallback, JSON fields/defaults, caps, JSONL flushing/closing and exit behavior remain.
- AST, direct-reference scan and diff/show checks passed. Ruff was unavailable; Python tests and CLI runtime were not run.

## DB Profile Cache

- Task 3 branch `codex/style-unify-task3-db-profile-cache` commit `b183a001` passed independent review and merged. Typed key/TTL/payload values are used directly; key format, TTL bypass, monotonic expiration, capacity check and top-level shallow copies remain.
- Ruff check/format, AST, caller scan and diff/show checks passed. Python tests were not run. Existing limitations remain: capacity can reach 2049 before the next insertion clears it, and nested values are shallow-copied.

## Document Version Diff

- Task 4 branch `codex/style-unify-task4-version-diff` commit `1ce72a02` passed independent review and merged. External hash normalization remains; Counter multiplicities, sorted hash samples, integer sample-limit behavior and response fields are unchanged.
- Caller/schema review and diff/show checks passed. Ruff and AST tooling were unavailable; Python tests were not run.

## Retrieval Hit Frequency

- Task 3 branch `codex/style-unify-task3-retrieval-hit-frequency` commit `daa50e70` passed independent review and merged. Typed settings, limits and aggregate counters no longer receive duplicate conversions. Untrusted JSONL parsing, `_to_int`, per-record containment, missing/invalid timestamp treatment, tenant/document matching and bounded reads remain.
- AST, caller/settings/type scan and diff/show checks passed. Ruff was unavailable; Python tests and metrics-file runtime were not run.

## Ingestion Metrics

- Task 3 branch `codex/style-unify-task3-ingestion-metrics` commit `9284ad91` passed independent review and merged. `_enabled()` now returns the declared boolean setting directly; duration conversion/rejection, negative-value handling, bounded label normalization and caller best-effort wrappers remain.
- Ruff check/format, AST, caller scan and diff/show checks passed. Python tests were not run.

## Prompt Variant Weights

- Task 3 branch `codex/style-unify-task3-prompt-resolver` commit `e24fe9d2` passed independent review and merged. The resolver reads the mapped nullable Float directly; null/zero handling, negative clamp, ordering, stable routing and equal-weight fallback remain.
- Caller/model/schema review and diff/show checks passed. Ruff and AST tooling were unavailable; Python tests were not run.

## Access Graph Diff

- Task 3 branch `codex/style-unify-task3-access-graph-diff` commit `89cb9048` passed independent review and merged. External export normalization, stable-hash privacy fallback, kind filtering, sample caps and PII-safe fields remain; normalized internal tuple/Counter values are consumed directly.
- AST, caller/type scan and diff/show checks passed. Ruff was unavailable; Python tests were not run. Existing set-based example and churn tie ordering is not deterministic across processes; this pre-existing behavior was not changed.

## Connector ACL Metrics

- Task 3 branch `codex/style-unify-task3-connector-metrics` commit `49e8fa55` passed independent review and merged. The bool setting and counts derived from sanitized membership lists are used directly. Label sanitation, finite mode/shape buckets, unknown handling and best-effort suppression remain.
- AST, caller/settings scan and diff/show checks passed. Ruff was unavailable; Python tests were not run.

## Retrieval Fixture CLI

- Task 7 branch `codex/style-unify-task7-fixture-builder` commit `df66baec` passed independent review and merged. Only argparse-typed paths, `top_k` and retrieval mode stop receiving redundant conversions; raw JSON normalization, aliases, defaults, IDs, fixture shape and resolved output handling remain.
- Caller scan and diff/show checks passed. Ruff/AST tooling was unavailable; Python tests and CLI runtime were not run.

## Embedding Drift Metrics

- Task 3 branch `codex/style-unify-task3-embedding-drift` commit `e20ddeae` passed independent review and merged. Locally derived integer/float metrics and the typed integer content cap no longer receive repeated casts. DB row filtering/coercion, vector shape checks, PII-safe output, sample cap, thresholds and error behavior remain.
- Ruff check/format, AST, caller scan and diff/show checks passed; independent source-boundary review passed. Python tests were not run.

## Evidence Import Normalization

- Task 3 branch `codex/style-unify-task3-evidence-import` commit `e53388cf` passed independent review and merged. Two helpers now consume already normalized `str` and `dict` values directly; CSV/JSONL decoding, raw field coercion, malformed input responses, caps, row numbering, deduplication and output shape remain.
- Ruff check/format, AST, caller scan and diff/show checks passed. Python tests were not run.

## Prompt Defaults Boundary

- `app/services/prompt_defaults.py` was reviewed and marked conforming without a code change. The explicit request-fields set preserves omitted-versus-null semantics, while dataset JSONB remains validated as a dict and string/UUID values retain their current normalization and malformed UUID reporting.
- Caller/schema provenance review and `git diff --check` passed. Ruff/AST tooling and Python tests were not run.

## Embedding Language Advisory

- Task 3 branch `codex/style-unify-task3-embedding-advisory` commit `df7405a7` passed independent review and merged. A declared routing bool is used directly; normalized nonnegative counts and configured model keys drive equivalent routing predicates. Raw count/JSONB metadata normalization, generic-model matching, recommendation ordering/cap and non-mutating output remain.
- AST, caller/config/schema scan, and diff/show checks passed. Ruff was unavailable; Python tests were not run.

## Dataset Embedding Configuration

- `app/services/dataset_embedding_config.py` was reviewed and marked conforming without a code change. Settings cleanup/defaults and JSONB dataset override normalization are required at distinct boundaries; dataset-scoped backend rejection, hash/collection semantics and embedding cache ownership remain clear.
- Ruff check/format, AST, caller scan and `git diff --check` passed. Python tests were not run.

## Connector Egress Policy

- Task 3 branch `codex/style-unify-task3-egress-policy` commit `4a153a54` passed security review and merged. The private IP-literal helper consumes its already normalized string directly. Untrusted config/host normalization, CIDR parsing, DNS, IPv6 handling, metadata/private-address blocks, allowlist and failures remain unchanged.
- Caller/security review and `git diff/show --check` passed. Ruff/AST tooling and Python tests were not run.

## Encoding Conversion CLI

- Task 7 branch `codex/style-unify-task7-encoding-cli` commit `00235535` passed independent review and merged. Argparse bool/extension values are consumed directly, and `is_dir()` replaces `exists()` plus `is_dir()` for target cleanup. Cleanup order, dry-run behavior, path overlap guard, file write failures and exit counts remain.
- AST, direct-reference scan and diff/show checks passed. Ruff was unavailable; CLI runtime and Python tests were not run. Existing `--clean-target` behavior can remove the source when target is the source or one of its ancestors; this pre-existing behavior was not changed in the style slice.

## Evidence Dashboard

- Task 3 branch `codex/style-unify-task3-evidence-dashboard` commit `45cc966b` passed independent review and merged. Casts around locally derived counters and `timedelta.total_seconds()` values were removed; JSON/ORM validation, nullable timestamp and finite-number handling, top-N caps/order, None paths and response fields remain.
- Caller/schema review and diff/show checks passed. Ruff and AST tooling were unavailable; Python tests were not run.

## Fixture From File CLI

- Task 7 branch `codex/style-unify-task7-fixture-from-file` commit `32494f99` passed independent review and merged. Redundant conversions of argparse-typed path, string and integer values were removed; parser backend defaults, document serialization, OCR fallback, query normalization and UTF-8 JSON output remain.
- AST, direct-reference scan and diff/show checks passed. Ruff was unavailable; Python tests and live parser/OCR execution were not run.

## Document QA

- Task 3 branch `codex/style-unify-task3-document-qa` commit `3578327b` passed independent review and merged. Typed request/helper values and local counters use their declared values directly; source normalization, Q/A pattern behavior, LLM degradation fallback/logging, tenant ACLs, scoped queries/deletes, best-effort indexing and response shape remain.
- Ruff check/format, AST, caller/schema scan and diff/show checks passed. Python tests and DB/vector/LLM runtime checks were not run.

## Integrated validation and coverage reconciliation (2026-11-04)

- Merged the reviewed fixture-from-file category `32494f99`; its source had remained outside the integration branch despite the preceding record. The integration now contains that source change.
- Repaired 13 CSV records whose unquoted explanatory commas had created extra columns. Every row now has exactly six fields; all 3,758 paths are unique and exactly match `git ls-files -z`, including non-ASCII paths.
- Registered 336 pending Python test files under `tests/` as preserved under the user's explicit deferral. This is a scope exclusion; no test semantics or runtime result is claimed. Production `app/rag/evaluation/test_generator.py` remains in scope.
- Using the available `E:/MimirQ/.venv/Scripts/python.exe`, checked the 33 production Python files changed since `688af099f`: Ruff check and complete AST parsing passed. Ruff format initially identified two quality/advisory modules; both were formatted with unchanged normalized AST, after which all 33 passed format checking. Detailed command/file evidence is in `.superpowers/sdd/2026-11-02-style-unification/integrated-static-2026-11-04.json`.
- Frontend dependencies are partially installed. Pinned Prettier 3.9.10 and eslint-config-prettier 10.1.8 were installed only in ignored `.superpowers/style-tooling`; application manifests, lockfiles and dependency versions were not changed. The frontend category uses the existing TypeScript/ESLint and these pinned tools. Earlier unavailable-tool entries are historical records, not the current environment status.
- Subsequent source integrations group complete category changes and their evidence in one commit; pure formatting stays in its own category commit. Existing root source and untracked work outside each category remain intact.

## Repository CLI entrypoints

- Reviewed five complete entry modules: `init_env.py`, `alembic_cli.py`, `clean.py`, `check_npm_audit.py` and `check_retrieval_profile_compat.py`. Environment setup uses argparse flags and the required regex group directly. Retrieval compatibility reads declared Settings fields and keeps one requested-option mapping for both profile application and its diagnostic fallback.
- Alembic's upstream exit normalization, cleanup's intentional best-effort behavior, and the npm audit's fail-closed external JSON checks conform without source changes. Existing CLI paths, secret/copy ordering, accepted boolean spellings, config defaults, diagnostic payloads and exit codes remain.
- All five modules pass Ruff check, Ruff format and AST parsing. AST comparison proves the shared option mapping exactly matches both the former call arguments and diagnostic fallback values; all callers in Makefile, CI and script references were inspected. No Python tests, file deletion, env writes, migrations, audits or model services were run. Per-file evidence: `.superpowers/sdd/2026-11-02-style-unification/repository-cli-category-report.json`.

## Connector category: registry, catalog and synchronization

- Completed the whole 15-file connector foundation category from branch commit `fec1647f9`: 9 adjusted, 2 conforming, 4 retained for explicit plugin/resource responsibilities. The source and these per-file results are integrated together as one category commit.
- One schema URL normalizer now owns trimming/deduplication/caps for four configuration fields. MySQL and SQL Server share table-field projection, catalog create/update share mutable assignments, and sync payloads/source identities use their actual typed owners. Configuration adapters accept actual schema or dictionary inputs instead of suppressing schema serialization errors through unrelated attribute fallback.
- Independent review and fresh Ruff check/format pass for all 15 files; AST parsing covers all 15 plus 28 relevant caller files. The static audit binds 44 direct calls, preserves 112 parameter/default contracts, 22 schemas/200 fields, and 26 sensitive SQL/network/cleanup helper bodies. Auth/tenant checks, query ordering, truncation, caller-owned transactions, timeouts, cleanup and external errors remain intact.
- The retained catalog query checks currently skip SQLAlchemy `RowMapping` values because they test for `dict`. This separate preexisting runtime issue is recorded in the category report, not silently changed during style cleanup. No Python tests, DB connections or connector services ran. Full per-file evidence: `.superpowers/sdd/2026-11-02-style-unification/connectors-domain-report.json`.

## RAG policy category: one routing owner

- Completed all 12 policy modules from `b9dcd6fc`: 7 adjusted, 4 conforming, 1 intentionally retained. Removed the 827-line duplicate orchestration router, redirected actual production callers to the policy owner, and placed identical retrieval-mode normalization in a dependency-light owner. Existing text entry points directly reexport that same function.
- Both orchestration calls retain a six-reason trace budget; the policy caller retains eight. Source comparison independently verifies all 28 removed routing functions against canonical bodies, mode constants/aliases, routing order, partition precedence, output shapes and scoring ties. Normalized learned-model and obligation records use explicit types; raw model/provider input validation remains at its owner.
- Ruff check/format and AST parsing pass for all 19 surviving category/migration/test-reference files. Independent source/reference review scanned 1,906 tracked Python files and found no remaining deleted-module references; 86 structural checks and 396 bound calls pass. The 12 policy modules and new rule owner receive full dispositions; four large caller modules remain pending for their remaining behavior.
- Two existing tests received necessary import synchronization only; their non-import AST and assertion/patch bodies are identical. The old two-copy comparison now references one canonical implementation and supplies no independent regression evidence. No Python tests, application imports or model/database services ran. Detailed per-file evidence: `.superpowers/sdd/2026-11-02-style-unification/rag-policy-domain-report.json`.

## Frontend API/type category: formatting

- Applied source category `fe736f244` to 33 tracked API/type files, using the existing two-space/single-quote/no-semicolon/120-column Prettier rules. The coverage table records formatting only at this stage; semantic pending entries are not closed by formatting.
- Fresh integrated Prettier check passes all 33 files. Independent source review confirms declaration structure and emitted JavaScript AST equivalence; routes, parameters, validators and runtime catalogs are unchanged. Type ownership and missing schema alias changes are kept in the separate semantic category.

## Frontend API/type category: direct contracts

- Completed all 51 owned API/type modules from semantic source category `15e7ec674`: 182 type-only imports now refer to actual owners, and the tenant-member update request aliases the existing generated schema. Runtime requests and compatibility barrels remain unchanged; ambient library declarations retain their required forms. Each file has an individual disposition in `frontend-contracts-report.json`.
- Independent review verifies all 183 type-equality assertions and equivalent emitted JavaScript ASTs for 51 files, including variable-declaration kinds and operators. Fresh integrated ESLint, Prettier, API-route contract, API coverage and strict type-drift scripts pass; the type-drift baseline was not widened. The missing scoped ESLint log referenced by the initial report is now populated from the integrated rerun.
- Full TypeScript remains incomplete: diagnostics fall from 24 to 23 with zero new errors. Remaining errors belong to the enriched dataset-RAG view being typed as the narrower system API schema, and incomplete MagicPDF/PaddleVL initial defaults in settings state. These are assigned to the subsequent configuration-contract category; they are not counted as a passing whole-project typecheck. No page rendering/state/interaction code changed in this category.

## Persistence model declarations

- Completed the remaining 19 model modules: 1 adjusted, 15 conforming, 3 retained for model registration/public exports and framework validation/transformer protocols. Each file has a distinct table/protocol reason in the coverage table and `persistence-models-report.json`.
- Conversation document scopes and message citations now use `default=list`, matching the other JSON/array collection defaults and producing a fresh empty list per inserted row. The normalized model AST is identical except these two client-side default factories; tables, 337 column declarations, 60 relationship/constraint declarations, tenant keys, indexes, foreign-key actions and server defaults are unchanged. No migration or data change is needed for the factory form.
- All 19 files pass Ruff check, formatting and AST parsing. Alembic registration and package export responsibilities were reviewed directly. No Python tests, model imports, database operations or migrations were run; live persistence behavior remains unverified. Evidence: `.superpowers/sdd/2026-11-02-style-unification/persistence-models-report.json`.

## Connector execution category

- Completed 22 owned execution/config/access/run/schedule modules from `832309ae1`: 18 adjusted including the deleted duplicate ACL route owner, and 4 conforming. Four providers share source-access settings and seven workers share ingestion-option mapping; actual client/config/worker/plan contracts replace arbitrary-object adapters.
- Fourteen duplicate route ACL helpers now have one service owner; the API aggregate imports that owner and retains remaining route behavior. One existing test received import/patch target synchronization only, with all 37 assertions unchanged. The aggregate remains partially reviewed; the deleted route has been removed from the coverage manifest.
- Independent review and integrated Ruff/format/AST pass for all 23 surviving owned/caller/reference files. Static evidence preserves 440 parameter/default contracts, binds 713 direct calls, compares all 14 ACL helpers and seven worker entries, and retains 142 transaction/resource operations plus 29 HTTP payload constructors. No Python tests, network/DB/job/storage services ran.
- Existing Jira issue contexts drop `source_acl` before the resolver, and route-side Confluence provenance suppression differs from its service. These preexisting behaviors and the earlier RowMapping finding are recorded separately in `.superpowers/sdd/2026-11-02-style-unification/connectors-execution-report.json`; they were not silently changed by style consolidation.

## RAG evidence category

- Completed 11 whole modules from `7f7d66098` and migrated the orchestration text helper's JSON parser ownership. Three duplicated JSON parser chains now share `json_text`; its JSON/blank-language fence selection reuses the equivalent existing code-fence scanner. Claim token/uncertainty rules, citation anchor normalization and sentence-reference field parsing each have one actual owner. Different citation/capsule hash payloads remain distinct.
- Independent review confirms parser selection/error policies, claim thresholds, first-seen reference/span ordering, caps, hashes, malformed metadata containment and lightweight import boundaries. All 12 scoped files pass integrated Ruff check, formatting and AST parsing. The static audit preserves 148 other functions, checks 138 invariants and binds 339 actual calls, with six forwarded mappings reviewed directly.
- No Python tests were modified or run, and no model/NLI/database services were invoked. The orchestration helper still awaits a full review of its non-JSON behavior; it receives a migration-only record. Per-file evidence: `.superpowers/sdd/2026-11-02-style-unification/rag-evidence-core-report.json`.

## Frontend configuration category: formatting

- Source category `1e369ea48` applies existing Prettier rules to the dataset RAG helper/test, knowledge settings panel and settings hook. This commit records formatting only; remaining page/hook semantic work is not closed by the reflow.
- Fresh integrated Prettier passes all four files. Independent AST comparison, including text-bearing JSX leaves and normalized redundant parentheses, proves the formatting preserves runtime structure and visible text.

## Frontend configuration category: view ownership and defaults

- Source category `1a1752e87` gives the dataset workbench an explicit `DatasetRagViewConfig` owned by dataset types: the unchanged system RAG API contract plus exactly 13 supported dataset-only overrides with their original optional/null types. The helper and workbench use that view; the system schema and generated OpenAPI are not widened. Dataset updates still project only top-k, score threshold and retrieval mode, preserving all other existing override content and config-hash requests.
- MagicPDF initial state now supplies its three required backend defaults, and PaddleVL supplies its two required display/audit defaults. These keys enter parser save payloads when needed; server/edited values retain precedence. Marker config, rendered controls/JSX, and other loading/save/reset/error behavior are unchanged. The earlier report's Marker label was corrected to PaddleVL.
- Independent virtual-baseline compilation reproduces 23 diagnostics and final whole-project TypeScript has zero. Fresh scoped ESLint/Prettier and API contract/coverage/drift checks pass; the existing three helper behavior tests and seven source checks pass. AST review finds exactly the five default-value additions as runtime differences.
- Only the dataset helper receives a full new semantic completion; the hook, panel and existing test retain their broader pending/migration statuses, and the already audited dataset type owner keeps its prior full result. No settings-hook/browser/backend runtime check is claimed; source checks do not cover those flows. Evidence: `.superpowers/sdd/2026-11-02-style-unification/frontend-config-contracts-report.json`.

## Frontend gate fixture and broader acceptance

- The first full frontend Vitest run passes 127/128 files and 420/421 tests. The sole failure assumes the live handwritten API type count equals the checked-in 66-type allowance; actual count is 29. The detector correctly accepts 29 against a temporary 65 allowance, contradicting that stale negative fixture.
- Source category `05940124f` tests threshold rejection using an isolated copy of the unchanged detector and one controlled handwritten type. Module and type breaches retain required exit 1 and exact error assertions; the positive case continues checking real source against the unchanged 8-module/66-type baseline. No production gate or baseline is loosened.
- Fresh integrated Vitest passes all four gate tests; scoped ESLint and Prettier pass. Direct Node CLI probes independently return exit 1 and expected messages for both breach cases, establishing no EPERM/sandbox bypass. Evidence: `.superpowers/sdd/2026-11-02-style-unification/frontend-gate-direct-cli.json` and `frontend-gate-integrated-*.log`.
- All five existing UI-check scripts pass. Prebuild Monaco/PDF.js asset sync passes. The C-drive worktree build fails resolving E-drive dependency-junction paths as `./E:/...`; this is being retried from a clean export on E. A production build or bundle-budget success is not yet claimed. Broader run provenance/results are in `.superpowers/sdd/2026-11-02-style-unification/frontend-acceptance-report.json`.

## Integrated Python checks

- At `dd926f449`, Ruff lint passes the 1,905 tracked Python candidates under the configured third-party/history exclusions. Formatting passes with the committed blob of `app/api/schemas/document.py` checked separately; its preexisting unstaged leading blank line remains untouched in the working tree. No Python tests ran.
- The commit was unchanged throughout the final seven-chunk lint/format run. Evidence: `.superpowers/sdd/2026-11-02-style-unification/integrated-full-ruff-2026-11-04.json`. Passing static checks does not close pending file-level semantic reviews or prove runtime integration.

## Remaining RAG core utilities

- Completed all 22 remaining core utility modules from `b44e32bab`: 12 adjusted, 4 conforming, 6 retained for intentional lifecycle/lazy/framework behavior. Existing JSON hashing owns rewrite/fingerprint serialization; pending-interrupt selection is shared while preserving lock, clock, status and order; normalized profiles use explicit record types; image payload construction uses one actual vision owner.
- Independent review verifies hash encoding/width, query/profile budgets, vision MIME/base64/data URL behavior, safety evaluation and HTTP boundaries, temporal/filter ordering, async/resource scope and lazy exports. All 22 files pass integrated Ruff check, formatting and AST parsing; 340 structural checks preserve 171 other function/method bodies and bind 798 calls, with eleven forwarded mappings read directly.
- No Python tests, application imports or model/network services ran. Static checks cannot establish live cancellation/provider behavior. Per-file evidence: `.superpowers/sdd/2026-11-02-style-unification/rag-core-utilities-report.json`.

## Document and pipeline schema category

- Completed the remaining six schema modules: four adjusted and two conforming. URL/HTML ingestion request models were AST-identical duplicates; ingestion now directly reexports the existing document-owned models and preserves its historical pipeline-options export. Public route models and all names/import paths remain available.
- Post-validation member/group lists use their string/UUID values directly; modeled index/provenance fields no longer repeat dynamic attribute checks. Pipeline plugin requests share one registered-reference validator, with unchanged regex and errors; regression mode validation uses its dependency-light rule owner and the actual Pydantic fields-presence set.
- Independent review verifies every field/default/alias/constraint across 184 baseline classes, duplicate full-class AST equality, 87 tracked schema caller modules and after-validator provenance. Ruff, formatting and AST pass all six task versions; raw external dict/string/UUID/plugin/fusion validation and metadata fallback policies remain intact. Additional imports in nine preexisting untracked tests were observed but remain outside this tracked category.
- The user's original leading blank line in `document.py` is left in the worktree and excluded from this category's staged source. Existing URL-endpoint test edits remain untouched. No Python tests, business-module imports, live OpenAPI generation or database/service execution ran. Evidence: `.superpowers/sdd/2026-11-02-style-unification/document-pipeline-schemas-report.json`.

## Connector API route category

- Completed all 20 remaining connector route modules from `f60d3e0d6`: 16 adjusted including 13 obsolete provider/helper/plan/state module deletions, and 4 conforming. Actual HTTP handlers, saved configs, schedules, background dispatch, queue handoff and registered jobs already use canonical services; the removed private copies carried roughly 9,700 redundant lines.
- Independent review traces actual entry points and lazy compatibility ownership, confirms the router assembler/route maps/`__getattr__` are unchanged, resolves 274 direct compatibility attributes, and verifies all 17 canonical execution modules are unchanged. Config dispatch now has one schema-owned model map; the moved group lookup has the identical body and no new dependency cycle.
- Integrated Ruff/format/AST pass all surviving category and required reference files; static checks preserve 15 route contracts and bind 759 calls. Four existing tests receive import/patch synchronization with all 177 assertions unchanged. Retired Confluence/Jira private variants do not alter active provider policies. No Python tests, imports or runtime services ran; arbitrary external users of deleted private modules remain unverified.
- Removed the 13 deleted paths from the coverage manifest; surviving route files receive full dispositions while owner-only relocations keep their existing source audit. Evidence: `.superpowers/sdd/2026-11-02-style-unification/connector-route-boundaries-report.json`.

## Frontend acceptance: resolved follow-ups

- Corrected full Vitest run on clean `05940124f` passes all 128 files and 422 tests, using two workers. The original 420/421 run remains recorded independently; the justified stale-fixture fix triggered this repeat.
- A clean E-drive export from integrated `ecfa39fc6` exactly matches all 1,080 tracked frontend blobs and the reviewed gate commit's web tree `baf1968d010743ff6ff96d28a48bba45af9424b8`. Prebuild asset sync, complete Next 16.2.11 webpack build, TypeScript, all 46 static pages, and all 12 bundle budgets pass. The earlier cross-drive-junction failure is retained as a resolved environment limitation; no application workaround was introduced.
- All five UI-check scripts pass. Build output and generated `next-env.d.ts` stay in the disposable export; no generated artifacts are committed. No browser/API/PostgreSQL user-flow run is claimed. Exact commits, commands, original/final results and 12 verified logs are recorded in `.superpowers/sdd/2026-11-02-style-unification/frontend-acceptance-report.json`.

## Shared internal types and Dify schema ownership

- Completed the five remaining internal type modules and added one actual Dify API schema owner. Six external request/response classes move unchanged from `app/types/dify_integration.py` to `app/api/schemas/dify.py`; the route helper also replaces its six duplicated schemas and two duplicated actor/flag records with direct canonical aliases. Existing public import paths and `__all__` remain, while six actual service consumers import the schema owner directly.
- Exact class AST comparison verifies all six moved models, and all eight duplicated route record fields match the retained owners. API/service function bodies and actor/flag dataclasses are identical. No production class-identity checks depend on former duplicate classes; a tracked test's canonical model import remains supported. The five internal modules' immutable records, collection factories, nullable requested/resolved pipeline types and TYPE_CHECKING-only ORM dependencies were reviewed in full.
- Document analytics now reads guaranteed artifact-result keys and the language detector's actual result dataclass. Raw PDF/document metadata and language validation stay with their existing producers. Ruff/format/AST pass 13 whole/partial files; 50 tracked caller modules were inspected. Seven large API/service modules retain migration-only conclusions for this import/schema change.
- No Python tests, business imports, live OpenAPI export or Dify/provider/database services ran. Per-file/AST/caller evidence: `.superpowers/sdd/2026-11-02-style-unification/shared-domain-types-report.json`.

## Storage adapter category

- Completed all 12 storage modules from `e40a28048`: 7 adjusted, 1 conforming, 4 retained for lazy/public/backend responsibilities. Normalized object configuration, MinIO image names, FAISS/Chroma metadata projection and Milvus initialization/result mappings use their actual owners and typed local records. SDK/runtime dictionaries and stream boundaries retain validation.
- Independent review confirms image/URI key and metrics failure behavior; metadata copying, defaults, IDs, scoring/filter/order/refill; Milvus tuple ordering and result omission; tenant/document/dataset filters; retries/timeouts, client caching/refresh/shutdown, write flush and delete no-flush policies, iterator and response cleanup. Intentional qdrant/pgvector scaffolds keep existing behavior.
- Integrated Ruff/format/AST pass all 12 files; 318 static checks preserve 193 other bodies and bind 394 function/constructor calls. Independent baseline/current AST parsing and report hashes also match. No Python tests, storage/DB/provider services or live durability/cancellation probes ran. Evidence: `.superpowers/sdd/2026-11-02-style-unification/storage-adapters-report.json`.

## Document ingestion API boundaries

- Completed the 13 owned API/form/dispatch/canonical-owner files from amended source category `290545799`. Removed the unregistered source-ingestion workflow and duplicate API dispatch owner, trimmed the upload module to its three typed registered handlers, and bound document compatibility exports to canonical services. Seven canonical service/form bodies and all 14 route handler sources remain unchanged; the three active form declarations retain all 31 fields/defaults.
- Resolved the connector-aggregate overlap by keeping its service-owned assembly and two direct URL/HTML aliases, without restoring retired leader injection or provider modules. Static integrated API route/coverage checks, Ruff, formatting and AST pass; the category binds 393 direct calls and checks real patch consumer owners.
- Initial independent review found incomplete mock-binding migrations. The same unshared source category was amended to patch by-value consumer bindings, retain fake SessionLocal factories, synchronize source/file-path fixture shape and use the actual account keyword. Re-review passes; all 199 assertions across four migrated tests remain unchanged. Python tests were not run and no runtime pass is claimed.
- The root URL test's existing service-owner import/patch hunks are themselves required for this retirement. Those hunks are preserved and incorporated, with only its missing canonical dispatch import/import ordering supplemented; all 19 assertions are identical to the baseline. No unrelated root edits were staged. The preexisting document schema leading blank remains untouched.
- Removed the two retired source paths from the exact Git coverage manifest. Per-file callgraph, protected-reference handling, original findings, fixes, commands and runtime limits: `.superpowers/sdd/2026-11-02-style-unification/document-ingestion-boundaries-report.json`.

## Dify pure-helper ownership category

- Retired five duplicate API helper modules. The API and conversation adapter now import the existing service owners for constants, record normalization, scoring, anchors and content compaction. Seventeen route constants also have one definition. The HTTP client-IP helper moves unchanged to the HTTP adapter; its original API name remains available.
- All 302 API definitions and 40 existing adapter definitions have identical ASTs; the moved IP helper and all 17 constants match exactly. The five canonical modules are unchanged and reviewed in full. Typed UUID fallback and int/bool Settings differences match active callers, while raw citations, metadata and SQL row boundaries retain their existing validation.
- Independent review passes. Ruff check, Ruff format and AST parsing pass all eight surviving Python files; 149 migrated/helper imports resolve to actual owners. No tracked source references the deleted modules. The five canonical files close as conforming; the two large API modules keep pending status for their remaining behavior.
- Python test sources are unchanged and no Python tests, application imports, model/provider/API/database services or runtime retrieval were executed. The existing decision-note validators pass. Evidence: `.superpowers/sdd/2026-11-02-style-unification/dify-helper-ownership-report.json`.

## Embedding model and provider category

- Completed all 17 embedding modules from `0546bdb39`: 13 adjusted, two conforming and two public export barrels retained with explicit reasons. Two identical NumPy normalization methods now use the existing embedding utility; current-configuration fingerprinting uses the existing explicit-configuration owner. Constructor options, batch progress, connectivity status, triplet payloads and ranking rows declare their actual shapes.
- Independent review confirms normalization timing/zero vectors, fingerprints/cache identity, HTTP retries/timeouts/response closing, async cancellation, batch alignment and registered stateful classes. Declared Settings, Redis and httpx producers support direct access; raw provider JSON and optional dependency validation remain.
- Integrated Ruff check/format and Python 3.11 AST parsing pass all 17 files; category sources exactly match reviewed commit `22b4b4e64`. Static evidence checks 104 parameter/default contracts, 45 critical body comparisons, wire keys and normalization/hash equivalence. Existing note validators pass.
- No Python tests, business-module imports, downloads or model/Redis/HTTP provider services ran. Runtime embedding quality and concurrency remain unverified. Per-file evidence: `.superpowers/sdd/2026-11-02-style-unification/embedding-category-report.json`.

## Shared React component declaration category

- Formatted 11 files separately; emitted JavaScript ASTs match the pre-format source. All 16 existing component-declaration rule violations in 12 assigned files are resolved: ordinary shared components use exported functions, the private tooltip remains local, and five test wrapper factories return local declarations. Per-call QueryClient scope is preserved.
- Complete source review closes seven production components. The five test files receive declaration/reference and formatting evidence only; their other semantic review remains pending. Radix aliases, forwardRef wrappers, public exports, props, JSX, labels, classes, hooks, displayName bindings and assertions are preserved.
- Scoped ESLint/Prettier12, full TypeScript and eight existing Vitest files/36 tests pass on reviewed source `2d968d25c`. Integrated category files match that source exactly. An existing ignored NODE_PATH tool overlay resolves the locally absent eslint-config-prettier package; repository dependencies/config are unchanged. Source migration and formatting retain separate category commits.
- The merge's format/declaration overlaps were resolved only after proving all 12 pre-merge mainline blobs equal the formatter parent, then taking the exact reviewed blobs. No Python tests or browser visual checks ran for this declaration-only change. Evidence: `.superpowers/sdd/2026-11-02-style-unification/react-declarations-category-report.json`.

## LLM call and prompt contract category

- Completed all 16 LLM modules from `31b305095`: eight adjusted, one conforming and seven retained for public exports, prompt data or schema responsibilities. Two exact content-to-text implementations now share the existing prompt-cache owner; stream/client/callback/attempt/usage types describe actual producers, and validated structured output is serialized once. Stateful clients, prompt text and provider raw metadata boundaries remain.
- Independent source review passes: converter bodies, 65 parameter/default contracts, transport and fallback loops, exception/raise/export policies, 920 prompt literals and four structured Pydantic schemas are preserved. Integrated Ruff/format/AST pass 17 files including the actual API caller; the 16 category modules exactly match reviewed commit `ec1741121`. Existing note validators pass.
- Independent caller review corrected the author's original enum claim: 12 constructors used LLMRole expressions, but one selected nonexistent HUMAN. `_request_llm_clean_preview` raised AttributeError before the model call and the existing handler converted it to 502. It now uses the declared USER member, matching existing HumanMessage/wire-user mapping. The caller AST is otherwise identical; all 12 integrated producer members resolve. That API module retains pending status for its other behavior.
- No Python tests, application imports, provider/model/cache calls or live cleaning-preview request ran. Source verification does not prove provider behavior or runtime streaming. Exact checks and the producer correction are in `.superpowers/sdd/2026-11-02-style-unification/llm-category-report.json`.

## Document read, health and version API category

- Completed eight full API modules: six adjusted and two existing typed operation facades conforming. Direct declared ORM, SQL count/range/page fields, scorer output and multiset dataclass values replace repeated dynamic/coercion reads. Parsed-content download shares its existing dataset-access helper; version activation shares its existing hash validator. Version counters/dates/flags declare their actual local record shape.
- Independent review confirms tenant/dataset/document ACLs, nullable fields, local source path/size/truncation, raw metadata/PDF checks, timeline redaction and date/order policy, version JSON/database fallbacks and transaction/audit/index/KG cleanup boundaries. No new fallback or shared abstraction was introduced.
- Integrated Ruff/format and Python 3.11 AST parsing pass all eight files and match reviewed commit `9e94843ff`; all 21 route decorators/request parameters and transaction/resource operation sequences are preserved. No test source, Python test, application import, API/database/index operation or runtime source/DOCX retrieval was executed. Evidence: `.superpowers/sdd/2026-11-02-style-unification/document-read-api-report.json`.

## Reranker model and ranking category

- Completed all 18 reranker modules from `923272ef8`: 13 adjusted and five retained with explicit responsibilities. Async API scoring reuses the existing synchronous score parser after the same response-close sequence. Constructors/callbacks/SDK metadata and locally generated ranking rows have explicit contracts; declared Settings and SDK scalars replace repeated coercions.
- Independent review confirms alignment, missing/malformed result rows, indices, overwrite/default scores and logging; provider aliases/caps, disabled/shim fallback, request/retry/cancellation/cache behavior, LTR feature order/version/fingerprint and ranking ties remain. Raw provider response validation stays at the boundary.
- Integrated Ruff/format and Python 3.11 AST pass all 18 files; sources exactly match reviewed commit `908857697`. Static evidence preserves 156 parameter/default contracts, 138 critical bodies, all 40 accessed Settings fields, 14 registry families/25 aliases, feature specs and existing shim/hybrid caller ASTs. No tests, application imports, model/provider/cache requests or runtime ranking comparison ran. Evidence: `.superpowers/sdd/2026-11-02-style-unification/reranker-category-report.json`.

## Checkpointer persistence and snapshot category

- Completed five modules from `ae6c031f8`: four adjusted and the public LangGraph export barrel retained. History/single-checkpoint projection share one local mapper, while constructors, serializer and framework kwargs declare their existing contracts. Declared Settings and SQLite fetchall lists no longer use dynamic/default reads.
- Independent full source/SDK review confirms both time-travel methods exactly match baseline after inlining the mapper, including optional parent/timestamp, copies and failure/logging behavior. Stateful caches, memory locks, SQLite thread-local connections/autocommit/PRAGMA policy, schema/SQL/serialization and async delegate semantics remain. The custom memory module remains distinct from the exported LangGraph saver.
- Integrated Ruff/format and Python 3.11 AST pass all five files and exactly match reviewed commit `1ebace502`; 44 parameter/default contracts, 40 critical functions, 16 SQL execute/eight serializer calls, public dataclasses/wire shapes and actual caller ASTs are preserved. No Python tests, application imports, saver creation, database or graph execution ran. Evidence: `.superpowers/sdd/2026-11-02-style-unification/checkpointer-category-report.json`.

## Remaining frontend pure-format category

- Inventoried all 1,080 tracked web files and checked 965 eligible sources with the single Prettier3.9.10 configuration. Formatted 628 and verified 337 already conforming; 115 explicit exclusions retain their bytes, including the 17 active viewer files, public assets, generated contracts and lockfiles. All checked sources have per-file hashes and parser evidence.
- Every changed file passes syntax/value equivalence. The two explicit cases additionally prove an unchanged five-operand && evaluation order in the PDF capability check, and identical parsed embedded CSS plus surrounding code in the graph loader. JSON values/order, CSS parser structure and TS/JS/JSX literals/operators/exports retain their contracts.
- Full tracked ESLint has zero errors (one expected ignored generated Next declaration notice); full TypeScript and seven UI/API scripts pass. The first full tracked Vitest run reports413 passed/nine failed because positive source-snippet checks bind quotes/line wrapping. The contrast checker likewise binds selector quoting; those check-only follow-ups are handled separately. This commit makes no application logic change.
- Formatting does not close semantic review. Only the two proven generator-owned type files receive explicit preservation dispositions; all other semantic statuses remain. Per-file scope, exclusions, source assumptions and exact logs: `.superpowers/sdd/2026-11-02-style-unification/frontend-remaining-format-report.json`. No Python tests ran.

## Frontend source-check formatting follow-up

- Resolved the nine exact-source quote/line-wrap failures with the existing expectSourceToContain helper; all 12 original positive snippets, source inputs and remaining test ASTs are retained. Contrast extraction now uses existing PostCSS selector/declaration ownership, with normalization limited to the known theme attribute. Missing/invalid CSS and contrast violations still fail explicitly.
- Independent controller source review passes all ten changes. The same five surfaces, two modes, ten foreground/background pairs, thresholds and decision loop produce100 identical before/after ratios. No application UI/runtime code, config, dependency or permanent test/check framework was added in this follow-up.
- Focused nine files/31 tests and full tracked 128 files/422 tests pass; contrast100 pairs and scoped ESLint/Prettier10 pass. The earlier413/nine-failure formatter result remains recorded as the actual red baseline. The CSS checker closes its full source review; the nine tests receive reference/check evidence only and keep their other semantic review pending. Evidence: `.superpowers/sdd/2026-11-02-style-unification/frontend-source-checks-format-report.json`.

## Document viewer pure-format category

- The 17 remaining viewer files now use the same Prettier configuration as the rest of web. Source/emitted JavaScript comparison and independent review preserve runtime syntax, literal values, JSX output, callbacks and API behavior. Viewer logic remains a separate category.
- This completes formatting dispositions for tracked web code while retaining generated/static/unsupported files for their stated owners. It does not close the viewer's semantic review. Exact format/source evidence is linked from `.superpowers/sdd/2026-11-02-style-unification/document-viewer-category-report.json`; no Python tests ran.

## Document viewer state and operation ownership category

- Completed all17 viewer files:15 adjusted/two conforming. Types import actual domain/generated owners; pure parsing is outside the Hook, one-use forwarding and redundant primitive derivation are removed. Raw API/cache citation/numeric normalization, rendering, props and established compatibility fields remain. Eleven actual API call argument lists match after explicit immutable-ID/known-bool substitutions.
- Real source/reproduced regressions now keep delayed preview/read/error/finally/clipboard/RAF outcomes with the active document visit and latest request. Clear invalidates pending preview work. Editor and QA dialog lifecycles own UI publication; accepted original-document writes/reembed and legitimate document data updates continue. QA retains its existing real-job busy behavior across reopen. Late save rerun respects newer preview/clear/draft/editor intent; delete clears only its busy ID and the current matching store highlight. Accepted failures still report original document/chunk context.
- Independent final review passes exact `5eb20439e`;41 focused tests pass, with red/guard-removed proofs for disposed/current-dialog/newer-intent behavior. Scoped17 ESLint/Prettier, fullTypeScript and allfive UI/three API scripts pass. The two changed test modules retain actual behavior assertions and exercise the real Hook/shell; no Python tests ran.
- Clean E-drive composite source95edec269+all17 finalviewer blobs passes production Next webpack build, TypeScript,46 static pages and bundle budgets. Source manifests/hashes prove the intended integrated web tree; generated next-env changes stay in the disposable export. Full integrated unit suite is recorded separately when terminal results arrive.
- Actual browser runtime acceptance is incomplete: automatic approval review rejected both task-owned loopback Next server launches on51741 with only `blocked by policy`; no server/browser test, screenshot, console or network pass is claimed. Export and scratch cases are retained, and cleanup confirms no own listeners/processes. Evidence: `.superpowers/sdd/2026-11-02-style-unification/document-viewer-category-report.json` and `viewer-browser-acceptance-report.json`.

## Parse and chunk preview typed governance category

- Completed both preview modules and reviewed their existing option owner. Two40-field mappings now use the same GovernanceCleanOptions builder as ingestion; regex rules remain separate and compile at the original stage. Chunk preview preserves remove_common_lines=False. Pipeline/options/rules and fixed local page rows have actual types; known Document/provenance/count/flag values replace internal fallbacks/casts.
- File and by-SHA paths share the existing cache-key owner; stats reuse one pure coverage result. Raw JSON/metadata/plugin coercions, nullable materializer input, scopes, cache lock/recheck/LRU/TTL, positions/page order, truncation, timing/cancellation and cleanup retain their policies. Only impossible internal field/type absence loses speculative fallback.
- Independent full source/producer review passes:40 option fields/six remaining defaults,57 parameters/four Form dataclasses,three routes/30 HTTP errors, expression grouping and whitespace cache-version normalization, and symbolic by-SHA key expansion match. Integrated Ruff/format/AST sources exactly match `334828e17`; the existing five decision-note gates pass. Old ingestion/chunk-owner references in that note now point at current services.
- Python tests/test sources, application imports and parser/model/subprocess/database/API runtime were not run. Evidence: `.superpowers/sdd/2026-11-02-style-unification/document-preview-category-report.json`.

## Dify evidence dependency repair and integrated checks

- Full tracked Python checking exposed two import-order errors caused by nonexistent tracked type owners. The old Dify evidence adapter also referred to an evidence service existing only among protected untracked leftovers. All three references now use actual tracked ChatRAGConfig/EvidenceRetrieveRequest/retrieve_evidence definitions; the request/endpoint import remains lazy, matching the active Dify API's existing retrieval boundary. No residual files were copied or made authoritative.
- Independent full adapter/note review passes exact `b53295247`; body/signature AST is identical after precise owner substitution. Nineteen config fields/three request keys, the response model, member/tenant quota/readable scope, metadata filter, managed admission/budget/fallback/error paths and40-module top-level dependency closure were checked. Bigger API/service modules stay partial/pending.
- All1,886 tracked Python paths pass Ruff check/format with existing exclusions;1,811 self-owned sources parse as Python3.11. Static tracked app-module/namespace import checks find no missing absolute owners after the fix. No Python tests, business imports or live provider/database work ran. Evidence: `dify-evidence-owner-report.json`, `integrated-python-owner-fix-static.json` and `tracked-python-import-owner-after-fix.json` in the existing execution evidence directory.
- The exact1,080 committed web blobs match the successful viewer-composite build. One full integrated Vitest run passes all128 tracked files/460 tests, including41 viewer cases, with no failures/skips. Source hashes remain stable; only the build-generated next-env declaration differs in the disposable export. Production build/bundle proof and policy-blocked browser limits remain recorded separately; full-suite evidence: `viewer-integrated-full-vitest-report.json`.

## RAG workflow category

- Completed16 pending workflow modules from `30239c2f9`:14 adjusted, one conforming and the public barrel retained. Configured workflows/steps/handlers stay classes. Constructors, callbacks, kwargs and owned ReAct/critic/router/evaluation records now express actual contracts; local counters/typed Settings use direct values. Previously reviewed rerank-expand-rerank is unchanged.
- WorkflowPlanStep belongs with WorkflowState and describes the real planner writer. The plan union keeps legacy string lists/None; all15 state keys and total=False remain. No StateGraph/Pydantic/API/schema consumer exists for this annotation-only state. The actual graph uses its separate RAGState. Agent caller migration changes two type imports/annotations only and keeps its full review pending.
- Independent full source/producer review passes exact `783a83fc1`:19 existing classes/method order, six registry classes/15 aliases,121 parameter/default contracts,111 strict/121 explicitly normalized functions,37 nonempty dictionary shapes (36 string-key plus enum registry),45 f-string ASTs and exception/raise/export contracts preserved. Raw graph/LLM/middleware guards, state/event/prompt ordering and budgets/cancel/fallback/cache/store policy remain.
- Integrated Ruff/format pass18 files including the already-reviewed workflow and agent caller;16 owners parse as Python3.11 and sources match reviewed Git blobs. Existing note validators pass. No Python tests, application/model/service imports or execution ran. Per-file/source evidence: `rag-workflows-category-report.json` and `rag-workflows-category-independent-review.json` in the existing execution evidence directory.

## Shared authentication, backend and dataset data Hooks

- Completed eight shared data Hooks:seven adjusted and tenant access conforming. API/domain/generated types use their actual owners; connector list calls share one request function. Auth profile completion respects cancelled/current credentials, index reconciliation owns the actual document visit and request generation before POST, and late connector actions refresh original-scope cache without changing visible dataset selection.
- Independent full production-source/QueryProvider/storage/API/caller review passes exact `56e7c3097`. Eighteen ownership tests and the relevant12files/65tests pass; scoped10file ESLint/Prettier, fullTypeScript and existing note validators pass. Eleven public function contracts, query keys/cache policies, request payloads, status/error callbacks and original server operations remain. Test files receive focused additions/fixture review only and keep their other semantic review pending.
- Review additionally found a pre-existing lower-level API-core race: an OIDC refresh completing after login/logout can still overwrite/clear a new session before the Hook sees cancellation. This is tracked and assigned as a separate authentication-client category; these Hook checks do not claim that lower-level guarantee. Actual browser launch remains policy-blocked; no Python tests/services ran. Evidence: `shared-data-hooks-category-report.json` and `shared-data-hooks-independent-review.json` in the existing execution evidence directory.

## URL download and document asset identity boundaries

- Completed the URL helper and shared asset identity modules. Public IPv4/IPv6 types, actual is_global property, typed Settings and local byte/redirect values replace internal coercion/dynamic reads. Port tokens use only the real integer conversion exception. UUID/header text uses the actual Starlette/Settings/UUID input contracts.
- Independent full source/config-parser/options/caller review passes. SSRF scheme/credentials/host/IP/allowlist checks, all DNS answers, Host/SNI pinning, redirect revalidation, proxy policy, streaming size/cleanup/error paths and JWT/header/tenant conflict/anonymous opt-in/callback seams remain. All36 parameter contracts,27 HTTP error constructors and public dataclass ASTs are preserved.
- Scoped Ruff/format/AST and diff checks pass; sources have exact peer-reviewed hashes. No Python tests, application imports, live DNS/HTTP/download/JWT/database work or service launch ran. Evidence: `url-asset-boundaries-report.json` in the existing execution evidence directory.

## Task locks and worker runtime category

- Completed the remaining three task modules: locks and worker adjusted, public queue barrel retained. Tenant/dataset acquire share one local lifecycle implementation while retaining separate scope guards, unassigned-dataset handling, keys and logs. Retry/context/result signatures use actual Arq contracts; typed Settings/scalars replace repeated conversions.
- Independent source/SDK/caller review passes:26 parameter/body contracts after explicit helper inlining, WorkerSettings registration/heartbeat records, two Lua strings,12 Settings fields and four actual callers. Owner comparisons, retry/exhaustion/fail-open/closed, refresh None-versus-False, heartbeat stop/cancel/wait/TTL, import-time probe and startup/shutdown policy remain. Other queue/job/service modules only receive caller checks here.
- Scoped Ruff/format/AST and diff checks pass, with exact reviewed hashes. No Python tests, application/worker imports, socket probe, Redis, queue processing or service launch ran. Evidence: `task-runtime-category-report.json` in the existing execution evidence directory.

## Simple package import boundaries

- Individually read all51 pending packages whose complete executable structure consists only of documentation, direct imports and literal export lists. Empty/documentation-only namespaces conform; import barrels retain their existing public/registration responsibilities with actual owner names recorded per file. No package source was changed.
- Static source checks resolve178 imported names from84 actual tracked owner modules, verify duplicate-free __all__ subsets and Python3.11 syntax, and preserve exact source hashes. Packages with functions, lazy loaders, compatibility branches or output business logic were excluded for their own business reviews, as were the active22 agent/tool modules.
- These dispositions cover only the51 package bodies. Imported parser/evaluation/KG/safety/plugin implementations remain pending unless separately reviewed. No Python tests, application imports, registration execution or external services ran. Evidence: `package-boundaries-report.json` in the existing execution evidence directory.

## RAG agents, tools, memory and middleware category

- Completed22 pending runtime modules from `953e7e7d9`:12 adjusted, three conforming and seven public/compatibility boundaries retained. Stateful graph/runner/client/store/registry/middleware classes remain. Actual registry/result/model/SQL/timezone/callback/stream contracts replace missing types; typed Settings and local event values replace internal coercions. Two per-phase logging setups use one local configuration function while still creating separate instances.
- Additional source review removed remaining dynamic reads/coercions of nine proven ORM columns in seven MCP tool functions. Nullable ACL/count defaults and page-zero behavior remain; raw UUID/page/string/JSON/provider/middleware checks retain their policies. ToolResult is constructed by every registry return, so required result fields are read directly.
- Independent controller review passes final `fc6238460`;293 qualified parameter contracts and261 strict annotation-erased function bodies independently match. Explicit producer checks cover the remaining32 functions and shared logging calls. All144 wire-key shapes,76 prompt/event string ASTs,11 SQL calls, ten tool registrations,42 declared Settings and six unchanged caller ASTs retain contracts. Security allowlists, namespaces, scope/ACLs, cancellation, budgets, retries/fallbacks, ordering and resource cleanup remain.
- Integrated sources exactly match all22 reviewed blobs and pass scoped Ruff/format/AST3.11. The nine pre-POC scanner modules and broader external caller implementations remain pending. No Python tests, application/model/DB/network/services or launches ran. Evidence: `rag-agent-tools-category-report.json` and `rag-agent-tools-category-independent-review.json` in the existing execution evidence directory.

## Proof artifacts and quality CLI category

- Completed18 scripts in the parsing/answer/retrieval artifact, batch, gate, provenance and proof family: nine adjusted and nine already conforming. Private records describe locally built case/group/check/report rows; initialized floats/counts/bools and guaranteed result fields replace repeated coercions or shape checks. Raw files, argparse/JSON/report/provenance/capsule/threshold validation remain at existing boundaries.
- Independent full source/producer/caller review passes exact `bcf5acf61`:132 parameter/default contracts,116 CLI arguments,63 nonempty dictionary shapes,125 formatted strings, whole-module I/O/network/subprocess/path/error/print contracts remain. Exit values, output encoding/schema/order and fail-closed metric behavior are preserved. External runner/helper modules receive only targeted partial checks and stay in their own review categories.
- Integrated Ruff/format/AST3.11 pass all18 and match reviewed source blobs. No target CLI, Python tests, application imports, subprocess/network/model/service execution or new quality framework ran. Evidence: `proof-cli-category-report.json` in the existing execution evidence directory.

## Lazy package loaders and generated compatibility boundaries

- Completed11 owner modules: five adjusted and six intentional loader/compatibility/registry boundaries retained. Return/vararg types describe real API router/module and integrated dictionary-list exports; importlib is shared at the stdlib level. ModuleNotFoundError.name and the actual typed rerank caller/local profile value replace repeated coercions. Heavy imports stay lazy, with existing public aliases, cache/error policy, bootstrap compatibility and registry copies/order.
- Independent full source/owner/caller review passes `43217f22f`:16 normalized function bodies and44 router registration calls retain their behavior. The canonical integrated bridge returns list[dict], and its actual matrix consumer reads dictionaries. Scoped Ruff/format/AST11 and diff checks pass.
- Separately classified16 generated integrated_pipeline compatibility shims. Each has the exact four-operation forwarding template, unchanged bytes and an actual tracked canonical third-party target. They are preserved, not treated as reviewed third-party business implementations. Complex output and parse-bench package modules remain outside this category and pending.
- No Python tests, application/module imports, Conda/socket probes, lazy registry execution, third-party semantic audit or services ran. Evidence: `package-loaders-category-report.json`, `package-loaders-category-independent-review.json` and `generated-compatibility-report.json` in the existing execution evidence directory.

## Pre-POC scanner category

- Completed all eight pending scanner owners; the already-reviewed export barrel stays unchanged. Typed local similarity rows, Path suffixes, percentile inputs, initialized counters, match offsets/kinds and hit dictionaries use their actual producers; dashboard stream/result signatures are explicit. Raw row/text/length/page/threshold parsing and masks remain at their established boundaries.
- Independent controller full source/Settings/PII/secret/simhash/normalizer review passes exact `9b0366dc1`. All23 parameter/default contracts,25 dictionary shapes, seven schemas, four dashboard routes, request model and28 call bindings retain their contracts. Cluster selection/tie order, bins/percentiles, PDF thresholds, privacy masking/truncation, SSE and injected file callback/error policy remain.
- Integrated Ruff/format/AST3.11 match the eight reviewed Git blobs. No Python tests, application/scanner imports, dashboard/file/PDF scan, network/model/DB/service execution ran. Bigger scanner runners and preprocessing producers receive only targeted partial checks here. Evidence: `pre-poc-scanner-category-report.json` and `pre-poc-scanner-category-independent-review.json` in the existing execution evidence directory.

## Authentication refresh and replacement-session ownership

- Completed the actual auth storage/OIDC/Axios/authenticated-fetch owners and current profile Hook. A small revision in the existing storage owner distinguishes explicit login/logout, including same-user same-token replacements, from normal in-session token rotation. Requests gate refresh/credential writes/clear/retry and cancellation against their original session; the existing OIDC single-flight is scoped so a new session cannot inherit an old refresh.
- Independent review caught a composite gap in the first candidate: same-scope login deliberately emits no cache-scope event, so token/signal-only profile guards could still clear the replacement session. The final Hook keeps all `dfc299a5f` behavior and also checks captured revision before profile success/error publication. Existing scope-event/storage payload/query-key policies remain.
- Final independent review passes exact `890ea87a3` on parent319250809. Real Hook+QueryProvider+storage+authApi+Axios/OIDC tests reproduce three replacement races, then pass four cases including normal rotation; peer independently passes those four plus five existing Hook cases. The overall related17files/98tests,12file ESLint/Prettier, nonincremental fullTypeScript and existing note validators pass. Lower-owner reviewed blobs remain unchanged from the initial candidate; fixture-only files keep partial semantic review.
- Retry-once and real unauthorized/error responses, same-session refresh coalescing, cancellation, no-token/header behavior and token-free diagnostics retain their contracts. No real browser/IdP/backend service validation or launch was performed. Sources/tests/note in the integrated squash exactly match all13 reviewed blobs. Evidence: `auth-refresh-ownership-report.json` in the existing execution evidence directory.

## Locale entry and content resource category

- Completed the five executable locale owners: two request/layout entries now use the installed framework's hasLocale predicate and an explicit ReactNode type import; navigation, routing and evaluation redirect already conform. SDK client/server exports and implementation are verified: the predicate is the same includes check, and the real request locale is string/undefined. Invalid-layout404, fallback locale, params awaiting, setRequestLocale and redirect/message order stay intact.
- Individually read and preserved46 simple Next locale re-export entries, each pointing to an actual tracked shared page. Fourteen locale resources preserve13 literal catalogs plus one ordered composition,39 unique namespaces and five static String.raw templates without interpolation. No source/message content change occurred in these60 files. Imported page business logic and translation quality are not closed by resource/entry registration.
- Independent full executable-source/SDK and preservation review passes; scoped5 ESLint,2file Prettier and full nonincremental TypeScript pass. No test framework/extra helper/dependency was added for this equivalent predicate/type-only change. Actual404/navigation/browser/IdP/runtime rendering was not exercised under the existing service-launch restriction. Evidence: `locale-boundaries-category-report.json` and `locale-boundaries-independent-review.json` in the existing execution evidence directory.

## Table catalog, routing and graph planning category

- Completed five owners: catalog API, table path/ID helpers, bounded routing, schema graph and join statistics. Actual ORM/SDK/config/owned count fields are direct; graph records name the normalized table/relationship/candidate/beam/result contracts. Raw tables/aliases/columns/rows/thresholds and workbook boundaries keep their validation. Path helper reads current settings through one local owner.
- Deleted165 lines from a closed obsolete TAG relationship island: nine private functions, one private record and two constants. Current public inference already uses the canonical graph; all65 surviving TAG functions and complete remaining module AST are exact. TAG SQL/model/query responsibilities remain pending, with no full-module closure claimed.
- Independent full-five/partial-TAG review passes:110 parameter/default contracts,26 graph functions with133 exact scoped rewrite rules/141 occurrences,30 dictionary shapes,17 SQL/resource/transaction operations and three DB routes preserved. Seed states have one join/ID and expansions append one, with no external state-helper callers; direct fields/averages retain score/hash/tie/beam/cap/ambiguity order. Copies, huge-row float handling, FLS/tenant/entitlement/cache/privacy and audit policy remain.
- Integrated Ruff/format/AST3.11 and source hashes match the reviewed category; focused note validators pass. No Python tests, application imports, SQLite/workbooks/scans/CLI/model/network/services ran. Evidence: `table-catalog-category-report.json` and `table-graph-expression-rules.json` in the existing execution evidence directory.

## Governance cleaning and normalization owners

- Completed25 preprocessing owners:18 adjusted and seven conforming. Actual local records/provider/result contracts replace internal conversions and two private forwarding helpers. Raw HTML/Markdown/JSON/model/regex input boundaries remain, as do privacy masks/hit budgets, language/keyword behavior, metadata copies, caches/locks and real provider/resource classes. The larger processor and seven other runtime/tagger/diagnostic/dedup/token owners remain pending.
- Independent snapshot-only full source/producer/caller review passes exact `952dec1e5`:162 parameter/default contracts,130 strict annotation-erased functions plus32 source-reviewed bodies,19 dataclasses,78 regex declarations, five schemas,26 dictionary shapes,41 formatted strings and seven raise expressions retained. All315 actual direct calls across62 files (132 external) plus two six-key dynamic mappings bind the intended contracts.
- Integrated25 source blobs match reviewed Git and pass Ruff/format/AST3.11. Existing barrel and eight deferred owners are unchanged; no borrowed producer check closes their full review. No Python tests, application imports, cleaning/scanner/model/network/DB/filesystem/service execution or launches ran. Evidence: `governance-cleaning-category-report.json` and `governance-cleaning-independent-review.json` in the existing execution evidence directory.

## Shared form and action UI primitives

- Completed24 primitive owners: seven adjusted and17 conforming. Switch composes public click handlers once while respecting prevention/disabled/controlled behavior; TagInput enforces capacity before every append; SearchInput clear respects disabled/readOnly; IconButton asChild keeps Slot's one-child contract; Progress forwards value/max and uses matching SDK range semantics. Badge uses direct function export, and unread private status-icon metadata is removed without changing public props or rendered design.
- Independent full source/test/note/installed SDK/representative-consumer review passes exact `826e66e9c`. Twenty real DOM contract cases pass; six related test files/47 cases and fullTypeScript independently pass. Public exports24/type aliases15, class attributes77 and CVA4 remain, with17 unchanged owner blobs exact. Reports distinguish current live consumers from public prop combinations exercised only by DOM tests.
- Author scoped25-file ESLint/Prettier, five existing UI checks and note validators pass. Controller rechecks changed production/test lint/format with the existing installed tool overlay; peer rerun dependency gaps are retained separately. No live page/browser/visual/real-keyboard integration or service launch is claimed. Evidence: `ui-primitives-category-report.json` in the existing execution evidence directory.

## Table store import and SELECT execution owner

- Completed the full table-store service. DataFrame/ExcelFile and locally created DOCX paragraph/cell/table values use actual SDK contracts; typed limits/options/counts/flags and parsed TableId fields replace repeated internal conversions. Query rows, public query result and planner mismatch dictionaries now name their real output shapes. Declared SQLite timeout keeps the original0..120 clamp.
- Independent full source/installed SDK/caller review passes. All62 existing function/class bodies match after65 exact scoped rules/70 occurrences and type additions;64 parameters/defaults, six dictionary shapes/eight regexes and11 core authorizer/query/raw functions are preserved. Ninety-three calls including21external bind the intended signatures. SELECT-only, allow/deny tables/actions, progress/size/time budgets, SQL fingerprints, reset/import/transactions/close, format order and fallback/errors remain. Raw JSON/NumPy/metadata/optional XML capability boundaries stay intact.
- Integrated source hashes match the frozen reviewed owner and pass Ruff/format/AST3.11/diff. No Python tests, app imports, pandas/docx/SQLite/file-processing runtime, workbook scans, network or services ran. API/TAG/chat/processor consumers remain partial until their own full review. Evidence: `table-store-operations-report.json` and `table-store-expression-rules.json` in the existing execution evidence directory.

## Document list, polling, mutation, upload and local search Hooks

- Completed seven production owners. Actual React Query entity/parameters captured at user intent own action/upload/poll publication; dataset navigation can update the originating live cache, while removed queries prevent old results or later batch requests. Existing keys/cache freshness/retry/upload limits remain. Removal subscriptions retire placeholders/errors without relying on an unrelated rerender, and live-query switch placeholders keep their established behavior.
- Per-document poll objects invalidate cancel/replacement/unmount/status/detail/reschedule work, idempotent delete projection avoids decrementing server-refreshed totals, equal initial-prop objects preserve explicit list parameters, and MiniSearch derives current results after constructing its current-data index. Public composition/action/upload/search signatures, API mutation/status/detail arguments and existing shared helpers remain. The list GET now forwards its existing AbortSignal option; retired operations reject CancelledError instead of fabricating completion.
- Independent full-source/QueryCore/API/consumer review passes exact `fcb7225b9`. Author baseline15 failures/eight positive controls and final five files/43 tests are verified; after integration the two changed behavior files pass36 tests, scoped lint/format pass, and production/new test blobs equal the reviewed source. The existing lifecycle fixture is merged with the current auth revision getter; no auth/viewer/query-key owner is changed. Full typecheck passed in the category.
- Precision correction in the reviewed note/report: getStatus lacks abort support; documentApi.get already supports request.signal in its third parameter, but this polling Hook continues its single-argument call. An old detail request may complete; ownership prevents later publication/rescheduling. No browser/service/Python runtime validation is claimed. Existing note validators pass. Evidence: `document-query-hooks-category-report.json` and `document-hooks-integrated-focused.json` in the existing execution evidence directory.

## Dataset table API owner

- Completed the full table API. Actual Dataset/TenantMember/TableId/FLS/Pandas/SQLite/LotusAvailability types and required query result fields replace dynamic internal reads/coercions. Preview and SQL query reuse the existing FLS row projection at their original stage, retaining redaction/audit/copy order. Raw metadata/model SQL/nested payload parsing remains.
- Two confirmed local SDK defects are fixed: pandas column Index cannot be used with `or []`; it raises ValueError, skipping FLS preparation or failing a filtered response. Both actual DataFrame producers now have direct column iteration. This fixes the local API contracts; the separately pending LOTUS bridge has another pre-existing columns-or[] path, so end-to-end LOTUS success is not claimed.
- Independent full-owner/producer/SDK/note review passes the frozen hash:40 functions/parameters, six routes with complete requests,20 HTTP constructors,22 ACL calls, nine filter/order/transaction/resource calls and14 unchanged raw/privacy/error helpers retain contracts. Strict mismatch, tenant/dataset/document binding, result egress caps, SQL read-only and optional fallback policy remain. Integrated Ruff/format/AST pass.
- No Python tests, application imports, pandas/SQLite/workbook/model/network/services or live FLS/LOTUS request ran. Imported TAG/FLS/bridge business owners remain partial until their own categories. Evidence: `table-api-category-report.json` and `table-api-expression-rules.json` in the existing execution evidence directory.

## LOTUS row payload and semantic filtering bridge

- Completed the full bridge owner. DataFrame columns are iterated directly, fixing the same confirmed pandas Index boolean-evaluation defect found in the table API. Declared bool/int Settings and owned string keys/caps replace duplicate internal conversions; existing zero-value defaults remain.
- Independent complete source/actual caller/config/installed SDK review passes exact `f70923150`. All11 function signatures/defaults, five raw/model/instruction boundary helpers, exception/raise/prompt/class ASTs, feature/row-egress guards, limits, sequential requests, index/length alignment and fallback behavior retain their contracts. The integrated owner equals the reviewed Git blob.
- Fresh integrated Ruff/format/AST3.11 and user-schema hash checks pass. No Python tests, app/pandas/model imports, database/network/file-processing execution or end-to-end LOTUS request ran. Evidence: `lotus-bridge-category-report.json` and `lotus-bridge-independent-review.json` in the existing execution evidence directory.

## UI animation, media query and resize Hooks

- Completed the three remaining UI-only Hooks: animation and resize adjusted, media query conforming with exact unchanged source. A resting spring now uses the current formatter; a conditionally mounted/replaced DOM target owns one observer and its pending frame, while unchanged targets keep the existing observation. Initial/reduced-motion behavior, size coalescing/filtering, breakpoint queries and server/legacy subscription behavior remain.
- Independent complete source/installed SDK/actual consumer/test review passes exact `ef3589086`. All six public exports/parameters/defaults retain contracts; the only return annotation names the existing string. The diagnostics consumer's actual empty-data early return establishes the delayed ref target. The new regression file is fully reviewed; two existing test files and broader graph consumers retain partial scope.
- Fresh integrated three-file11-case Vitest, four-file ESLint/Prettier, exact reviewed-blob and user-schema checks pass. Author full nonincremental TypeScript passes. These DOM checks do not establish real browser observer delivery, visual layout or animation performance; no service/browser launch ran. Evidence: `ui-hooks-category-report.json` and `ui-hooks-independent-vitest.json` in the existing execution evidence directory.

## Complete frontend formatting gate

- The exact tracked `7586ec51c` export passes131 Vitest files/546 cases, full nonincremental TypeScript, ESLint, all eight existing UI/API scripts and the full Python static gate (1,886 tracked Python paths with configured exclusions;1,811 self-owned AST3.11 parses). It contains no original untracked residue. Its complete Prettier check actually fails five paths; the historical report now records that failure instead of leaving it running.
- Format-only category `fa0c34099` formats the two README files, the trusted-forwarding declaration and tsconfig; JSON values, TypeScript child AST and every nonblank documentation line remain exact. The declaration's complete signature matches the actual Node HTTP consumer/implementation. Root `/next-env.d.ts` is explicitly excluded as an existing generated owner; its source remains unchanged.
- Complete isolated frontend `Prettier --check .` passes after these changes. A separate checkout-only globals.css CRLF warning was resolved to its exact already-committed LF blob, producing no Git change. These records prove the named historical snapshots and formatting category; later frontend changes require their own integration checks. Evidence: `integrated-7586-acceptance-report.json`, `integrated-7586-python-static.json` and `format-gate-completion-prettier.log` in the existing execution evidence directory. No Python tests or browser/service launch ran.

## Field/connection redaction and document metadata policy owners

- Completed four pending policy/metadata owners from exact `7db919baf`: FLS and metadata operations adjusted; SQL/connection redaction and canonical user merge conform unchanged. Validated FLS fields, ORM status and string patch keys replace internal conversions; the sole forwarding regex helper exits. Raw validation, errors, first-match allowlists/masks, regex order, caps/copies, tenant/write ACL and commit/refresh/audit/rollback policy remain.
- Independent complete source/model/producer/caller review and fresh four-module snapshot comparison pass:25 retained signatures/defaults,18 strict bodies,17 scoped expressions,24 raises,12 formatted strings, six regex/transaction calls and45 bound calls. No outside caller signature migration is needed.
- Integration review additionally found and removed four unused duplicate merge/tag/note functions in `document_metadata_service.py`. All tracked write callers already use `document_user_metadata.py`; the complete remaining response-metadata service has six exact unchanged function ASTs. Its full owner was re-reviewed, and the ownership/exit decision is recorded in the new note. No second forwarding entry is introduced.
- Fresh five-owner Ruff/format/AST3.11, note checks, exact coverage and original user-schema hash checks pass. No Python tests, application/SQL/model/network/file-processing execution or services ran; runtime equivalence is not claimed. Evidence: `redaction-policies-category-report.json`, `redaction-policies-independent-source.json` and `document-user-metadata-independent-source.json` in the existing execution evidence directory.

## Chat session, stream, recovery and formatter Hooks

- Completed all five chat Hook owners. Token strings keep whitespace/newlines; the current controller, mounted state and existing auth revision/scope own publication. Clear/reset/navigation discard old work, while explicit stop retains the existing partial answer. Accepted SSE errors and stopped failures cannot issue a second fallback chat; the existing pre-acceptance fallback remains.
- History clear/reset/auth/unmount retire old loads and synchronously maintain the messages ref. Initial conversation links load history; stable navigation functions avoid restarting the real ChatArea effect on transient renders. Recovery's own signal cancels waits/further reads while keeping the four-attempt/500ms/40-message defaults and allowing timeout recovery. Existing request options, history window, query keys, API arguments, error text and formatter bodies except token preservation retain contracts.
- Independent full source/actual API/auth/QueryCore/consumer/note/test review accepts exact `fbaeea650`; all nine integrated blobs match. A clean isolated integration with current document/auth/UI changes independently passes eight files/62 Vitest cases, full nonincremental TypeScript and eight-file ESLint/Prettier. The author's27 Hook cases reproduce16 baseline failures with11 controls; the17-case new file is fully reviewed, while supporting existing tests retain their prior partial dispositions.
- Final related tests use `--no-file-parallelism`. Earlier parallel auth suites exchanged real BroadcastChannel session-clear events; Hook fixtures isolate that external transport, and unchanged authentication tests/config are retained. In-flight backend writes/getMessages reads can still finish; retired results cannot publish. No live browser/backend/SSE or Python validation ran. Evidence: `chat-hooks-category-report.json`, `chat-hooks-independent-vitest.json`, `chat-hooks-independent-tsc.log` and `chat-hooks-independent-lint.log` in the existing execution evidence directory.

## Governance preprocessing runtime owners

- Completed all eight deferred runtime owners: processor, CPU/LLM taggers, diagnostics, optional HTML/XPath, near dedup, SimHash and BM25 tokenization. Required result/model/SDK fields and locally produced strings/counts/copies replace speculative dynamic reads and reparsing; stateful/configured classes remain. Raw model/JSON/Jieba/options/provider boundaries, meaningful optional metrics, phase/patch order, sidecar failure/atomic-write policy, tokenizer cache/budgets and output records remain.
- Independent complete source/actual producer/caller review accepts final amended `f9aaf6198`; old `6760e3695` remains on its preserved branch. The final review removes seven remaining dynamic reads/conversions using six declared Settings fields and the pinned SDK Document.id. Existing or-8/or-128/or-100 zero/default semantics remain.
- Fresh exact-snapshot comparison passes eight complete normalized modules,97 signatures/defaults,64 strict and33 scoped function bodies,18 regex calls,24 exception handlers,197 bound calls across32 callers and the43-key legacy kwargs mapping. Config and SDK declarations are independently proved. All integrated blobs match; fresh eight-file Ruff/format/AST3.11 and user-schema hash checks pass.
- Existing25 cleaning owners are unchanged. No Python tests, app/config/SDK/model imports, parsing/dedup/file-processing runtime, services or network ran; static contracts do not prove runtime equivalence. Evidence: `governance-runtime-category-report.json` and `governance-runtime-independent-source.json` in the existing execution evidence directory.

## Integrated frontend acceptance at a9001cba6

- Exported all3,754 exact tracked blobs directly from Git, including1,085 web blobs; six model symlinks remain inert link text and no original untracked residue enters validation. All133 Vitest files/574 cases pass with serial files. Full ESLint, complete Prettier and all eight existing UI/API scripts pass.
- A fresh Next webpack production build passes compilation and TypeScript, generates46 static pages and passes the existing bundle budget. Post-build comparison of every exported tracked blob finds only the generated next-env declaration changed; all manually maintained source remains exact. Existing next-intl cache-dependency, Browserslist-data and external module-type warnings remain; no dependency/config change was made to hide them.
- This proves the named integrated snapshot and its unchanged frontend descendants, not completion of the remaining file review. Real browser/service acceptance remains unexecuted: automatic approval review previously rejected the local server launch as `blocked by policy`, and that action was not retried. No Python tests ran. Evidence: `integrated-a900-acceptance-report.json` and its source manifest, build/budget/Vitest/ESLint/Prettier/UI-API artifacts in the existing execution evidence directory.

## Document assets, source persistence, manual indexing and dispatch

- Completed four pending full owners: asset authorization and source persistence conform unchanged; manual indexing and dispatch adjusted. The sole append helper is inlined so the seven IndexRecord fields are visible at their existing chunk-loop step. Three queue-policy wrapper calls read the same declared flag at the same points; the helper that always raises now declares NoReturn. Two shallow unused-outside-owner helpers exit without a new wrapper.
- Independent review accepts exact `369539b5c`: complete four-module AST comparison after the four precise inlinings/type addition,51 retained callables/45 top-level parameter contracts, exact record arguments/aliases and zero outside helper consumers. Tenant/dataset/document/preview ACLs, raw UUID/path/binding/metadata boundaries, source leases, ambiguous commit durability, queue acceptance/no duplicate handoff, error codes, resource cleanup/cancellation, budgets and KG sidecar policy retain their owners.
- Source hashes, Python3.11 syntax, scoped Ruff/format and diff checks pass. Broader API/ingestion/preview/indexer dependencies were inspected only for these contracts and remain partial. No Python tests, application/storage/DB/indexing/model/network runtime or service launch ran. Evidence: `document-lifecycle-category-report.json`, `document-lifecycle-source-evidence.json` and `document-lifecycle-independent-review.json` in the existing execution evidence directory.

## Complete Python static gate through document lifecycle integration

- On exact `369539b5c`, all1,886 tracked Python paths pass Ruff check/format in76 bounded invocations with the existing configured third-party/generated/history exclusions. All1,811 self-owned sources parse using Python3.11 grammar. Every Python/config Git blob matches integrated `3b1f71f98`; the original dirty user schema remains separate and unchanged.
- No Python tests, application/config/provider imports or processing execution ran. These static results do not close pending semantic reviews. Evidence: `document-lifecycle-full-python-static.json`; the integrated acceptance report links this follow-up separately from its earlier frontend snapshot.

## Complete table and chat TAG services

- Completed both surviving TAG service owners, including all2,775 baseline lines and115 original functions. Required query/diagnostic/ORM/candidate fields and Settings replace speculative revalidation; two private adapters and one duplicate dtype tuple exit. The owned diagnostic result has a concrete seven-field type. Existing state/planning records and public compatibility wrappers retain their responsibilities.
- Independent source/producer/caller review accepts final amended `80dfa3659`, with `12ac2beb3` preserved separately. The final audit removes the remaining owned record casts, retaining three real UUID serializations. All113 retained parameter/default contracts,77 strict functions,124 exact scoped rules/126 occurrences,35 formatted strings (three precisely normalized owned sheet indices),12 raises,33 key shapes,14 regex calls, four prompts and two query/ORM calls retain contracts.225 direct calls and both local kwargs mappings bind their actual owners.
- SQL text/quoting/fingerprints, candidate sort/order, source-key/document/tenant scope, budgets, row/result egress, strict ambiguity/low-confidence/mismatch and failure fallback policies remain. The existing fake query result receives only its real producer's neutral required mismatch record; removing that field restores the entire previous test AST. No cases/assertions/helpers were added, no Python tests ran, and the test's full review remains deferred.
- Integrated two-owner/necessary-fixture Ruff/format/AST3.11, note/diff, exact reviewed-blob and user-schema checks pass. No application, SQL, workbook, model, network or service execution ran; runtime equivalence is not claimed. Evidence: `table-chat-tag-category-report.json` and `table-chat-tag-independent-source.json` in the existing execution evidence directory.
