# 后端去过度防御进度（Phase 0 / 1A / 1B）

原始证据已迁出仓库：`C:/Users/jiahuanl/Documents/Codex/2026-11-08/opencode-omo-slim-orch-opus5-5/outputs/mimirq-evidence/`。本文历史 JSON/TXT 文件名均相对于该目录的 `legacy/`；后续批次各用独立子目录。迁移逐文件校验 SHA-256，不改写历史。仓库仅保留本台账、定性表、延期/后续清单与 `red-green-summary.md`。

状态：Phase 1A 列举位置及审查修正完成；Phase 1B 限定切片的 181 处修改已验证，其余 1339 候选按范围裁决列入后续清单。历史暂停记录保留，不宣称全库清零。

## 并发裁决

- 初始 HEAD：d04e10ab93fd96ea2a9d0dd6a8fcf3bde2366776。
- 调查中发现新 HEAD：255fb9cc7（refactor: preserve connector-owned values）。按交接「发现有新提交/文件被并发改动就停下来」停止。
- 不代提交既有 WIP：归属不明且存在活跃写入者。没有执行整体 stage 或清理。
- 本快照 tracked status 条目：482；untracked status 条目：66（按默认 porcelain 目录折叠计数，并非实际文件数）。
- baseline-status.txt / baseline-diffstat.txt / baseline-counts.json 保存停止时快照；它们不是最初 HEAD 的完整基线。

## 基线计数口径

使用 rg -o，app 下 *.py；每个匹配单独计数。三参 getattr 为单行词法近似，不能用作缺陷总数。各目录同样记录全部六项模式。

## 环境与未执行验证

- python -m ruff check app、python -m ruff format --check app 和 pytest 尚未成功启动：当前 PATH 找不到 python、python3、py、uv，工作区 .venv/Scripts/python.exe 不存在。
- 初次尝试的 Python 基线脚本没有执行，未产生文件；本记录与快照由 PowerShell 保存。
- C:/Users/jiahuanl/AppData/Local/Programs/Python 的目录检查被权限拒绝，未请求升级或安装依赖。
- 未启动解析器、模型服务或容器。
- FastCtx 工具未暴露，使用本地文件命令。工作区 rg 未发现 AGENTS.md；已读 C:/Users/jiahuanl/.codex/AGENTS.md、完整计划和三篇指定 note。

## 已核实调用链（仅调查，未修复）

- datasets.py create_dataset 的主写入由 dataset_service.create_dataset 执行，路由 1163 的 commit 位于明确注释 Best-effort audit log (commit separately; never block response) 后；依总指挥补充规则应按文档化审计旁路定性，保留时需提高日志可观测性，不能直接声称是未提交主数据。
- datasets.py update_dataset 的 1562 同样在服务调用后的审计写入；需进一步核实 update 服务提交契约。
- document_versions.py 472/588：审计提交后 rollback 但未重抛；570：删除 KG 关系和索引后 commit 失败被回滚吞掉。后者涉及真实清理持久化，不应返回成功；尚未写回归测试。
- document_qa_service.py _update_document_chunk_stats 763：chunk_count/total_characters 更新提交失败后 rollback 并正常返回，是服务层回归测试候选。
- document_ingestion.py _attach_document_to_ingestion_run 1121：document 关联元数据提交失败后继续 add_document；需确认 ingestion run 旁路契约与外层失败处理。
- document_metadata_operations.py _commit_audit_event 已有 warning+exc_info 和 rollback；属于审计旁路候选，按补充规则逐处核实，不机械删除。

## 下一步

总指挥协调并发写入窗口并指定可用 Python 解释器后，重新建立稳定 HEAD 基线，运行现有相关 pytest，先编写并证明 commit 抛错回归失败，再实施首批主写入修复。当前 Phase 0 未完成，Phase 1A 尚未开始；无修复前后测试证据、无提交 SHA。

## 续作裁决（2026-11-08）

- 已确认仅主代理运行，HEAD 为 `255fb9cc7`，并发暂停条件解除；`py` 指向 Python 3.14，可执行源码语法检查。
- Ruling: 用户明确要求不处理 Python 测试，因此本轮不新增或运行 pytest；以完整调用链、暂存源码编译、差异检查和 Note 门禁作为证据。代价是数据库异常路径没有运行时回归证明，交付说明必须保留该缺口。
- Phase 1A 先修 `document_versions.delete_document_version`：KG/事件数据库清理失败必须向上抛出；向量、BM25 与审计旁路保留可观测降级，不新增重试、兼容分支或默认成功。
- Phase 1A complete: commit `d1f607a39`。暂存版本通过 Python 3.14 源码编译、限定差异/空白检查及 131 篇 Note tree/format/archive 门禁；静态核对两个派生索引 warning、两个审计 helper 调用及 KG rollback 后 re-raise。按裁决未运行 Python 测试，未执行数据库、索引或 API 运行时。
- Phase 1B ruling: `document_qa_service._persist_qa_chunks` 已在统计刷新前提交 QA chunks；`chunk_count/total_characters` 是可重算投影。统计 commit 失败继续 rollback 并返回生成结果，但必须发出带堆栈和修复建议的结构化 warning。代价是响应成功时统计可能暂时陈旧，运维需按日志重算。
- Phase 1B complete: commit `33c3879eb`。暂存 blob 通过 UTF-8/Python 3.14 编译，结构化 warning 五字段、限定差异/空白和 131 篇 Note 门禁通过；原 `_split_prefixed_field` 工作树改动未进入提交。按裁决未运行 Python 测试或数据库/QA 运行时。
- Phase 1C ruling: ingestion run 创建和 attachment 是文档主入库后的可选追踪；失败不得伪装为主入库失败，但必须先 rollback 恢复 Session，并由 `_attach_document_to_ingestion_run` 单一 owner 记录降级。删除三个调用方重复 suppress。代价是 run manifest 可缺记录，运维需按 warning 对账。
- Phase 1C complete: commit `bea542575`。暂存 blob 通过 UTF-8/Python 3.14 编译，逐段核对两处 create rollback/warning、attachment 两段 rollback/warning 与三个调用迁移；限定差异/空白及 131 篇 Note 门禁通过。一次零上下文暂存预览发现错位并在提交前清空重建，最终索引源码已编译；其他 direct-value 工作树 hunks 未提交。未运行 Python 测试或入库运行时。
- Phase 1D ruling: batch item 由独立 Session 形成结果，主请求 Session 的 ingestion run manifest 是旁路。run 创建、metadata、attachment、close_intake 失败都必须 rollback + warning，但不得改写已形成的批量成功/失败列表。代价是 manifest 可能不完整，需按日志对账。
- External HEAD: Phase 1D 施工中发现用户提交 `4c1cb4531 Update files`，仅改 `document_batch_ingestion.py` 两处 `file_sha256=(file_sha256)`。该提交保留为当前基线；与 run-tracking 事务/日志 hunks 不重叠，不回退、不改写归属。
- Phase 1D complete: commit `2a67d0ba6`（基于外部 `4c1cb4531`）。暂存 blob 通过 UTF-8/Python 3.14 编译；静态核对 run create、metadata、attachment、close_intake 四处 rollback/warning，限定差异/空白及 131 篇 Note 门禁通过。未运行 Python 测试或 batch/数据库运行时。

## 恢复后的基线与目标文件冲突

经总指挥授权，仅借用 E:/MimirQ/.venv/Scripts/python.exe；所有命令 cwd 为本 worktree，未读取或复制 E 盘源码。

新 HEAD d1f607a39 (fix: surface document version cleanup failures) 直接修改本切片 app/api/v1/document_versions.py（86 行差异），并且文件仍有 WIP。依更新后的并发规则停止源码施工；未写源码或测试、未暂存或提交。该文件当前 hash-object 为 7374e8f12e4051901527820e7b516b87ade81586。connector_execution 全部延后，有活跃写入者。

以下是存在并发写入者时的时点快照，不代表固定 HEAD 的干净基线。

- `E:/MimirQ/.venv/Scripts/python.exe -m ruff check app`：exit 1，8 个 I001；条目 app\services\connector_execution\confluence.py:1:1, app\services\connector_execution\db_catalog.py:1:1, app\services\connector_execution\drive_files.py:1:1, app\services\connector_execution\github_repo.py:1:1, app\services\connector_execution\jira.py:1:1, app\services\connector_execution\minio_bucket.py:1:1, app\services\connector_execution\url_batch.py:1:1, app\services\connector_execution\web_crawl.py:1:1。完整输出 ruff-check-baseline.txt。
- `E:/MimirQ/.venv/Scripts/python.exe -m ruff format --check app`：exit 0，1216 files already formatted。
- `E:/MimirQ/.venv/Scripts/python.exe -m pytest -q tests/test_document_versions_integration.py tests/test_dataset_ingestion_policy_endpoints.py tests/test_dataset_service_atomic_acl.py tests/test_document_lifecycle_metadata_endpoints.py`：11 passed，2 skipped，74.42s，无失败；document_versions_integration.py:69/:195 因集成开关关闭跳过；一个 pytest cache 写权限警告。未启用外部集成服务。
- 已重新用 Python subprocess 传递精确 rg 正则重建 baseline-counts.json；替代先前 PowerShell 参数传递的计数。app 汇总：{"except": 2227, "suppress": 255, "or_collection": 3058, "getattr_3": 900, "isinstance": 3970, "settings_or": 1518}。三参 getattr 仍为单行词法近似。

待总指挥协调 document_versions 文件归属后继续；尚无本轮回归测试红绿证据或修复提交。

## 第一提交：table API 审计边界（已实现，待提交）

总指挥放宽规则：冲突只跳过对应文件，其他继续。document_versions.py、services/document_*（含 document_qa_service.py）、connector_execution/ 由并发会话处理（d1f607a39/33c3879eb），本计划不重复。已完整阅读 document-mutation-contracts note，本批同样保留文档化审计旁路。

### 定性与修改

- app/services/audit_log_service.py:4 明确声明 Best-effort, fail-open: logging must never break product flows；本批三个 helper 仅调用该服务并提交审计记录，不提交请求主业务数据。
- app/api/v1/db_catalog.py 原 :80，_audit_fls_redaction：文档化审计旁路，保留 fail-open，commit 失败 rollback、warning+exc_info；write 失败同样 warning+exc_info。
- app/api/v1/dataset_tables.py 原 :185，_audit_table_query：同上。
- app/api/v1/dataset_tables.py 原 :221，_audit_fls_redaction：另有本地 Best-effort, fail-open 注释；同上。
- 全部宽捕获加边界原因 noqa。没有新增捕获、默认值、重试或静默降级；rollback 自身失败向上传播。没有强行把这三个审计点改为主业务 P0。

### 红绿证据与命令

- 新增 tests/test_table_audit_commit_failures.py::test_audit_commit_failure_rolls_back_and_warns，参数 catalog_redaction/table_query/table_redaction。调用真实 API helper 与真实 audit_log_event，仅 Session 在 commit 注入 RuntimeError。
- 修复前：3 failed，均 assert db.rolled_back 为 False（table-audit-red.txt）。
- 修复后：上述三例及原先三份现有单测共 14 passed，15.03s（table-audit-green.txt）。
- 局部 ruff check 通过，ruff format --check 通过（3 files already formatted）。
- 命令均使用授权的 E:/MimirQ/.venv/Scripts/python.exe，cwd 本 worktree，pytest 使用 -p no:cacheprovider 避免既有 cache 权限警告。

### 并发与 hunk 归属

- 修改前 db_catalog hash 5d1d6b967bf9ba4eab4f010988ec355222254b71，修改后 ff7aae89b13143fe5be3cf8fed438c1ab4f12062。
- 修改前 dataset_tables hash 12733e2ad7303fc6c6b52e57d0222e880cf23d72，修改后 9639d0ee92802f61ab78b7ba8e5cf72c080daaa2。
- 修改前分别查看每文件 git log -3；没有最近两小时同类修复占用。原有 dataset_tables WIP 在 4c1cb4531 Update files 中由并发方提交，本代理未代提交。该提交不包含本轮审计 hunk；提交前源码 diff 仅本轮 17 insertions / 11 deletions。
- 原始文件快照仅用于核对，不纳入提交。未操作他人暂存内容。

### 剩余范围

datasets.py 指定 7 处、dataset_precheck.py 2 处、ingestion_runs.py 4 处、rag.py usage_count、KG routes.py/extraction.py 尚待下一组逐处回归。已初读 ingestion_runs 四处均为审计（export/compare 有本地 best-effort 注释）；extraction.py :184 同样为审计，datasets :1957 为 purge 审计。尚未声称完成 Phase 1A 全部主写入调查或完成路由 5xx 回归；本批经契约核实是合法旁路清理。

补充验证：catalog 鉴权 + 本轮回归 11 passed，9.78s（catalog-green.txt）。提交前 HEAD 2a67d0ba6；4c1cb4531 之后仅 document_batch_ingestion 并发提交，不碰本批。提交标题按真实审计降级语义使用 expose audit commit failures，而非声称所有 commit 均重抛。

第一组已提交：a1a8db2c6 fix(table-api): expose audit commit failures；7 files changed, 182 insertions(+), 11 deletions(-)，其中源码 2 文件、测试 1 文件、台账与证据 4 文件。提交后 datasets.py 出现他人 WIP，本代理未修改或暂存它，后续先检查归属。Phase 1A 仍为部分完成。

Phase 1E complete: commit `9b8eb9127`（基于并行 `a1a8db2c6`）。`datasets.py` 新增单一 `_commit_dataset_audit` owner，迁移 create/update/config import/retrieval audit/clone/purge/documents export/bundle export 八处旁路；统一 event+commit、失败 rollback 和 warning，主业务结果不改写。暂存 blob 通过 Python 3.14 编译、限定差异/空白及 132 篇 Note 门禁；未运行 Python 测试或数据库/API/导出运行时。并行 table-api 路径无重叠。

## 独占恢复检查未通过
总指挥要求起步 HEAD 为 9b8eb9127 或本会话提交；实际起步 HEAD 为 11d964252 fix: expose KG document cleanup degradation。新增非本会话提交包含 6eeb24312 ingestion-run 审计、283882cf5 precheck 状态、fbf93015c RAG usage、efee8832b KG extraction audit、11d964252 KG cleanup。按本轮明确停止条件暂停，未修改源码或测试、未运行回退 patch、未暂存或提交。当前仅 progress.md 有未提交修改。需要总指挥确认 Desktop 实际停止，并认可新的验收起点后继续。

## 独占起点 11d964252：Desktop 八组验收

八组提交的当前函数已审查：datasets 8 个调用点、ingestion_runs 4 个调用点与 document_versions/extraction/deletion 审计遵循 audit_log_service.py:4 fail-open 契约，回滚并记录 traceback；RAG usage 是选中配置后的可选计数，QA stats 是已提交 chunks 的投影，允许可观测降级。版本 KG 数据库清理失败 rollback 后重抛。precheck 补偿提交失败有 warning+exc_info，但后台入口仍需单独补主异常观察与事务恢复。KG 文档关系删除已有本地 Best-effort 注释，后续事件删除由 Indexer 持有主事务。未将计数、审计误报为权威主写入。

新增 tests/test_commit_boundary_acceptance.py，9 个运行时用例覆盖八组提交（含文档审计与真实删除路由 500）。临时 patch 仅恢复旧的静默分支和版本 cleanup 的吞错分支；同一套测试 9 failed，9.34s（desktop-acceptance-red.txt），finally 按原字节恢复全部 8 文件并核对 hash 相等。未提交回退。当前版本初次 9 passed，5.96s；恢复后与现有测试组合结果见 desktop-restored-green.txt。

Ruff 审查发现 Desktop 的 routes.py 遗留 F401 contextlib，删除该导入；其余十个文件 check 和全部十一文件 format 通过。routes.py 修改前 hash 19fd6c18c03a28fbd1bbc5a74116add178f9e15d，修改后见本次 hash 命令。此提交不调整其事务语义。所有验证仍仅借用指定解释器，未启动外部服务。

## 第二提交：剩余 API 审计与后台补偿

上一提交 773f70281（6 files, +392/-1）；routes.py 修改后 hash 3fc6d5644fef2c2a397066ae214422acdec6335e；恢复后的组合测试 34 passed / 2 integration skips。

本组 audit.py 原 427/517/797/1031、evidence.py 原 243、evaluations.py 原 1912 均为已完成操作后的独立审计；主删除服务使用 commit=True，失败不会到达审计分支。沿 audit_log_service.py:4 保留 fail-open，删除嵌套 rollback 吞错，增加 warning+exc_info。

datasets.py 原 226（现 _mark_dataset_profile_scan_run_failed）是 enqueue 失败后的补偿；调用者仍 raise 503，不当成功。补偿失败保留 rollback，debug 改带堆栈 warning。原 1957/3000/3101 已由 9b8eb9127 的 _commit_dataset_audit 覆盖，非剩余主写入。

datasets.py 原 2416 与 precheck 原 244 是后台顶层失败状态补偿：先记录原异常、rollback 恢复事务，再更新 failed 行；补偿失败独立 rollback/warning。precheck 原 179 已由 Desktop 处理且有 acceptance 测试。

新增 test_api_commit_failure_boundaries.py：修复前 11 failed（均缺少目标异常观察/事务恢复），修复后与 Desktop/scan queue 现有测试 42 passed，9.35s；6 文件 Ruff check/format 均通过。新增分支为零，仅修正已有 catch 的责任；原始异常在补偿失败前已经日志记录。每文件 log -3 与 hash 记录在 api-hashes-before/after.json。新决定 note 记录审计与补偿边界，引用既有两篇 owner note。

## 第三提交：服务 / 解析重试 / 抽取旁路

第二提交 7d8de5bcf（12 files, +685/-28）。本组 Confluence 原 819 为必要 connector identity/来源 metadata，失败 rollback 后重抛，不能把 page 导入报成功。Ragas 原 317 只写进度投影，不是最终评估结果，保留降级但 direct rollback+warning traceback。extractor 原 1208 是已选 prompt 的旁路计数、3942 仅已生成事件的文档统计投影，保留降级，加 exc_info 并删除 rollback 吞错。recovery 原 259 已有显式 deferred 返回和 marker 恢复，非成功伪造；保留并增加 traceback。

batch precheck 原 800 附近：precheck_only 是必需扫描，commit 失败 rollback+raise；optional precheck_first 是已有可选扫描策略，失败 rollback、warning+exc_info，返回 None 而不是未持久化的 pending scan_run。后台 scan job 在原异常之后先 rollback 再查询/补偿；补偿失败 rollback+带堆栈 warning，仍 raise 原始 scan 异常。

新增 test_service_commit_failure_boundaries.py 8 例。最初发现 tmp_path 权限/Windows 路径长度及 prompt monkeypatch 目标问题，已修正测试装配；不把这些环境/装配错误当红证据。最终临时恢复本组 HEAD 旧源码：新用例 8 failed；另 3 个原有 retry_queue 测试同样失败，4 个通过；恢复全部源码后新测试+KG复杂度+Ragas契约 17 passed（8.20s）。三个既有失败分别为 test_retry_document_processing_fails_closed_when_queue_handoff_fails / test_retry_document_processing_hash_ignores_parser_backend_resolved_drift / test_retry_document_processing_local_fallback_preserves_then_consumes_retry_cleanup，均因 app.api.v1.document_processing 无 settings 属性；本切片不修无关别名。

服务组 ruff 仅剩 baseline confluence I001，其他无新增；格式检查由 batch 新增长行触发，已仅格式化该文件新块。hash 与每文件 log -3 记录在 service-hashes-before/after.json。Note 三门禁以 Node 24 原生 TypeScript 执行，134 notes tree/format、0 archive 全通过（宿主 ESM 类型提示无关）。

## 第四提交：worker/KG 完成边界与收尾验收

第三提交 fec9a000d（12 files, +643/-19）。最后一组 tasks/jobs.py 原 795 是有 Best-effort job-level audit summary 注释的审计，保留旁路但 direct rollback+warning traceback；原 1838 的 invalidate_dataset_cache_namespace 写 dataset.updated_at 轮转持久化 corpus token，是 KG 完成的一部分，不能把 commit 失败当成功，现在 rollback+raise，队列收到错误。已提交事件不会被这次 rollback 撤销，不虚构跨事务原子性。

KG routes 原 1618/1671/1993 及同类 1879/1940 主提交原本已重抛，不是吞主提交；删除嵌套 rollback 吞错后，rollback 失败同样传播，并通过 Python __context__ 保留原始 commit 异常。test_worker_and_kg_commit_boundaries.py 修复前 7 failed / 5 passed（5个正常rollback时的原始传播用例原本已通过），修复后该组+Desktop补充 22 passed。

Desktop KG cleanup 的关系清理和 audit 两分支补充临时旧行为证明：2 failed（kg-relations-red.txt），恢复后均通过。precheck 再加初次提交成功、后台 worker 失败的 required/optional 两例，旧源码4 failed（含原2个首次commit失败用例），修复版本通过（precheck-late-red.txt）。

最终新增回归 46 passed，17.73s（new-regressions-final.txt）。完整限定15文件组合 141 passed / 2 skipped / 5 failed，32.87s（final-pytest.txt）。2 skipped 均文档版本数据库集成开关未开启，未启动数据库、模型、解析服务或容器。5个失败全部已用旧源码复现：
- tests/test_document_processing_retry_queue_contract.py::test_retry_document_processing_fails_closed_when_queue_handoff_fails
- tests/test_document_processing_retry_queue_contract.py::test_retry_document_processing_hash_ignores_parser_backend_resolved_drift
- tests/test_document_processing_retry_queue_contract.py::test_retry_document_processing_local_fallback_preserves_then_consumes_retry_cleanup
  以上三例引用不存在的 document_processing.settings；service-red.txt 记录旧版本同失败。
- tests/test_task_locks.py::test_document_job_propagates_failed_processor_result
- tests/test_task_locks.py::test_document_job_downloads_generic_object_storage_source
  以上两例测试替身仅接受 kwargs，生产 processor 用5个位置参数调用；task-existing-failures.txt 记录旧worker同样2 failed。

全app ruff check仍为基线8个connector I001，format 1216 files already formatted；新测试和本组源码7文件check/format通过。所有任务指令使用授权解释器并在worktree cwd运行；带tmp_path的测试指定工作区短路径 --basetemp，避免系统临时目录权限和Windows长路径假失败。

已核对 owner-call-sites.json：datasets审计8处、ingestion_runs审计4处、document_versions审计2处、RAG usage两个入口各1处，无遗留旧局部usage提交。dataset_service create/update主commit已有rollback+raise，未误改成审计降级。32个函数/边界逐处表见 classification.md；本轮指定点无跳过，扩展扫描候选单列 follow-up-findings.md，不能把本轮完成解读成全库commit吞错清零。没有触碰1B settings默认值切片。

采用 requesting-code-review 技能的独立只读代理审查：没有阻碍提交的正确性问题；确认主写入传播、可选与必需precheck分流、异常链和真实函数测试。限制：MagicMock Session故障注入，不覆盖真实数据库expire/transport行为；policy suggestion失败完整外层流程未增加用例。新notes的tree/format/archive三门禁通过。

最终模式计数（包含Desktop已提交修复影响，不仅是本代理diff）：except Exception 2206、suppress 236、or{}[] 3058、三参getattr单行近似892、isinstance3970、settings.X or1518。仅作词法参考。四组提交的最终stat以git show为准；最后提交SHA在交付回报列明，本文不自引用自身尚未生成的SHA。

## 审查修正：保留 precheck 失败记录链接

总指挥审查确认 c243d0033 之前四提交整体通过，指出 optional precheck 执行失败时不能丢已提交 run。核实发现普通 precheck-first 最终 _build_batch_response 也未传 precheck_scan_run_id；现一并补上。

_run_precheck_scan 分开创建提交与可选执行边界：创建提交失败仅 optional 返回 None；提交后的 worker 失败 rollback+warning 并返回持久化 scan_run，precheck_only 仍重抛。第一次与执行后的 db.refresh(scan_run) 均在降级捕获之外；ingest_batch 的 db.refresh(dataset) 删除 suppress。数据库无法 refresh 是真实故障，向上抛出，不新加缓存/默认值。

新测试 test_precheck_scan_response_contract.py 使用真实 SQLAlchemy Session/SQLite 与最小映射，实际 worker 独立 Session 将 run 标为 failed 并 commit；after_soft_rollback 证明 request Session 中 run 已 expired，随后序列化响应仍返回该 UUID，实际 SELECT 可见 failed 状态。证明的是事务恢复与惰性载入契约，不是数据库不可用时的成功保证。另3例验证 initial scan / completed scan / dataset refresh 失败全部冒泡。

修复前4 failed（修正响应 UUID JSON 比较后又临时恢复旧源码重证）；修复后结果见 precheck-review-green.txt。旧 service 回归更新为 optional worker 失败保留已创建 run、创建提交失败返回 None，避免把原先错误断言当产品契约。源码修改前 hash 1cdd2a24b713983dcd88fdd0691dcc90f3ec19e6，修改后5c78167eafe40677044d1c7aa05851c5de004a5d；动手前git log -3无外部新提交。

审查修正验证：指定解释器 -m pytest -q -p no:cacheprovider --basetemp=.ptreviewg2 tests/test_precheck_scan_response_contract.py tests/test_service_commit_failure_boundaries.py tests/test_dataset_scan_queue_contracts.py：36 passed，4.92s；3文件 Ruff check / format通过。上一收尾提交 c243d0033（22 files, +1792/-32）。

## Phase 1B：声明默认值归属（限定切片）

前置审查修正已提交 8309eec52（7 files, +350/-22）；真实SQLAlchemy测试36 passed，恢复失败记录链接并使refresh错误冒泡。

全量定位以rg与AST交叉执行：rg单行 settings.[A-Z_]+ or 与-U getattr(settings,...)变体输出 phase1b-rg.txt；完整原始AST候选1522条见 phase1b-inventory.json（含13条getattr变体及真正逻辑OR，不能当1522个已判缺陷）。超过总指挥60阈值，按授权只做计划三处 + rag/retrieval，范围外1339候选逐行列在 phase1b-deferred.md，不改其他模块。

限定范围原有183个直接Settings OR候选：181个字面量兜底删除（retrieval167、evaluations KG snapshot13、process_document_flow PREPROCESS_SAMPLE_PAGES 1），21个源文件、99个配置字段；每一字段均对照config.py注解与默认表达式，为非Optional并有默认值。逐处映射在 phase1b-classification.md / phase1b-decisions.json。没有需新增is None分支的字段，未改config声明、.env.example、部署或默认值文档；Nullable字段和未声明getattr候选留给范围外下一片。

保留2个真正逻辑OR：ENABLE_MULTI_QUERY or forced（实验强制启用）和 RETRIEVAL_COMPACT_HIGH_CONFIDENCE_ENABLED or policy.enabled（策略合并）。另外4个紧邻的 .strip()/lower() 后文本规范化OR是生成审查记录时遇到的外层节点，并非直接Settings兜底，本片保持。请求覆盖优先级、业务min/max限制、类型转换和其他非Settings兜底不动。

新测试 test_settings_declared_defaults.py 与 test_hybrid_settings_declared_defaults.py 共11例：旧源码9 failed / 2 passed。红证据包括KGweight=0.0被改为0.25、max_promoted=0被改为3、calibration alpha=0被改0.7、multi-query cap=0被改8、PDF sample_pages=0被改3、lexical的0未走既有最小值、rerank阈值0未跳过模型。BOOL False由KG启用和multi-query/lexical开关控制用例验证，不删除真的逻辑或。

特别说明：evaluations 的 or 0 / or 0.0 原本保留合法零值，valid零值/False快照用例修复前已pass，不能伪造此处零值bug。它的红证据是给非Optional DIM注入None时不应伪造零快照；直接读取后int(None)进入原有optional snapshot失败分支，不再db.add伪造记录。此None是故障注入，不代表合法配置输入。

修改后11新例全通过（13.10s，phase1b-new-green.txt）；扩展相关pytest组合56 passed / 4既有failed（13.65s，phase1b-final-pytest.txt）。修复前组合34 passed / 13 failed，其中9为新红例、4为相同旧失败（phase1b-red-baseline.txt）。旧失败列表：
- test_retrieval_orchestrator_complexity.py::test_run_retrieval_parallel_variant_execution_preserves_public_query_order：patch已不存在的 generate_alias_queries。
- test_retrieval_hybrid_channel_results.py::test_hybrid_search_normalizes_vector_candidates_and_exact_anchor_metrics：patch不存在的 retriever.get_vector_store。
- test_retrieval_hybrid_channel_results.py::test_bm25_candidates_preserve_active_pipeline_identity：引用已退出 _candidate_metadata_from_doc。
- test_retrieval_hybrid_channel_results.py::test_invoke_preserves_debug_degradation_contract_with_bm25_fallback：patch不存在的 retriever.get_vector_store。
不顺手恢复旧别名或改无关测试。

验证命令：指定E:/MimirQ/.venv/Scripts/python.exe -m ruff check app/rag/retrieval app/api/v1/evaluations.py app/parsing/processors/support/process_document_flow.py tests/test_settings_declared_defaults.py tests/test_hybrid_settings_declared_defaults.py 通过；format --check同范围82 files already formatted。全app check仍是基线8个connector I001，format 1216 files already formatted。限定pytest命令完整文件集合见 phase1b-final-pytest.txt 的结果及工具执行记录；没有模型、解析器或容器服务启动。notes三门禁通过135 notes/0 archives。

修改前对21文件逐个git log -3及hash，见 phase1b-file-history.json / phase1b-hashes-before.json；修改后hash见phase1b-hashes-after.json。以8309eec52完整模块AST为基准，仅应用批准删除Settings字面量默认的变换，21/21文件与实际修改AST相等（phase1b-ast-proof.json），证明没有旁带语义编辑。

独立只读审查核对181条、99字段，未发现阻塞问题；限制是代表性运行测试未逐一执行181条路径，eval None仅为故障注入。最终复扫全app剩1341个候选 = 范围外1339 + retrieval保留逻辑OR2；本轮限定直接Settings字面量兜底已收尾，Phase1B全库仍未完成，不扩大到其余候选。

Phase1B所有实际复现命令已单列 phase1b-commands.txt；提交前再次核对21文件hash与验证时一致。只有本代理自有改动；新提交仍为8309eec52，没有触发外部写入停工条件。

## 后续裁决：证据精简与可选建议边界
原始证据迁移提交4c50ff154：52 files +18/-23118；51份文件共926959字节复制到外部legacy并逐份验证SHA256（含未提交policy红输出），不改写历史。
实际_apply_precheck_policy_suggestion自身已有catch，8309并未使其通常异常直接传播；本轮选择保留可选便利功能契约，HTTP非409及普通异常现在rollback+warning(exc_info)，已有策略409仍正常no-op，外层继续返回已提交scan_run并保留响应链接。真实SQLA响应测试2新例先failed/4passed，修改后相关16passed，2文件Ruffcheck/format通过。note Consequences已明确。

## 后续批次 api

候选 228；direct 175、Optional显式None 1、保留逻辑/来源链 21、安全裁决未改 31；源码 23 文件。声明与逐处裁决见 phase1b-remaining-classification.md，安全项见 phase1b-review-decisions.md。红：3 failed in 3.93s；绿：3 passed in 2.39s。原始输出/完整命令/源码前后hash/逐文件git log及AST证明位于仓库外 `C:/Users/jiahuanl/Documents/Codex/2026-11-08/opencode-omo-slim-orch-opus5-5/outputs/mimirq-evidence/api/`。Ruff check/format 与完整模块AST对照通过；不改变Settings声明或环境默认值。
