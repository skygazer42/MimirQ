# 内部值直接传递验证

最新验证日期：2026-11-08。本次范围核查及修正已完成；最终相关验证覆盖 195 个测试文件，**1831 passed、2 skipped、86 deselected**。保留 87 个此前记录的基线排除名称，其中 86 项在本次选择中收集到；未新增排除。下文保留各批边界与历史验证结果。

日期：2026-11-07。工作树：`C:/Users/jiahuanl/.codex/worktrees/style-task3-chat-tags/MimirQ`。

本轮依据用户最新澄清，修正此前“将 `or None` 改成条件表达式”的理解。当前规则见[决策记录](../../.agents/notes/implemented/simplification/2026-11-07-direct-value-contracts.md)。原始扫描数量不作为剩余改动量，也不要求删除真实可空接口、解析失败和未找到资源的返回值。

## 变化

- 候选、语义和重排缓存直接使用已有的 scope/token/behavior 字段；必需 query、top-k、score threshold、检索模式不再被空值补齐。
- 重排结果缓存直接读出 writer 保存的 provider/model 字段，保留空字符串和显式 `None`，缺失必需键会报错。
- 文档执行身份与 provenance 直接使用已有的解析器、分块策略和版本字段；空值差异进入 provenance 哈希。去重与内容 SHA 的原有边界保留。
- URL 来源、文档 owner 和检索诊断直接传递已获得的字段。profile 在运行状态中保留上游的可空结果，不做往返空值转换。

## 验证过程

新增的缓存契约测试在修改前得到 16 个预期失败、2 个已有通过；文档身份与 provenance 测试在修改前得到 13 个预期失败、1 个已有通过。用例验证真实的缓存键隔离、缓存往返、缺失字段报错、去重状态清理与 provenance 哈希区分，不按源码语法计数。

独立复核发现一项 P2：预算路径入口仍先将缺省 profile 变成空字符串。修复从 query routing、既有编排入口和预算策略解析器保留可空值，并调整选择器的类型契约；没有在输出端恢复归空。5 项回归在修复前为 3 个预期失败、2 个已有通过，修复后全部通过，覆盖策略匹配、未匹配和实际 query routing。三组新回归合计 **37 项通过**。

18 个 Python 源码/测试文件通过 AST 解析、Ruff check、Ruff format --check 和限定文件的 git diff --check。独立复核使用冻结的前后快照，未将工作树的其他改动计入本轮；问题修复由上述失败转通过的测试验证。

## 既有失败边界

相关回归沿用[上一批选择记录](explicit-null-documents-test-selection.json)的 113 个测试文件和 76 个既有排除名，加入本轮三个测试文件。首次扩大验证遇到的以下 **13 个失败均在本轮修改前源码的内存覆盖运行中复现**，异常种类与修改后相同。没有为这些旧夹具恢复已迁移的导出或放宽必需契约。

- `test_hybrid_search_releases_distributed_lease_after_candidate_cache_write`
- `test_hybrid_search_publishes_distributed_result_before_semantic_cache_write`
- `test_hybrid_search_singleflight_only_uses_behavior_hash_in_cache_key`
- `test_hybrid_search_uses_distributed_singleflight_when_exact_cache_disabled`
- `test_hybrid_search_keeps_local_followers_when_distributed_singleflight_errors`
- `test_query_debug_includes_singleflight_cache_role_metadata`
- `test_retry_document_processing_fails_closed_when_queue_handoff_fails`
- `test_retry_document_processing_hash_ignores_parser_backend_resolved_drift`
- `test_retry_document_processing_local_fallback_preserves_then_consumes_retry_cleanup`
- `test_transition_document_index_channel_tracks_attempts_and_timestamps`
- `test_transition_document_index_channel_keeps_disabled_optional_channels_out_of_error`
- `test_transition_document_index_channel_savepoint_failure_does_not_block_next_update`
- `test_orchestrator_preserves_query_contract_defaults_and_hash_contract`

其中后四个测试名加入本轮排除表，其余已在历史记录中。排除表共有 80 个名称，当前实际选中并排除 79 个测试项；用收集后的测试名精确匹配，不用无法解析参数标点的 pytest `-k` 表达式。

本轮证据保存在 `E:/tmp/ragvia-direct-values-correction-20261107`：`before/` 是修改前字节，`after/` 是独立复核快照，`final-source/` 是复核修正后源码，`baseline-reproduction.log` 记录 13 项修改前失败，`review-fix-red.log` / `review-fix-green.log` 记录复核问题的失败转通过，`test-selection.json` 和 `run-selected.py` 保存实际相关回归选择。运行使用 `E:/MimirQ/.venv/Scripts/python.exe`，`PYTHONPATH` 包含工作树和已有 Milvus 测试 SDK 路径；未安装依赖或请求外部服务。

最终运行 116 个相关测试文件，结果为 **1168 passed、2 skipped、79 deselected**，耗时 95.53 秒。两项跳过分别是未启用的索引通道集成测试和需要 fork 语义的平台测试；65 条 warning 为已有弃用提示。上述选择不是全库测试通过声明，也不代表真实 Milvus/Redis 服务的集成验证。

修正后的 15 个生产所有者和 3 个新增测试文件均以字节哈希冻结，测试结束后核对未变化。独立复核原始快照与修复后的快照分开保留，不用活动工作树的其他差异替换本轮证据。

## 后续核查进度

上述结果是首批修正的历史记录，未证明全库目标完成。后续核查继续按同一规则处理实际值投影、请求清空语义和必需契约，目标保持进行中。

当前继续批次累计修改 75 个生产所有者（包含离线 benchmark 和 CLI 脚本）。文档/训练导出、群组与请求参数、时间线/健康信息、预热和 profile/index-drift 诊断移除重复归空；真实可空 UUID 的响应字符串转换、ETag 长度上限、脱敏和已有服务校验保留。另删除 9 个与原值完全等价的 `x if x is not None else None` 表达式。

新覆盖包括：聊天缓存空 scope 的隔离、SQL 诊断输出原值并保留计划一致性校验、表格来源元数据往返、trace 中 `False`/`0` 的保留、响应模型拒绝错误存储类型、空列表/字典在请求 patch 中保留、群组空名称触发既有业务错误和空外部 ID 实际清空。群组更新以真实 SQLite Session 验证，不增加生产兜底。群组服务对 `0` / `False` 外部 ID 在写库前报错，真实缺省和空文本清空仍保留。

trace 对未知的 scope 字段继续保持未知，对已脱敏的存在性布尔值直接保留；二次规范化不会凭空生成 `False` 或抹掉已有 `True`。SQL 期望 fingerprint 的空覆盖也不能屏蔽 planner 中的有效期望值，这项完整性约束以修正前失败、修正后通过的独立用例验证。

扩大到索引审计接口时的 5 项失败已在本批修改前的 `observability.py` 快照中复现，均为旧 `_DummyDB` 缺少 `commit()`；没有恢复可选提交、吞错或默认成功逻辑。14 个支持的 profile 定义也在本地纯计算验证中成功生成。

继续批次证据位于 `E:/tmp/ragvia-direct-values-correction-20261107/continuation`：`plan.md` / `progress.md` 保留完整目标与待办，`owned-python-null-wrappers.json` 是候选记录，`task1-candidate-decisions.json` 记录已核查的真实边界，`before/` 与 `task1-tested-source/` 保存前后字节，`task1.diff` 为本批差异，`task1-test-selection.json` 记录相关测试与基线排除。候选数量不是剩余缺陷数量，未核查项不视为已完成。

后续连接器响应与通道输出修正增加 14 项行为测试，验证原值、必需映射/状态失败和敏感字段脱敏；14 项包含了数据库 connector 标识带空白时仍执行连接信息脱敏的回归。管线持久化修正增加 11 项测试：6 类合法空覆盖真实往返、缺省继承、primitive 安全过滤和 3 类完全非法覆盖不取消安全继承。

会话摘要接口继续补充 5 项测试，使用真实 SQLite 证明保存的空文本、原始文本和租户隔离，证明真实无记录仍返回 `None`、读取失败向上暴露及权限拒绝先于读取；修改前 3 项预期失败、2 项已有通过。最近消息读取器同样直接返回保存文本，自动标题的既有派生规则保持。

继续批次最新相关验证选择 139 个测试文件，得到 **1377 passed、2 skipped、84 deselected**，耗时 70.34 秒，65 条已有弃用提示。代码通过 AST、Ruff check、Ruff format --check 和限定文件 diff 检查。该结果覆盖当前实际改动；并不证明全库目标已经完成。此前管线修正后的 135 文件结果为 1348 passed，作为阶段证据保留。

首批 27 个生产所有者的继续改动经过一次独立静态复核，未发现可操作新增缺陷；之后对 SQL 完整性、连接器脱敏、管线空覆盖的补充以先失败再通过的定向用例验证。完整目标结束前仍需复核后续所有新增差异。`task2-candidate-decisions.json` 与 `task3-candidate-decisions.json` 记录后续处置；`parser-boundary-decisions.json` 为 12 个实际可空解析结果提供生产者、消费者证据，未将同文件其他函数自动判为完成。

## 2026-11-08 继续验证

索引审计、入库身份/actor、词法与 KG 范围适配、Confluence/Jira 来源、标准 stream 诊断、异常 detail 和预算诊断的组合改动，使用冻结的 26 个生产文件及 4 个测试文件完成独立只读复核，30 项哈希一致，未发现可操作新增缺陷。原 reviewer 两次在启动前返回 503 后，替代模型完成同一份审查；没有把失败调用当作审查通过。审查不代表 reviewer 独立重跑过测试，也不覆盖全库剩余候选。

新增回归分别证明：不完整 marker 不持久化、非法处理人不改变记录状态、空错误不选旧 metadata、来源 ID 长度上限及非法类型无副作用、词法 SQL 继续限制 tenant/发布状态、profile/A-B 字段不掩盖错误类型、显式异常空字典可见、零预算诊断与执行规则一致。KG 引擎的 deny-all 空列表适配有实际消费者依据，保留原域语义。

诊断后续修正保留 benchmark 的实际缺失资产列表、证据漂移观察值、KG confidence 和在线评估 mode。在线评估采样率为零的真实队列测试先失败，修复后不再产生评估任务；保留正采样率和有界队列原有行为。该诊断批 11 项回归先得到 7 项预期失败、4 项已有通过，修复后相关定向 44 项通过。

当前树另有并行的生命周期输入校验、处理流程类型访问和两个等价语法整理，均保留并保存独立差异。生命周期旧测试停在已迁移的 route mock 符号处；仅把测试连接到实际服务并使用 ORM 对象，权限拒绝、审计脱敏、空值清除、禁止自引用及 QA 委托断言全部保留。相关当前测试 73 passed、1 个已知旧 checkpoint 夹具排除。

最终相关验证为 **1501 passed、2 skipped、86 deselected**，153 个测试文件，耗时 156.92 秒，65 条已有弃用提示。87 个既有失败名称精确匹配后，实际排除 86 个测试项；新增两个失败均以修改前源码复现，未恢复废弃导出或放松必需字段。旧 checkpoint 夹具失败曾进入清理分支并尝试连接不可用的本机 Milvus，后续复现使用测试离线 guard，生产代码未加入静默降级。

本阶段未提交、安装依赖、启动服务或部署。当前代码及并行差异的版本边界以 `nov8-source-hashes.json`、`nov8-regression.log`、`concurrent-nov8/` 和各批冻结快照为准。剩余 API/SDK/CLI 范围适配及其他候选仍待合同核查；未将未检查项标为完成，也不报告“所有 or None 已删除”。

## SDK、提示词和解析输出继续验证

Milvus 空凭据直接交给 SDK；CLI 请求头和配置 builder 不再重复归空/默认。实体别名搜索原先会把空类型转换成字符串 `"None"` 并添加错误类型筛选，现在使用实际类型，仓储层租户条件保留。4 项边界测试先得到 2 项预期失败、2 项已有通过，相关 SDK/CLI/评测/别名测试 51 项通过。其余 KG 空列表到 `None` 的范围适配有接收方 deny-all 语义依据，继续保留。

选中的 prompt 内容、版本及 A/B 元数据直接输出；未选中仍可空，错误的必需内容直接报错。显式 KG 空参数字典在序列化中保留，嵌套参数仍拒绝。继承的 ValidationError/LLMError 也保留实际空 detail、field 和 provider，非法 scalar detail 不被补为空字典。

独立复核冻结的 21 个源码/测试文件，哈希全部匹配，发现 1 项 P2：关闭实体别名规范化时，描述缺少进入索引前的公共处理，与 embedding 使用的文本不一致。修复位于实体公共准备入口，保留 nullable/empty 差异，不恢复下游兜底。8 项分支、类型和输入不变性测试先得到 4 项预期失败、4 项已有通过；修复后相关 33 项通过。选中 KG 模板的旧提前归空 guard 也由 2 项先失败的用例纠正。

解析输出新增 4 项先失败的用例，证明空 ID、文本、属性和源 hint 不被归空；旧 preview 夹具替换为真实 LangChain Document，已有 ownership/图片处理断言保留。标准化元素的旧精确形状用例只将两项期望属性从 `None` 改为实际空字典。vendor/DeepDoc 的 Docling 测试因缺少 `trio` 无法收集，未安装依赖；本轮实际修改的 app/parsing Docling wrapper 由新增用例及既有 wrapper 测试验证。

缓存 token 新增 4 项用例，保留真实缺少身份时的拒绝，证明 datetime/ISO 等价，并区分实际空版本和缺失值。解析/corpus 相关定向测试 43 passed，1 项既有 manual-route mock 失败按已记录的基线排除。

修复复核问题后重新冻结并运行 166 个相关测试文件，结果 **1592 passed、2 skipped、86 deselected**，耗时 247.56 秒，65 条已有弃用提示。前一次运行在旧 extractor 模块已导入后才收集到新增模板测试，出现 2 failed、1582 passed；该混合版本结果保留为过程证据，未用于最终通过声明。最终结果和版本哈希以 `task13-final-regression.log`、`task10-13-accepted-source/`、当前总 manifest 为准。

并行的 sibling header helper、KG canonical-name/关系引用处理整理单独保存差异并保留；不归为本轮实现。公共实体描述处理、选中模板行为与索引投影经 AST 核查保留。所有剩余候选仍按实际生产者/接收方判断，解析无匹配、SSE 无 token/结束符以及隐私白名单无可接受字段等真实可空结果有独立审计记录，不能由词法扫描批量删掉。

## 范围、解析来源与工厂合同闭合

最新继续修正把已有值沿 API、运行状态、任务参数、日志和缓存传递。空模板名称、显式空字段和零权重不再重选旧值；插件文本及必需记录身份的错误类型、缺键会报错。Typed after validator 先验证字符串，再执行已声明的空白清除或继承规则，`0`、`False` 和容器不再被改成未提供。

聊天和检索从范围所有者返回真实 `None` 表示未选文档；KG 内部的明确空集合继续为 deny-all。KG 请求构造、传输、同步及流式注入、计数和 evidence capsule 的接收方同步适配。KG 搜索和 community 缓存使用 v3 签名，区分未选与空范围，避免新键读取旧 v2 的模糊范围结果；空文档范围优先于数据集 fanout。真实 ACL 函数本身已对全拒绝选择抛出 403，本次撤销了基于不可能 mock 返回值添加的重复检查。

冻结 KG 抽取任务以自身的版本选择为准，真实无版本不会在 enqueue 或 worker 中重新选文档旧版本；对应任务只抽取无版本 chunks。工厂的默认选择只在真实省略参数时执行，显式空 API 模型、凭据、URL 及零 timeout/MMR 权重不被改成另一套配置；未知 provider 和 fusion strategy 不再静默执行别的算法。合成数据 `max_attempts=0` 不调用生成器，非法预算类型在开始工作前失败。RAGAS 剩余本地 HuggingFace embedding 分支也已退出，退休配置在分配客户端之前被拒绝。

解析的实际后端来自 worker、已验证缓存或可复用 checkpoint。实际后端可以与请求和 lookup backend 不同，不能按不相等判坏，也不能用请求值猜实际来源。远端缓存 schema 和本地缓存键均升级为 v2，旧的猜测来源不复用；缺来源的旧 checkpoint 按既有可选复用策略进入新解析。Local cache decoder 同时验证策略来源，拒绝 `None`、空文本和非文本，保留合法 `auto` 与 integrated chunks-only 结果。OTel 不用实际值反推请求值，metadata recorder 不再 seed 未记录的请求事实。

索引检查现在从 `index_audit_service` 到真实 `MilvusVectorStore.fetch_existing_ids` 都区分失败与成功无匹配：SDK 查询异常原样传播，坏响应和缺失主键报错；真正空查询结果仍为空集合。真实 SDK 的 `col=None` 表示已知 collection 不存在，保留这一空结果；缺少 `col` 或 `query` 能力会报错。完整方法测试使用独立对象，避免修改 class singleton 污染后续用例。

原始 249 项归空来源已逐项关联当前合同：239 项改为所有者或投影直接传值，9 项保留真实解析/隐私/缺省边界，1 项在 typed after validator 修正后保留合法空白 no-override。原始默认值清单中仍匹配的 62 项也完成复核；真实可空容器、未匹配、清除和选择器优先级有单独依据。V1 replay citation fingerprint 与脱敏后的空 canonical 信息属于既有格式合同，不迁移为新的签名协议。词法剩余数不代表缺陷数。

独立复核报告 `current-scope-review-verified.json`、`parser-provenance-review-verified.json`、`original-defaults-review-verified.json` 均无未解决项。复核发现的 tuple/len/slice 对 `None` 的遗漏、缓存策略缺事实仍命中、SDK 深层异常转空集合，以及新增测试的 singleton 污染，均有完整生产函数或真实文件往返的回归覆盖。Golden 问题格式化保留数值零与布尔假值；对应旧源码快照得到 2 项预期失败，本地缓存旧源码得到 4 项预期失败、2 项控制通过。

最终组合为 **1831 passed、2 skipped、86 deselected**，pytest 用时 350.62 秒，65 条已有弃用提示。两项跳过分别为禁用的集成测试和 Windows 不支持的 fork 场景。最后静态范围共 214 个源码/测试文件，通过 AST、Ruff check、Ruff format --check；限定文件 `git diff --check` 和三项 agent note 门禁通过。组合执行期间源码哈希无漂移；真实数据库、Milvus、Redis 和模型服务未做集成运行。

首次扩大选择的 5 项失败保留在 `task31-aggregate-regression.log`：其中两项来自误加入的无关完整 session 测试文件，纠正为实际修改的两个 nodeid；两份重排测试改用其真实 UUID 输入合同，另一项负例允许版本选择器在模型构造前暴露类型错误。没有恢复任何生产兜底，也没有新增基线排除。并发的 hardcase 末尾归空清理保留为单独差异并纳入最终验证。

最终证据目录为 `E:/tmp/ragvia-direct-values-correction-20261107/continuation`：测试选择 `task33-test-selection.json`、执行结果 `task33-aggregate-regression.log` / `task33-aggregate-result.json`、冻结字节 `task33-tested-source/` / `task33-tested-hashes.json`、归空来源 `original-or-none-closure.json`、各批修前快照及三份独立复核报告。旧缓存会在后续使用时重新生成；权威文档、索引及用户数据未执行迁移。

组合之后的版本核验发现并发 Dify helper 去重，四个鉴权函数的 AST 与已测试版本相同，追加相关鉴权和会话幂等测试 **8 passed**。该验证同时纠正了本轮对外部来源 ID 规范化的过度删除：幂等键入口只对已提供字符串执行 `strip()`，真实 `None`、空字符串和错误类型不会被另一套 ID 或 `None` 代替。对应源码及共享 auth 模块另外冻结，不把它们冒充组合执行时的版本。

额外扩大到 Dify 两个完整测试文件得到 49 failed、202 passed；以本轮修改前的三个模块快照隔离重跑，得到完全相同的 49 个失败节点和 202 passed。失败涉及原有测试 response 缺少必需 metrics，以及另一组既有检索/提示规则预期；记录在 `post-test-dify-baseline-equivalence.json`，没有加入本轮 87 个排除名称，也没有声称 Dify 全套通过。相关 8 项及 1831 项组合的验证范围分别保留。

后续并发整理还把 preview 和治理中的 frontmatter tag parser 合并到其既有 frontmatter 模块；移动后的函数与已测试治理实现仅名称不同。当前三个文件另经 **50 passed** 的治理、值投影及空覆盖测试验证，测试期间无漂移，证据为 `post-test-frontmatter.log` / `post-test-frontmatter-result.json`。最终 manifest 逐项区分组合快照和这两组补充验证后的源码。
