# 全项目代码风格统一重构计划

> 执行方式：继续在本会话按 `superpowers:executing-plans` 逐项实施；已确认的分支和执行方式沿用。

**目标：** 同类业务采用一致、直观的写法，读入口即可追踪数据、依赖和失败路径；减少重复实现与无依据防御，不以拆文件数量或复杂度分数作为完成标准。

**结构：** 后端沿现有业务所有者组织模块函数；有状态、资源生命周期和框架要求的类保留。前端按业务职责组织页面、组件、Hook 与类型，稳定复用才进入共享层。定义、调用方和错误转换在一个业务批次内闭合。

**技术栈：** 现有 Python 3.11+、FastAPI、SQLAlchemy、React、Next.js、TypeScript；沿用 Ruff、ESLint、Prettier 与 pnpm。

**依据：** 本会话已批准的全项目计划、2026-11-02 的后续要求、`AGENTS.md`、`.github/CONTRIBUTING.md` 和 `DESIGN_MEMORY.md`。本文件是唯一的全仓实施计划；已有覆盖表与验证记录继续使用。

## 1. 当前进度与执行位置

- 主工作区：`E:/MimirQ`；分支：`codex/local-account-registration`。为提速，独立业务类别可从当前 HEAD 建立 `codex/*` 分支和 worktree；类别代码与调用方完成审阅后合并回此分支。
- 原始基线：`77b6adc1bce523482f0509302a454ce20e01c41c`；数据集服务已提交为 `2c16dedf8`。前两批及第三批此前结果保留，不重新执行。
- 当前覆盖表有 3,758 个文件：223 个已调整、89 个已符合、985 个登记保留、2,461 个待语义审核。纯排版结果另记，不能据此关闭语义审核。
- Task 3A 的 125 个 Python 文件已完成最终静态核对并按数据集类别提交；Task 3B 的权限、配额、SCIM、配置、通用 API、身份令牌、共享资源与健康观测已完成本轮代码整理与静态检查，继续核对其余基础模块。原有 `app/api/schemas/document.py` 修改另行保留。
- 原工作区的 1,625 个未跟踪文件及其他既有修改保留；只按本批明确文件清单暂存，不使用 `git add .`，不执行全仓清理或重置。
- 用户执行要求：提交按完整业务类别归并，不按函数、文件或每个检查步骤频繁提交；同一类别的定义、调用方、必要引用和验证记录一起提交。纯格式化仍独立成类。
- 已完成并合并的并行类别分支：Task 5 dataset route planning/query contracts/query preparation/hybrid fusion/channel retrieval/lexical-sparse/context expansion/hierarchy owner/rerank cache/retrieval policy/trace diagnostics、Task 3 chat runtime/turn persistence/memory/dataset profile/precheck、Task 4 batch ingestion/document dispatch/identity-lifecycle/parser models/parser backends/parser structure/table rendering/OCR enrichment、Task 6 settings API/settings sections/system/auth/access/documents/chat APIs/common/feedback types、Task 7 model bootstrap/diagnostics CLIs；后续分支以最新主工作区提交为基线，不能把原有未提交文件带入提交。

## 2. 已选定的统一标准

| 方面 | 约定 |
| --- | --- |
| Python 服务 | 普通业务用模块函数，依赖由明确参数或实际所有者导入表达；保留有状态、生命周期、领域含义或框架要求的类。 |
| Python 排版与类型 | PEP 8 + Ruff，120 列；类型写在签名中，注释解释规则、限制和原因。保持 Python 3.11 兼容。 |
| 错误处理 | 优先复用明确业务异常，由 API、任务或 CLI 入口转换；迁移现有 `HTTPException` 时同时核对捕获方、状态码、载荷和认证头。 |
| React 组织 | 组件内聚；有复用或独立职责才提取 Hook、子组件。纯转换用普通函数，Hook 管状态和副作用。 |
| 组件声明 | 普通具名组件使用 `export function`；事件和数组回调可用箭头函数；保留框架导出、私有组件及必要包装形式。 |
| TypeScript 类型 | 应用对象、Props、联合类型优先 `type`；声明合并、库扩展保留 `interface`，生成类型不手改。 |
| 前端排版 | Prettier 两空格、单引号、无分号、120 列，JSX 属性双引号；ESLint 管代码规则。 |

## 3. Skill 如何用于本次改造

Skill 安装目录为 `C:/Users/jiahuanl/.codex/skills/`。项目已选规则和用户后续要求优先；进入具体问题时读取对应参考，不预先叠加所有工具与流程。

| Skill | 本次用途与适用边界 |
| --- | --- |
| `refactor` | 每次处理一个可说明的结构问题；先查定义和调用方，完成迁移后检查并提交。外部行为保持兼容。 |
| `revise` | 从入口往实现复查命名、导入、函数顺序、职责和重复转发。沿项目模块函数约定，不套用静态方法回迁、`if True` 分组或普遍注释标签。 |
| `oil-frontend` | 明确页面、组件、Hook、类型和请求的所有者；数据来源唯一，失败保留内容，一次用户操作只提交一次。配合 `oil-ui-pro` 检查真实页面。 |
| `py-refactor` | 作为 Python 工作顺序：有实证的安全问题优先，再处理重复规则、死代码和难读控制流，最后整理语法与排版。 |
| `py-code-health` | 找重复实现、无用导入、旧入口和转发包装；删除前核对注册、反射、插件及框架使用，静态无引用仅是线索。 |
| `py-complexity` | 发现多层嵌套、分支重复、超长职责和重复参数映射；只在改善阅读时拆分，不设置每函数行数或全仓复杂度达标指标。 |
| `py-security` | 在触及的业务链核对鉴权、租户条件、SQL、命令执行与外部输入；扫描告警需确认真实数据流，不把全部防御判断当作问题。 |
| `py-test-quality` | 按用户要求，本次不启用 Python 覆盖率、mutation testing、测试补写或测试质量整改。 |
| `py-modernize` | 只按需采用项目当前版本支持的惯用写法；不升级 Python、不迁移包管理器、不混入依赖升级。 |
| `py-quality-setup` | 复用已配置的 Ruff 等工具；有具体缺口才补现有配置，不另建整套 mypy／basedpyright 门禁。 |
| `py-git-hooks` | 本次不新增 Git hooks 或 CI 门禁；先完成现有业务代码改造。 |

继续配合已安装的 `python-patterns` 和项目要求的 `avoid-overdefensive-programming`：优先可读、显式类型和具体异常，核实输入契约后移除重复转换与无依据兜底。

## 4. 改造边界与逐文件识别方式

- 公开路由、请求及响应字段、状态码、错误格式、认证头、事件和配置含义保持兼容。不同入口原有的 400／403／404／422 不能被重构顺手改变。
- 外部输入、鉴权、租户隔离、事务及已定义的降级、重试、超时、取消、缓存与检索排序保留。类、`getattr`、异常捕获或判空本身都不是删除理由。
- 不新增通用 Context、整个模块的 `Any` 注入、无复用转发层、万能配置驱动框架或旧类兼容外壳。业务直接依赖实际所有者，共享请求模型归入所属 schema。
- 前端沿用已确认的 Ragvia 方向、`DESIGN_MEMORY.md` 的布局和交互及现有组件；本次不重新设计品牌，不从未跟踪残留导入实现。
- 本地仅运行前端、API 与必要 PostgreSQL；不为重构启动完整容器栈、解析器或模型服务。
- **Python 测试本次暂缓：** 不新增、扩写或运行；旧符号删除涉及的 import、patch 和 fixture 引用仅做必要同步。测试文件登记为用户要求保留，不能标为已做语义或测试质量审核。生产代码不能因文件名带 `test` 而跳过，例如 `app/rag/evaluation/test_generator.py`。

每批依次执行以下步骤，覆盖表沿用 `path / batch / review_status / format_status / reason / evidence`，不另建重复台账：

1. 从 `git ls-files` 与现有覆盖表确定本批自研文件；新建文件明确补入，第三方、生成代码、已发布历史迁移和静态资源注明保留理由。
2. 用现有 Ruff、源码搜索和必要的 AST 检查找候选：纯静态类、重复 UUID／字符串转换、已声明属性的动态读取、宽泛异常后返回成功默认值、单次转发、重复映射、无用代码；前端同时找重复状态、重复请求和重复类型。
3. 按调用链确认候选是否真的多余。比如 `_coerce_uuid(raw: object)`：已是 `UUID` 的内部输入直接使用；外部字符串的校验及原错误表现留在真实入口。不能全仓搜索后批量删除同名函数。
4. 修改业务所有者及全部实际调用方，再从入口顺序阅读一次；新抽取必须减少维护点，不能只把条件分支挪到更多文件。
5. 记录“已调整”“已符合”或“有理由保留”及证据；仅机械替换的调用文件仍待完整语义审核。检查通过、记录补齐并提交本批后，再进入下一片业务。

## 5. 重点核对的五类行为

| 条件 | 预期保留的行为 | 所属任务与核对方式 |
| --- | --- | --- |
| 成员不存在、停用或跨租户访问 | 原有拒绝路径和错误响应继续生效 | Task 3：逐入口核对身份、租户条件和异常映射；Python 运行时回归本次未做。 |
| ACL 更新失败、空成员或组列表 | 清空、去重、数量上限及提交／刷新／回滚顺序保持一致 | Task 3A、4：核对 schema、ORM 约束、循环与事务顺序。 |
| 上传重试、任务取消或资源释放 | 不重复入库，取消和失败不变成成功状态 | Task 4：核对任务状态迁移、幂等键和资源生命周期；依赖外部服务的结果单列。 |
| 前端旧请求晚到、刷新或保存失败 | 结果归属正确，已有列表和编辑内容保留，操作范围明确 | Task 6：现有相关检查及真实入口操作。 |
| 检索无结果、模型失败、预算耗尽 | 保留排序、阈值、流事件和既定降级，不用空结果掩盖故障 | Task 5：核对调用、配置及异常路径；没有运行证据时明确未验证。 |

## 6. 分批实施

### Task 1：基线与工具（已完成）

文件：`ruff.toml`、`web/eslint.config.js`、`.prettierrc.json`、`.github/CONTRIBUTING.md`、覆盖表和验证记录。

- [x] 建立原始失败记录、逐文件覆盖表及选定配置。
- [x] Python 纯排版单独提交，原有 1,724 个自研 Python 文件排版前后 AST 一致。
- [x] 记录前端类型、检查、单元和生产构建基线；保留 Python 历史失败归属。

本批不因新增 Skill 重做工具搭建。此前已运行的测试结果只证明当时版本。

### Task 2：认证与数据集页面样板（已完成）

入口：`app/services/user_service.py`、`app/api/v1/auth.py` 及 SAML 调用方；`web/components/datasets/datasets-page.tsx`、`web/hooks/use-datasets.ts`、`web/types/datasets.ts`。

- [x] 用户服务改模块函数，调用方和配置依赖同步。
- [x] 数据集列表落实具名组件、共享类型、加载／空／失败及缓存刷新状态。
- [x] 已验证的样板和实际证据见 `docs/maintenance/style-unification/verification.md`；其余同目录文件不自动算完成。

### Task 3：基础后端（进行中）

**3A：数据集服务已完成，类别提交 `2c16dedf8`。**

文件：`app/services/dataset_service.py`、`app/api/v1/datasets.py`、已迁移的文档／连接器／RAG 调用文件，以及本轮明确的 52 个既有测试引用文件。接口保留 `ensure_member(db, tenant_id, account_id)`、`get_dataset(db, tenant_id, dataset_id)` 等现有模块函数，供实际调用方直接使用。

- [x] 对照已有修改前和结构迁移快照复查 125 个文件；区分服务内部简化、精确调用替换和两个特殊 fixture 调整，不能沿用内部简化之前的 AST 通过结果作为最终证据。
- [x] 逐项核对 UUID／成员类型、本地 owner 引导条件、组数量限制、ACL 审计和事务顺序；当前 `HTTPException` 先保留，错误边界迁移另行处理。
- [x] 查清旧三个静态类及路由装配器反向取服务的生产引用；既有测试 stub 的同名类需按用途判断，不能机械删除。最终对这 125 个文件运行 Ruff check、format --check、语法与调用关系核对。
- [x] 用 `revise` 复查入口阅读、命名、重复转发和导入；尤其人工审阅 `tests/test_complexity_batch12.py` 与 `tests/test_evidence_capsules_tenant_isolation.py` 的必要 patch 同步，不运行测试。
- [x] 补验证记录与实际审核文件的覆盖结论；数据集模块函数、调用迁移及内部简化已归并为一个业务类别提交。推送随本轮完整类别统一执行，纯排版仍独立处理。

**3B：按权限、成员、配额、通用入口依次处理，每片单独闭合。**

入口：`app/services/rbac_service.py`、`tenant_group_service.py`、`tenant_member_provisioning_service.py`、`tenant_quota.py`、`tenant_quota_service.py`、`app/core/config.py`、`app/core/request_state.py`、`app/core/exceptions.py`，以及 `app/api/v1/rbac.py`、`scim.py` 的实际调用链。

- [x] 先核对 RBAC 的角色归一化、权限集合和租户成员契约；已完成的租户组服务仅检查相邻接口，不重复重写。
- [x] 再核对成员供应与配额的所有者、重复映射和失败政策；保留配额 fail-closed、限流资源及同步／异步边界。6 个调整文件通过 Ruff、AST 与调用签名核对；请求状态载体按框架契约保留并登记已符合。
- [x] SCIM 使用明确的 Settings／ORM 类型；成员 PATCH 的校验、增删、审计与提交顺序直接呈现，组详情响应由 GET 和 PATCH 复用。13 个路由声明、42 处错误构造和查询条件静态核对一致，99 处可确定调用匹配签名；协议输入验证、鉴权和既有 best-effort 政策保留。
- [x] 配置去除 14 项运行时注入及 8 个私有取值包装；57 个校验函数有明确类型。完整 Settings 类、53 个规范化校验函数、4 个迁移函数、439 项导入与 313 处调用静态核对通过，热加载保留结构化指纹的字符串表示。
- [x] 通用 API 内部保持已验证 UUID，删除无调用或注册的五个校验包装；7 个中间件及完整应用装配经规范化 AST 核对，43 处启动配置动态读取退出。15 个保留模块 Ruff、格式与语法通过；请求头、上传限制、认证响应、限流与启动顺序保留。
- [x] 本轮已触及的业务异常捕获方和响应对应关系核对后，保留既有 HTTPException 转换；共用异常只清理确定的内部类型重复处理。不能证实兼容的迁移不混入风格整理。
- [x] 身份与令牌的 10 个模块完成审核；签发、校验和初始管理员直接使用已声明类型，组同步清理重复 ORM 适配和不可达空分支。35 个参数契约、31 处错误／加解密构造与 69 处调用静态核对通过；保留外部 claim 校验、签名轮换、HTTPS、缓存及事务策略。
- [x] 数据库、HTTP 池、Redis 客户端与租约、异步桥、可选导入、代理环境及路径 9 个模块完成审核；明确类型与配置读取，删除无引用的兼容方法、锁和根路径包装。49 个参数契约、2 段租约 Lua 和完整规范化模块静态核对通过，资源、重试和取消策略保留。
- [x] 健康检查与观测 10 个模块完成审核；就绪缓存、日志上下文与 ASGI 回调有明确类型，费用与脱敏去掉内部重复转换。57 个参数契约、三个路由、完整响应 schema 与规范化模块 AST 核对通过；真实探针兼容、PII fail-closed、计数与事件顺序保留。
- [x] 其余核心工具 12 个模块完成审核；移除 14 个无引用包装及一个私有别名，合并连接器密钥遍历，补齐引擎与编码器类型。49 个保留参数契约、141 项 SQL 字面量与完整规范化模块 AST 核对通过；运行迁移、正则边界、加密轮换与离线 token 策略保留。
- [x] 数据集分类的服务、路由、schema 与模型 4 个模块完成审核；静态类迁为模块函数，UUID 校验留在 schema，树节点直接使用已声明字段。13 个参数契约、8 处调用及完整规范化 AST 核对通过；权限、租户、环检测、排序与事务顺序保留，数据集主路由仅完成相邻引用迁移。
- [x] 元信息与依赖诊断完成审核；三处构建 SHA／时间读取合并为一个标准库模块，五份原函数体与其 AST 原样匹配。诊断只清理已确认的内部转换和未使用函数，完整探针和快照规范化 AST 核对通过；provenance 仅迁移共享读取，领域语义审核留在文档链。
- [x] 审计查询、清理与权限快照完成审核；八个 schema 原样移到所属模块，七项筛选及三条删除路径各复用现有所有者。单列 UUID 查询改为直接解包 Row，修复原 tuple-only 适配遗漏候选的缺陷；38 个参数契约、七个路由和 123 处调用静态核对通过。事务与 best-effort 政策保留，实际数据库清理本次未运行。
- [x] 租户隔离、组输入与授权指标五个模块完成审核；三个 after 校验器直接消费声明类型，200 项边界仍在 Field。十段 RLS SQL 插值、转义、模型约束及有限指标标签保留；完整规范化 AST、16 项 schema 字段和七个函数参数契约核对通过。
- [x] 设置入口及所属 schema 完成审核；26 个模型、188 项字段和默认工厂保持契约，删除声明字段的缺省取值和重复标量转换。84 个参数契约、四个路由、六项原范围及 239 处调用静态核对通过；环境锁、写入、审计、权限、资源刷新及非零默认策略保留。
- [x] 共享策略完成审核；删除无调用的通用 CRUD，编辑角色检查归回 RBAC；导航直接消费已验证的列表，聊天 token 配额声明六字段，路径安全原样符合。109 个参数契约、12 个路由、320 处可确定调用与完整规范化 AST 核对通过；分块预设只迁移调用，领域审核仍待继续。
- [x] SAML 元数据、交换、桥接与重放三个服务完成审核；Session／User 与组 claim 类型明确，锁内清理后直接判断存在性，已确认的重复转换退出。29 个参数契约、40 处 HTTP 错误、七个安全核心函数及 52 处调用静态核对通过；原 XML 校验、原子消费、TTL、401／409／503 与 Redis fail-closed 保留。
- [ ] 按覆盖清单继续核对其余基础服务与通用路由；已完成的 1,139 处 Settings 读取只作为结构迁移记录。schema 和各领域路由随所属业务链审核，不能仅按目录批次编号提前关单。

**本批产出：** 用户、成员、权限和配额各有明确所有者；调用方式统一，错误与事务归属可追踪。

Chat runtime 独立类别分支已合并：`ChatRequest`、`ChatRAGConfig`、`RagConfigTemplate` 和 SQLAlchemy `Session` 作为内部类型契约；数据集 metadata loader 的字典返回契约直接使用。Redis 序列化校验、best-effort、singleflight、租约、事务、超时与取消策略保留。5 个生产文件完成调用方静态复核；Python tests 未运行。

Chat turn execution/persistence slice 已合并：`ChatStreamPersistInput` 归入流持久化 owner，turn/stream callers 使用显式输入类型；9 个生产文件经独立审查与复审。发现并修复 UUID 类型导入及 Ruff import-order 错误，最终 Ruff check/format、AST 与 diff checks 通过；事务、会话范围和流事件顺序保留。Python tests 未运行。

Chat memory runtime slice 已合并：long-term、summary 与 structured-memory flows 使用声明的 tenant/conversation inputs；flags、retrieval order、limits、transaction and best-effort boundaries 经独立审查，冗余 no-op guards 与 dynamic reads 按真实类型清理。Ruff/AST/caller checks 通过；Python tests 与 storage/runtime services 未运行。

Dataset profile slice 已合并：scan runner 和 profile service 使用声明的 ORM/schema fields；profile utils 对 serialized metadata 的 coercion 继续保留在边界。tenant/read ACL scope、scan inputs/order、cache/diagnostics、transaction 和 failure marking 经独立审查；Ruff/AST/caller checks passed，Python tests 与 storage/parser services 未运行。

Dataset precheck slice 已合并：typed scan-run/dataset fields 替代了 ORM 边界 dynamic access；serialized JSON/artifact, tenant-root path, optional scanner, failure/status, cancellation, lock/session, cleanup and best-effort policies保持。classification/diff/near-duplicate/risk helpers audited conform; Ruff/AST/caller/error-path review passed，Python tests与外部服务未运行。

### Task 4：文档处理链（进行中）

入口：`app/api/v1/documents.py`、`document_batch_upload.py`、`document_batches.py`；权限涉及 `app/services/document_access.py`、`document_access_service.py`、`document_permission_service.py`；处理涉及 `app/services/ingestion_run_service.py`、`connector_run_executor.py`、`app/parsing/processors/support/process_document_flow.py`、`app/tasks/jobs.py`、`app/tasks/worker.py`、`app/storage/object/`。

- [ ] 先从上传、权限与入库追踪请求模型、ID、元数据及参数映射；确认三个访问模块的职责，只有同一业务规则确有重复才合并。
- [ ] 再追踪入库、连接器运行、解析、存储和后台任务；去掉路由装配器反向依赖及整个 `Any` 模块传递，共享请求类型归入所属 schema。
- [ ] 按真实契约清理重复转换、空值过滤和吞异常；存储客户端与解析器的资源类保留，重试、任务取消、幂等和回滚顺序逐项核对。
- [ ] 每条完整处理链验证静态契约、记录未运行的外部依赖检查、更新覆盖并提交；不把“转成更多小文件”当产出。

入库运行记录服务及 ORM 已完成审核：五个静态入口改为模块函数，四个生产调用文件直接使用实际所有者，两个整模块参数退出；JSON 边界、原锁顺序、事务与 best-effort／required 政策保留。九个相关模块通过 Ruff、格式及完整规范化 AST 核对，302 个参数契约、九个路由与 577 处确定调用静态匹配。调用文件只完成精确迁移，其余业务仍待审核。

文档元数据与批量操作完成本片审核：运行时元数据模块更名后统一承接用户 patch，单文档与批量路由退出装配器反向依赖；状态判断归入现有生命周期服务。同步管线修改不再被错误 await，异步 retry 保持 await。15 个文件完整规范化 AST、311 个参数契约、17 个路由、86 处 HTTP 错误与 1,124 处确定调用核对通过；现有 231 条断言保持原样，Python 测试未运行。六个调用模块只迁移了明确依赖，其余处理链仍待继续。

文档读取视图完成本片审核：列表／统计共用现有数据集范围谓词，列表／统计／目录共用生命周期筛选；详情、目录树、重复文档与 MinerU 状态消费者直接使用明确契约。11 个模块规范化 AST、59 个参数契约、七个路由及 725 处确定调用核对通过；原 91 条断言未变，Python 测试未运行。处理、队列与上传主链仍待继续。

当前已完成预设与 ACL 首片：四个预设模型、五个持久化操作及六个权限函数有明确所有者；批量过滤、单文档检查与授权写入保持各自职责。58 个参数契约、六个路由与 156 处可确定调用静态核对通过，四个 ORM 模型保持原样。上传、批处理、连接器其余代码及入库任务仍待继续。

状态、取消、重试与删除完成本片审核：处理 API 直接调用 ACL、生命周期、管线身份、解析器、对象存储、索引通道和队列所有者；单文件上传、批量上传与 URL 入库共用 `app/api/utils/document_dispatch.py`，原有同步处理、BackgroundTasks、线程并发限制和对象存储临时文件清理均保留。原双份队列调度只保留一个实现。队列返回差异按 arq 合约保留。12 个完整模块、309 个参数契约、7 个路由、64 个 HTTP 错误构造及 1,285 处已绑定调用通过静态核对；378 条既有断言及测试用例未变，Python 测试未运行。该类别的 Python 源码已通过 Ruff 与格式检查；上传、解析、连接器和任务的其余处理链继续待审。

禁用、启用、归档和取消归档共用一个逐项处理函数；成员检查、文档写权限、审计与单次批量提交仍按原顺序执行。批量删除直接调用已有文档生命周期服务，并保持每个 ID 的未找到、拒绝和其他错误分类。

请求中的 `PipelineOptionOverrides` 与验证／合并函数归到 `app/api/utils/pipeline_options.py`；手工入库、文件上传、文件预览和分块预览直接调用同一所有者。字段覆盖顺序、schema 校验、缺省 `PipelineOptions` 和 400 错误的生产脱敏方式保持原样。调用模块的其余业务职责继续待审。

tenant-scoped 可写数据集选择规则归入 `dataset_service.resolve_writable_dataset`，文档、手工入库、上传与连接器入口直接调用。指定 ID 仍先执行同租户查询与写权限检查；没有 ID 时仍按创建时间升序选择第一个可写数据集，全部拒绝后仅允许编辑角色创建 `ONLY_ME` 默认数据集。路由与连接器装配模块不再转发该规则。

preview 图片引用归一化、文件定位与读取、owner sidecar／legacy 归属判断、MinIO 上传和文档内容替换统一归到现有 `document_preview_utils`。15 个 helper 的调用次序及 403／422 映射保持原样；`documents.py` 保留旧 helper 名称的直接导出，手工入库直接依赖图片 utility、生命周期、管线及身份服务。

下载、preview 和 image-url 的请求 tenant/account 解析归入 `document_assets` 路由模块，ACL 直接导入 `document_access_service`；这三个 endpoint 不再解析 `documents` 路由模块。保留 header／JWT 差异、匿名 header 图片访问显式开关、tenant 冲突拒绝、路径租户限制、Range／ETag／304 和对象存储错误映射。

URL 入库的 `UrlUploadRequest` 归入现有文档 schema；上传和连接器直接导入请求类型，`documents.py` 只保留同名直接导出兼容既有 Python 引用。请求字段与默认值按原 class AST 核对，连接器其他尚待迁移的动态 helper 继续纳入后续文件审核。

队列服务集中维护 connector ID 到执行函数的唯一映射，HTTP connector run 路由复用该 resolver。执行期延迟导入保留，因为当前 connector 聚合器负责给分拆模块绑定共享 helper；该初始化契约纳入后续连接器边界审核。

上传提交异常后的存在性核对直接使用 `Session.get` 和 ORM model；核实 SQLAlchemy session 契约后移除路由模块模型读取及 query 形状 fallback。session 创建／查询失败的 unknown 状态、远端对象保留和关闭顺序保持原样。

文件名与来源路径规则归入现有 `app/api/utils/upload.py`；`documents.py` 保留已引用名称的直接导出，上传及预览入口直接调用 utility。原路径折叠、FakePath、Windows drive、长度限制、文件名清理错误和测试 patch 行为保持不变。

`pipeline_options` utility 同时拥有 multipart pipeline JSON 解析与 chunk overlap 校验；上传直接依赖 ingestion policy、governance、parser、chunker、pipeline config 和 identity owners。既有表单大小限制、schema 错误、默认策略及 override 顺序保持原样。

Batch precheck helpers 直接依赖 staging file APIs、scan model/session 和已有扫描／策略服务；pending commit、threaded scan、失败标记、best-effort suggestion 及 staging cleanup 顺序保持原样，日志继续使用原 category。

去重查询和 bounded metadata fallback 归入 `document_dedup_service`；文件上传与 URL 入库复用同一实现，`documents.py` 保留兼容导出。tenant/dataset/archived 条件、updated/created 排序、JSONB fast path、5,000 行上限、查询异常后的 scan fallback 与持久化冲突处理顺序保持不变。

批量入库独立类别分支已合并：批量文档构造、结果快照、完成处理和重复查询明确接收 `DBDocument`，直接读取 ORM 必需字段；nullable owner 的任务映射保持现状。删除无调用包装及重复导入。其他文档处理、上传、解析和任务链仍按后续类别继续审核；Python tests 未运行。

文件上传的 single/batch document 构造和 batch finalization 直接依赖 `DBDocument` model；仅为创建该 ORM row 的 documents module 参数退出，字段值与租户查询条件保持一致。

批量上传的 saved/live worker 直接使用已有 `SessionLocal` 所有者；两个 helper 不再接收未使用的 `documents_module: Any`，批量路由也不再为创建会话导入 documents 聚合模块。路由声明与每个 worker 的独立会话生命周期保持不变。

失败 duplicate 直接调用 `document_processing.retry_document_processing`；处理中 duplicate 的 409 文案归入 `document_dedup_service`，documents 仅兼容重导出。commit acknowledgement 不确定时直接使用 `SessionLocal`。重试输入、错误文案与对象清理时序保持原样；URL 入库仍需独立移除路由聚合依赖。

URL 上传与 connector HTML 入库共享的来源准备、配额、去重、持久化和任务调度流程归入 `app/api/v1/document_source_ingestion.py`；`document_upload` 和 connectors 直接导入，`documents.py` 只保留旧入口的直接兼容导出。`LocalHtmlIngestRequest` 归入文档 schema；dedup identity、约束识别和冲突异常统一由 `document_dedup_service` 持有。49 个流程定义按 AST 保持原实现；SSRF、功能开关、租户权限、配额、错误映射、事务与资源清理顺序不变。

分块预览直接导入 parsing subprocess runner 和解析位置标记；预览参数归一化与 chunker 参数过滤由 `document_chunk_preview` 自身拥有。移除跨整个 `documents` 模块的 Any 传递，日志 category、解析取消、缓存锁、治理处理和响应策略保持原样。

原文预览直接调用 parsing subprocess runner 与治理 processor；错误转换 helper 在 `document_preview` 本地使用相同 `api.documents` logger。移除向 parse、governance 和错误转换 helper 传递 `documents_module`，保留 400／499／500 映射、生产错误脱敏、disconnect 检查和 finally 临时目录清理顺序。

Chunk-write routes 直接依赖 ORM、`Indexer`、ACL、审计和 index-audit owners。chunk-specific 查询、状态策略、index result 和 drift persistence helper 归 `document_chunks_write`；`documents.py` 只保留既有直接兼容导出。manual edits 的 chunk metadata patch 就地呈现；路由事务、权限检查、vector/BM25 best-effort、drift markers 和 response mapping 保持原序。

`connector_run_job` reads the non-null ORM `ConnectorRun.connector_id` as a string directly and retains its existing whitespace normalization and unsupported-ID failure path; no arbitrary-object coercion or empty-string fallback is needed.

**本批产出：** 上传到任务的输入输出和失败路径一致，同一字段映射与权限规则只有一个业务维护点。

Task 4 document-dispatch slice is merged. `jobs.py` now passes the declared processor inputs directly and leaves session ownership with the worker. `process_document_flow.py` annotates all 31 processor references through a `TYPE_CHECKING` forward reference to avoid a runtime cycle. Independent review and explicit six-file Ruff/format/AST/caller checks passed; upload, parser and worker modules not touched by this diff remain pending.

Document identity/ACL provenance/lifecycle slice 已合并：`DBDocument` and non-null ORM fields are read directly; tenant/ACL, tombstone, commit/rollback and metadata-only best-effort boundaries remain. `document_identity.py` retains validation at serialized-metadata/external-hash boundaries. Independent review and scoped Ruff/AST/caller scans passed; Python tests and DB/object-store/queue services 未运行。

Task 4 parser model-cache/manifest slice is merged. Model cache snapshots now consume the documented path-like result directly; manifest fields retain their declared types and normalization. The loader remains the owner of resolving the manifest and the CLI serializes its resolved `manifest.path`, preserving the prior absolute result for relative inputs. Ruff/format, four-file AST, caller scan and scoped review passed; model downloads and parser runtime were not run.

Parser structure helper slice removes only redundant coercion after local string/sequence contracts are established. Noise exemptions/regexes, region metadata/order, header/footer bands and reading-order metadata remain unchanged; four-file Ruff/AST/caller checks and independent review passed. OCR/parser runtime was not run.

OCR enrichment slice removes repeated conversions after local parser/dataclass contracts while retaining provider/image/filesystem validation, caps, redaction, formula/seal thresholds, metadata and best-effort policies. Four-file Ruff/AST/caller checks and review passed; OCR/model runtime was not run.

Parser backend sub-slice reviewed four files: aliases remain owned by `backends.py`; the parser factory retains its class because it owns cached parser instances and lazy optional-plugin construction; `errors.py` keeps dynamic metadata at the subprocess boundary. `diagnostics.py` now consumes its own sampling helper's guaranteed `is_scanned` field directly. Ruff/format, AST and caller scan passed; parser providers were not run.

Parser table structure/rendering slice retains cell/row order, span/coordinate validation, Markdown/OCR normalization, CSV/HTML escaping and renderer failure behavior while removing contract-redundant normalization. Four-file Ruff/AST/caller checks and independent review passed; parser/OCR runtime was not run.

### Task 5：RAG 与模型调用（进行中）

入口：`app/api/v1/rag.py`、`app/rag/engine.py`、`app/rag/engine_support/`、`app/rag/retrieval/orchestration/`、`app/rag/embedding/`、`app/rag/reranker/`、`app/rag/llm/`，以及实际索引所有者 `app/services/indexer.py`、`app/services/indexing/`、`app/services/dataset_embedding_config.py` 和 `app/storage/vector/`；同批覆盖其实际检索、索引、KG、评估与工具调用模块。

已开始核对索引写入切片：`vector_writer.py` 统一持有 Milvus 模式判断、shadow writer 配置／缓存、运行时异常和可选双写；`indexer.py` 与 `chunks.py` 直接调用该所有者。当前仅完成此切片的静态核对，三份文件的整体语义审核仍在清单中待办。

Reranker shim 明确识别 registry 中的 disabled aliases，并仅在 provider module 缺失时退回 identity；未知 provider 和其他初始化错误保留为显式失败。Hybrid ranking 已在调用 factory 前跳过关闭的 provider。

`planner.py` 将 dataset route helper 的内部 string-key dict 改为 frozen dataclass；route order、dedupe 与 primary/expansion scope mapping 经 caller review，公开 plan 形状不变。

KG chunk-injection wrapper 直接返回 `KGEngine.search` 的声明结果，不把契约错误转换为空结果；query-expansion owner 的 `KGResponseContractError` 校验保持在原边界。

共享 numeric coercion 收敛到 `common.py` 的 `_safe_int`／`_safe_float`；调用处显式提供原有 default 和 clamp。JSON 型字段的 `Document.id` 使用声明类型直接读取。

Citation parse-quality summaries 读取 typed `Document` 字段，并只把标准数值转换错误作为可跳过的 optional metadata。

Query variant budget stage now consumes typed int/float fields; omitted values retain the zero/unbounded contract, while malformed values no longer silently become zero.

Query contract snapshot normalization treats the optional template version as absent only for standard integer conversion errors; the typed normalization inputs and callers were reviewed.

Query planner input mapping now uses shared private values while keeping KG expansion ahead of model override parsing in both sync and async paths. An independent review caught the earlier ordering regression; the fix preserves explicit parse failures and KG diagnostic order, then passed scoped re-review. Python tests were not run.

Query model expansion deduplication now declares `set[str]` after existing provider output validation; normalization, truncation, first-seen order and stage sequence remain unchanged. Ruff check/format and independent review passed; tests and model runtime were not run.

`QueryPlan.queries` now names each internal `(kind, query)` pair as `QueryVariant` while returning the same stage-owned list by reference. No ordering, routing, scope, diagnostics, or output behavior changed; Ruff/AST/caller review passed.

Hybrid candidate fusion reuses the shared stable `result_key` owner and metadata-anchor ordering owner. The `candidate_ranking` caller preserves protected-record merge, pre/post ordering, dedup, reranker mapping, diversity, score promotion, threshold, budget prefix and diagnostics; the diff changes only `dedup.py` and `post_process.py`. Ruff check/format and independent review passed; Python tests and live channel/reranker behavior were not verified.

Hybrid channel result processing consumes its declared list inputs directly and increments locally initialized integer annotation/promotion counters directly. The external/provider item shape check remains. The reviewed branch changed only `channel_results.py`; Ruff/format, AST, callers, and static review passed, while live vector/lexical/sparse services remain unverified.

Lexical/sparse retrieval reuses `candidate_metadata_from_doc` for the shared projection; sparse calls the owner directly instead of depending on the hybrid mixin MRO. BM25/sparse score fields, cache/scope/filter/ordering behavior are unchanged. `text_preparation.py` and `lexical_search.py` were reviewed and already conform; changed files passed Ruff/format and review. Python tests and index/provider runtimes were not run.

Context expansion removes only the score-neighbor forwarding wrapper and calls `neighbor_expand` directly from the rerank workflow with the same inputs and ordering. Hierarchy's wrapper remains because it adds public diagnostics fields; the other expansion owners were reviewed and conform. Python tests and retrieval services were not run.

Rerank cache has one canonical owner: the orchestrator imports `app.rag.rerank_result_cache` directly, while the prior orchestration path re-exports the same public symbols. Corpus-token invalidation therefore targets the populated cache. Cache keys, TTL, provider/fallback semantics, and error policy remain unchanged; Ruff/import checks and independent review passed.

Retrieval intent/KG/out-of-scope policy slice keeps the orchestrator stage order and provider/scope boundaries. KG boost rows are constructed locally with `is_kg: bool` and bounded `kg_score: float`, so eligibility reads those fields directly; score, order, thresholds and diagnostics stay unchanged. Ruff/format and independent review passed; services/tests were not run.

Hierarchy orchestration retains its optional refill guard and now iterates the declared list directly. Primary/refill order, duplicate handling, ancestor-wins behavior, survivor order, metadata and diagnostics are unchanged; Ruff/AST/caller checks and independent review passed. Runtime graph/database services and Python tests were not run.

Retrieval trace finalization now increments its locally initialized integer counters directly; debug sanitization remains defensive at the raw debug/PII boundary. Trace schema, ordering, and error diagnostics remain unchanged; Ruff/AST/caller scan and independent review passed.

- [ ] 按查询准备 → 通道召回 → 融合／重排 → 上下文 → 模型／流式返回的顺序追踪数据和预算，再处理各条依赖链。
- [ ] 合并经证实重复的参数映射与控制流，核对动态取值和无依据默认值；保留供应商协议适配、可选插件边界和有状态资源。
- [ ] 核对排名、阈值、缓存键、配置指纹、超时、取消、预算和流事件；不为缩短函数改变策略或事件顺序。
- [ ] 用已有固定样例和配置资料作静态契约参照；Python 测试及模型／解析依赖验证本次不启动。已有 CI 结果有则记录，不能把样例源码核对写成检索结果回归通过。
- [ ] 每条调用链检查、审阅、覆盖登记和提交后，再进入下一条。

**本批产出：** 检索主流程顺序可读，模型、索引和检索职责清楚；运行效果的未验证范围如实列出。

### Task 6：全量前端

入口先为 `web/lib/api/core.ts`、`web/lib/api-client.ts`、`web/lib/api/`、`web/types/`；再按数据集／文档与入库、检索对话、权限设置、评估治理与观测覆盖 `web/app/`、`web/components/`、`web/hooks/` 及剩余自研前端文件。

- [ ] 先核对 API 客户端、错误转换、请求／响应类型和 legacy 导出使用者；只有不存在真实兼容对象才删除旧入口，生成的 `web/types/openapi.ts` 保持生成来源。
- [ ] 再按领域统一 `export function`、`type`、组件内聚和数据所有者；Hook 负责状态／副作用，纯计算直接派生，只有编辑草稿才维护独立副本。
- [ ] 核对加载、刷新、空数据、筛选无结果、失败与处理中状态；确认旧请求晚到、重复提交、失败保留及保存后读回。状态表达遵循现有业务，不统一制造一套状态管理框架。
- [ ] 页面、共享组件和所有使用方同批调整；`web/app/[locale]/` 中框架入口转导出按其路由职责保留，不只为形式改写。
- [ ] 按 `oil-frontend` 和 `oil-ui-pro` 检查受影响真实页面与必要状态，复用现有浏览器会话；设计方向继续沿用，仅补受影响的判断。纯格式化单独提交，语义批次运行相关前端检查。

**本批产出：** 各领域页面采用一致的组织与声明方式；共享实现有明确职责，真实交互和数据归属可核对。

设置 API 与共享类型首片已合并：保留 `settingsApi` 的四个方法、`settingsApiLegacy` 兼容导出、endpoint 与错误传播；手工响应形状明确为共享类型。该 worktree 缺少 `web/node_modules`，ESLint、Prettier、TypeScript 和前端 tests 未运行，因此格式状态仍为 pending。

Shared API core slice 已合并：request/response interceptors 仅提取为具名内部 handlers，注册顺序和行为保持；auth、OIDC refresh/retry、cancellation、request ID、rate-limit、HTML response 和错误传播经独立审阅。Barrel re-export surface 未改；工具链因 `web/node_modules` 缺失及 pnpm 版本不符未运行。

Chat API type import now points directly to `web/types/chat.ts`; the nine exported contracts, HTTP requests, response validation, SSE handling, and API barrel are unchanged. ESLint/Prettier/TypeScript/runtime checks remain unavailable due the missing web dependency tree.

Shared common type slice 将 `PermissionEnum` 指向 generated `OpenApiSchema<'DatasetPermissionEnum'>`；literal union 完全一致，`DocumentAccessMode` 的 `inherit` 与通用 `LooseString`/`JsonObject` aliases 不变。Caller/barrel scan and review passed; frontend type/lint/format checks remain unavailable.

Auth/access API 首片已合并：`auth.ts` 与 `access.ts` 的 duplicate request/response shapes 改为直接使用 OpenAPI owners，`tenant-permissions.ts` reuse generated `TenantAccessOut`; SAML/bootstrap token, member/group paths and role payloads retain their existing wire contracts. No UI change; frontend lint/type/runtime checks remain unverified because the required web dependency tree is unavailable.

Feedback DTOs have a dedicated `web/types/feedback.ts` owner; the chat type module re-exports the old names so both `@/types/chat` and `@/types` remain compatible. Fields, optional/null modifiers, union members, API payloads, feedback UI state and labels remain unchanged. Frontend tools remain unavailable.

Governance, industry-rules, LTR registry, and observability settings sections now import types from their direct owners. This slice changed only type imports; JSX, props, state, callbacks, form submission and visible behavior remain unchanged. Frontend tooling is unavailable.

Document API slice 已合并：`documents.ts` 与 `document-helpers.ts` 保持 endpoint、FormData、relative filename、parser selection、timeout/abort、Zod/OpenAPI validation 和 error propagation contracts。工具检查因 web dependency constraints 未运行。

System API slice 已合并：health response uses its backend type owner, usage token/cost share the identical generated query shape, and metadata aliases remain. Endpoint/validation/error behavior is unchanged; TypeScript/ESLint/Prettier and tests remain unverified because frontend dependencies are unavailable.

`web/components/settings/settings-switch.tsx` already follows the named component and type ownership rules and delegates state to the shared Switch; callsites were scanned, no code change was needed. The Dify/object-storage/parser settings sections now import generated settings/parser types from their owners; the model-provider section conforms unchanged. No JSX/state change was made. Prettier status remains pending with the unavailable web dependencies.

The settings `feature-flags`, `frontend-preferences`, and `system-status` sections were audited as conforming named components with local props types and direct settings/API owners. No UI or state behavior changed; formatting remains pending because Prettier is unavailable.

### Task 7：脚本与全仓收尾

范围：`scripts/`、`ci/`、`docker/` 下自研运行代码、入口及覆盖表中剩余文件；Python 测试仅按本轮暂缓约定登记，前端测试继续按职责维护。

模型引导 CLI 首片已完成：`bootstrap_parsing_small_models.py` 合并重复结果字段构造，维持各状态的字段集合、顺序和 canonical manifest path；`bootstrap_mimirq_models.py` 审阅后符合标准。Ruff/AST 检查通过；CLI、下载和转换未运行。

Diagnostics/smoke CLI 首片完成：`compose_diagnostics.py` 将重复 compose `ps` 命令及 JSONL parsing 收敛到一个 helper，同时保留两次 subprocess 调用、参数、错误记录、报告字段和主函数 exit code；`api_ping.py`、`api_smoke.py`、`check_parsers.py` 审阅后符合标准。Ruff/AST 与独立审查通过；CLI/runtime 未运行。

- [ ] 核对脚本参数、退出码、输出、路径、配置和资源释放；命令行有意输出及必要兼容注明理由，不套用业务服务的错误转换。
- [ ] 将覆盖表与最终 Git 跟踪列表重新对齐；新增、删除、移动都有去向，逐一检查 pending，不能因格式通过或改过一个引用就关单。
- [ ] 核对残留旧符号、重复业务实现、转发模块、动态注册及过期豁免；有真实用途的保留并记录依据。
- [ ] 完成下面的全量验收及提交审阅；报告本次新增问题、原有失败和未运行验证。只有本轮授权范围全部有结论，才声明该范围完成。

## 7. 验证、提交与完成标准

**Python 每批：** Ruff check、Ruff format --check；通过 `ast.parse` 读取本批源码核对语法，不导入业务模块、不运行测试。涉及签名与依赖时核对全部引用和 patch；结构迁移可比较归一化 AST，逻辑简化必须另外审阅数据、异常与事务。静态检查不能证明运行时等价。

全量 Ruff 使用 `git ls-files` 的 Python 清单并遵循 `ruff.toml` 排除项，Windows 下分块传参，避免扫描原有未跟踪残留或超过命令长度：

```powershell
$stylePythonFiles = @(git ls-files -- "*.py")
for ($styleOffset = 0; $styleOffset -lt $stylePythonFiles.Count; $styleOffset += 50) {
    $styleChunk = @($stylePythonFiles | Select-Object -Skip $styleOffset -First 50)
    & ./.venv/Scripts/python.exe -m ruff check -- @styleChunk
    if ($LASTEXITCODE -ne 0) { throw "Ruff check failed" }
    & ./.venv/Scripts/python.exe -m ruff format --check -- @styleChunk
    if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed" }
}
```

每批把同样的检查限制为本批明确的文件清单。新增自研文件在纳入提交后进入全量清单。未跟踪残留引起的其他检查失败单列归属，不移动或删除它们来制造通过。

**前端每批：** 涉及文件的 ESLint／Prettier、`pnpm -C web run typecheck`、现有相关 Vitest 和 UI／API 检查；修改交互时从真实入口核对实际结果。证据充分后停止重复验证。

**前端全量收尾：** 沿原用户批准计划运行以下已有命令，生产构建和全量用例留到收尾，不要求每次局部修改重跑：

```powershell
pnpm -C web run lint
pnpm -C web run format:check
pnpm -C web run typecheck
pnpm -C web run test
pnpm -C web run ui-check
pnpm -C web run api-check
pnpm -C web run build
```

**记录与提交：** 继续使用 `docs/maintenance/style-unification/coverage.csv` 和 `verification.md`。每批说明解决的阅读／维护问题、改动范围、真实检查结果和未验证项；只对实质性职责决策补短记录。纯排版与逻辑整理分开提交，不新增常驻评分脚本或整套管理工具。若检查因本批修改失败，先修复或只回退本批具体改动，再推进。

**完成条件：** 全部跟踪文件都有本轮处理结论；暂缓测试、第三方、生成物等明确标明理由。所有新增检查失败已解决，旧失败与环境限制有归属。注册登录、权限拒绝、数据集、上传和检索对话分别标明源码核对、实际运行或未验证，不能用历史结果替代当前版本证据。
