# Phase 0 / Phase 1A 进度

状态：暂停源码施工，等待总指挥协调并发写入；未修改源码、测试或暂存区，未提交。

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
