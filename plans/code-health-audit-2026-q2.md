# MimirQ 存量代码健康度审计 Plan（2026-05-19）

## Context

**为什么做**:MimirQ 已沉淀 27 份"向前看"的能力调研 plan（`plans/rag-*-2026-q2.md`、`plans/industry-rules-*.md` 等),但代码本身的健康度从未系统审计。本次基于 3 个 Explore agent 对 web/ + app/ + tests/ 的扫描数据,产出"向内看"的存量改造清单。

**核心发现**:
- **前端比 MEMORY 记录的更糟** —— `ingestion/page-client.tsx` 已涨到 **5767 行**(MEMORY 记 3720,+2047 行倒退);`quarantine/page.tsx` 涨到 **2802 行**(+687);`similarity-workbench.tsx` 涨到 **3426 行**(+682)。"大文件持续膨胀"已成趋势。
- **正确性风险**:**async 函数中调用 time.sleep**(openai/ollama embedding provider);**15+ 测试 monkeypatch 绕过 DB**(直接违反 MEMORY 中"禁止 mock 数据库"原则);`except Exception:` 滥用集中在 `retriever.py`(81 处)/`orchestrator.py`(73 处),错误被静默掩盖。
- **测试覆盖错配**:后端 pytest 3164 个测试 / 前端 vitest 2319 用例,但 E2E playwright **仅 6 个 spec**;3164 个后端测试中**仅 23 处 parametrize**,导致 test_connector_internal_helpers.py 单文件 1893 行。

**用户取舍**(已确认):
- 形状 = 单文件 P0/P1/P2 分级总览
- 范围 = 架构治理 + 正确性风险 + 测试基建(**不**单独列"拆超大文件",拆分作为架构治理的副产物)

**用户未取**:代码可读性专项(纯拆超大文件)。理由推断:工程量大、收益不直接;此类工作应该**绑定到具体架构治理任务**(如重写时顺带拆),不作独立 sprint。

---

## 三大主题 × P0/P1/P2 矩阵

### 主题 A：架构治理

#### A-P0(本周可启动)

**A-P0.1 类型双轨合并(2 day)**
- 现状:`web/types/backend.ts`(206 行手写) vs `web/types/openapi.ts`(50780 行 openapi-typescript 生成),Explore agent 实测 **152 处 export type/interface 重复定义**。`web/types/{models,processing,datasets,chat,evaluation}.ts` 5 个分散文件与 openapi.ts 覆盖范围重叠。
- 动作:
  - 在 `web/types/backend.ts` 内只留 **alias re-export** 自 `openapi.ts`(已有 `web/types/backend.ts` 模式可复用)
  - 把 `models/processing/datasets/chat/evaluation.ts` 中能从 openapi 派生的全部改为 `type X = paths["..."]["..."]["responses"]["200"]["content"]["application/json"]`
  - **保留** `web/types/common.ts`(8 行基础类型)和真正前端独占的 UI 状态类型
  - CI 加 `openapi-typescript-codegen --check` 防止 openapi.ts 与 backend OpenAPI schema 漂移
- 验证:diff 行数 ≥ 2000 行删除;`pnpm typecheck` 通过;搜索 `import.*from.*types/openapi` 数量上升

**A-P0.2 chunk-preview/context.tsx 28 个 useState 拆分(2 day)**
- 现状:`web/components/chunk-preview/context.tsx` **1675 行**,**28 个 useState**(行 272-317)+ 4 处 useEffect 集中在一个 Context。任何 useState 触发整树 re-render。
- 动作:
  - 按"语义群"拆 3-4 个独立 Context 或迁移到 Zustand store:**预览状态**(currentChunk, scrollY)/ **编辑状态**(draftBoundaries, isEditing)/ **策略状态**(strategyParams)/ **诊断状态**(metrics, errors)
  - 参考已有 `web/store/document-view.ts` 的 Zustand 模式
- 验证:React DevTools Profiler 比较渲染次数;`context.tsx` 文件 ≤ 600 行

**A-P0.3 API router 错误处理统一(1 day)**
- 现状:`app/api/v1/` 89 个 router,Explore agent 发现错误处理风格混杂:有些手写 `raise HTTPException(status_code=404, detail=...)`,有些 `raise ValueError → 500`,无统一日志/trace_id 透出。
- 动作:
  - 检查是否有 `app/api/middleware/error_handler.py`(Explore 提到该文件 async sleep 问题,说明已存在),改为**全局 exception handler middleware**(`@app.exception_handler(DomainError)`),按异常类型映射 status_code
  - 89 个 router 内的 `raise HTTPException` 全部迁移至 `raise <DomainError>`
- 验证:`grep -rn "HTTPException" app/api/v1/ | wc -l` 数量大幅下降;一个故意失败用例返回带 trace_id 的统一 envelope

#### A-P1(1-3 个月)

**A-P1.1 useEffect+useState fetch → TanStack Query(2-3 周,分 4 批)**
- 现状:**137 个文件**混用 `useEffect+useState+fetch/api.`;MEMORY 中仅 8 个用 useQuery、0 处 useMutation;`/knowledge/quarantine/page.tsx`(2802 行 / 24 处 useEffect)、`/knowledge/feedback/page.tsx`(1989 行)、ingestion/page-client.tsx(5767 行)是重灾区。
- 动作:每批 ~35 个文件,优先级 = ingestion → quarantine → feedback → 其余;迁移时**顺带**对 page-client 做 4-5 子组件拆分(关联 A-P2)
- 验证:`grep -rln "useEffect.*fetch\|useState.*fetch" web/ | wc -l` 持续下降;loading/error 状态视觉一致

**A-P1.2 UI 基础组件库统一(1 周)**
- 现状:Drawer 至少 3 个实现(`profile-editor-drawer.tsx` / `ingestion-detail-dialog.tsx` / knowledge documents panel 子组件);Modal/Dialog 命名混乱(`*-dialog.tsx` vs `*-drawer.tsx` vs `*-modal.tsx`);DataTable 多套无共用基类。
- 动作:在 `web/components/ui/` 下抽 `BaseDrawer` / `BaseDialog` / `BaseDataTable`,迁移现有 3 套实现;命名规范文档(只保留 `*-dialog.tsx`,Drawer/Modal 作为 dialog 变体 prop)
- 验证:`web/components/` 下 Drawer 实现数 = 1

**A-P1.3 状态管理分工规范文档(1 day)**
- 现状:5 个 Context + 3 个 Zustand store + 32 处 zustand/jotai import,无规则。chunk-preview Context 因此膨胀到 28 useState。
- 动作:写 `web/docs/state-management.md` 规则:server state → TanStack Query;cross-page state → Zustand;single-tree shared state → Context;component-local → useState。在 `.cursorrules` / `CLAUDE.md` 引用。
- 验证:新功能 PR review 时可引用该文档

#### A-P2(长期)

- **A-P2.1** 大文件拆分(超大 page 拆 4-5 子组件):随 A-P1.1 TanStack Query 迁移**顺带完成**,不独立 sprint
- **A-P2.2** `app/core/config.py` 1103+ 字段按域拆 `config/retrieval.py` / `config/embedding.py` / `config/parsing.py` 等子模块(pydantic-settings 已支持 nested model)
- **A-P2.3** Chunker 12+ 实现抽 `ChunkerBase` ABC(对照 `ConnectorBase` 模式 `app/connectors/base.py:11`)
- **A-P2.4** Reranker 5 个独立实现(BGEV2/LongContext/Weighted/LLM/MMR)抽公共 `RerankerBase` interface

---

### 主题 B：正确性风险

#### B-P0(本周必修,可能正在产 bug)

**B-P0.1 async 函数中的同步 sleep(0.5 day)**
- 现状(关键 bug 隐患):
  - `app/rag/embedding/providers/openai.py:171, 183, 193` 在同步分支用 `time.sleep`(可能 OK),但 262/274/282 async 分支已用 `await asyncio.sleep`(标准模式) —— 需逐行核对是否有 async 函数误用 time.sleep
  - `app/rag/embedding/providers/ollama.py` 3 处类似混淆
  - `app/rag/reranker/base.py` + `app/rag/middleware/error_handler.py` 同样情况
- 动作:
  - 写一个一次性 lint 脚本 `scripts/audit_async_sleep.py`(基于 ast 模块):扫所有 `async def`,递归找 `time.sleep` 调用
  - 修复每一处:`time.sleep(x)` → `await asyncio.sleep(x)`
- 验证:lint 脚本输出 0;`pytest tests/test_*_provider*.py -v` 不慢

**B-P0.2 测试 mock DB 改为真实 fixture(1 day)**
- 现状(直接违反 MEMORY 警示):
  - `tests/test_chat_helper_option_inputs.py` 用 `monkeypatch.setattr(db_mod, "SessionLocal", ...)` 绕过 DB
  - `tests/test_connector_url_batch_checkpoint_resume.py` 类似
  - `tests/test_dataset_ingestion_defaults.py` mock `DatasetService.get_dataset` 等 service 层
  - 全仓库 6395 处 monkeypatch,至少 15+ 处是 DB 相关
- 动作:
  - 复用 `tests/conftest.py` 中已有的 `pg_session` fixture(全局已配置)
  - 把 15+ 个 mock DB 测试改为接 pg_session(若担心慢,可用 `pytest-postgres` 或 sqlite in-memory + alembic 迁移作为单元层 fixture)
  - **重要**:不要为了图快用 `sqlite` 替代 —— MEMORY 提到上季度被"mock 通过、prod 迁移挂"坑过
- 验证:`grep -rn "monkeypatch.setattr.*SessionLocal\|MagicMock.*Session" tests/` 数量降到 < 3

**B-P0.3 `except Exception:` 静默掩盖修复(1 day,TOP 5 文件)**
- 现状(数量):
  - `app/rag/retriever.py` 81 次
  - `app/rag/retrieval/orchestrator.py` 73 次
  - `app/parsing/processors/processor.py` 49 次
  - `app/services/report_service.py` 35 次
  - `app/rag/engine.py` 28 次
- 动作:TOP 5 文件每处 `except Exception:` 至少加 `logger.exception()` 或窄化为具体异常类。**不要求**一次到位窄化全部 —— P0 仅"先吼出来",后续 P1 再分类。
- 验证:故意触发一个错误,日志中能看到完整 trace + 上下文字段

#### B-P1(1-3 个月)

**B-P1.1 类型注解补齐到 95%(1-2 周)**
- 现状:220/1061(~9%)文件完全无类型注解;不是所有 init 文件,业务模块也涉及(parsing 子模块、部分 schema 字段)
- 动作:用 `mypy --install-types` + `pyright --outputjson` 找出"零注解"业务文件,按模块分批补;优先级 = `app/rag/` > `app/parsing/` > `app/api/v1/`
- 验证:`mypy app/ --strict` 错误数下降到 X(基线先跑一次)

**B-P1.2 retriever/orchestrator 异常窄化(1 周)**
- B-P0.3 完成后,把 `except Exception` 按具体业务异常类(VectorStoreError / TimeoutError / RetryExhaustedError)分类
- 验证:`grep "except Exception" app/rag/retriever.py | wc -l` 降至 < 20

#### B-P2(长期)

- **B-P2.1** 死代码自动检测:Python 用 `vulture`、TS 用 `ts-prune` 加入 CI(可只 warn 不 fail)
- **B-P2.2** ESLint 规则强化:`@typescript-eslint/no-unused-vars: error` + `import/no-unused-modules: error`(扫到 Explore 提的 387 处疑似未使用 export)

---

### 主题 C：测试基建

#### C-P0(本周必修)

**C-P0.1 E2E 关键路径补齐(2 day)**
- 现状:`web/e2e/` 仅 6 个 spec(`management-surfaces.smoke.spec.ts` / `live-stack.smoke.spec.ts` 等),全是烟雾;885 行总代码。
- 动作:补 5-8 条**业务关键路径** spec:
  - `e2e/upload-parse-chunk.spec.ts` —— 上传 PDF → 解析 → chunk 预览
  - `e2e/query-with-trace.spec.ts` —— 提问 → 看到引用 → 看到 trace
  - `e2e/kg-snapshot-diff.spec.ts` —— 建快照 → 修改 → 对比 diff
  - `e2e/feedback-flow.spec.ts` —— 差评提交 → 出现在 feedback page
  - `e2e/quarantine-approve.spec.ts` —— 隔离条目 → 批准 → 入库
- 验证:`pnpm playwright test` 全绿;CI `.github/workflows/ci.yml` 加这 5 条到非 smoke job

**C-P0.2 1893 行单测拆 parametrize(1 day)**
- 现状:`tests/test_connector_internal_helpers.py` 1893 行 + `tests/test_connector_saved_state_resume.py` 1499 行;全仓库仅 23 处 `@pytest.mark.parametrize`
- 动作:重写这 2 个文件,把"复制粘贴 + 改输入"的测试合并为 parametrize 表格;目标 ≤ 500 行 / 文件
- 验证:`wc -l tests/test_connector_*.py` 显著下降;测试数量不减少;`grep -c parametrize` 上升 30+

**C-P0.3 pre-commit 加最小测试(0.5 day)**
- 现状:`.pre-commit-config.yaml` 仅 ruff lint + web ui-check,**无自动测试**
- 动作:加 `pytest -q tests/unit/ --timeout=30`(若有 unit 标签)或 `pytest -q -m "not slow" --timeout=30`;前端加 `pnpm test --changed`(vitest 只跑改动文件)
- 验证:`git commit` 时触发,< 60s

#### C-P1(1-3 个月)

**C-P1.1 `@pytest.mark.slow` 分层 + CI 双轨(2 day)**
- 现状:全仓库 0 处 `@pytest.mark.slow`;3164 个测试全部一锅跑
- 动作:`pytest.ini` 注册 `slow` marker;给真正慢的(集成 / RAG eval / connector 网络层)打标;CI 拆 `fast`(PR check)+ `nightly`(全跑)两条 workflow

**C-P1.2 RAG evaluation 测试扩容(1 周)**
- 现状:`tests/rag/evaluation/` **仅 1 个测试文件**(test_rag_quality_gate.py),但项目核心是 RAG
- 动作:对接 MEMORY 中已规划的 `cn-benchmark-baseline-2026-q2.md`(P0-2)和 `graphrag_bench_runner` —— 把 benchmark 跑成可在 pytest 调用的 fixture,产出 10+ 评测测试

**C-P1.3 覆盖率门槛上调(1 day)**
- 前端 vitest 当前 40% → 提到 60%(强制);后端目前无 coverage gate,先跑一次基线再设(建议 ≥ 70% for `app/rag/` + `app/api/v1/`)

#### C-P2(长期)

- **C-P2.1** 测试 fixture 分层:`tests/unit/` vs `tests/integration/` 物理隔离目录
- **C-P2.2** Mutation testing(`mutmut`)针对核心 `app/rag/` 做 1 次基线评估,而后纳入季度 KPI

---

## 关键文件清单(实施时直接定位)

### 前端(critical files)
- 类型层:`web/types/backend.ts` / `web/types/openapi.ts` / `web/types/{models,processing,datasets,chat,evaluation,common}.ts`
- 巨型组件:`web/app/knowledge/ingestion/page-client.tsx`(5767) / `web/app/knowledge/quarantine/page.tsx`(2802) / `web/components/ragviz/similarity-workbench.tsx`(3426) / `web/components/graph/kg-snapshots-page.tsx`(3261) / `web/components/rag-trace/rag-trace-panel.tsx`(2474) / `web/components/chunk-preview/context.tsx`(1675)
- 状态管理:`web/contexts/*.tsx`(5 files)+ `web/store/*.ts`(3 files)
- UI 重复:`web/components/governance-profiles/profile-editor-drawer.tsx` / `web/components/ingestion/ingestion-detail-dialog.tsx`

### 后端(critical files)
- async sleep 隐患:`app/rag/embedding/providers/openai.py:171,183,193` / `app/rag/embedding/providers/ollama.py` / `app/rag/reranker/base.py` / `app/rag/middleware/error_handler.py`
- except 滥用 TOP 5:`app/rag/retriever.py`(81)/`app/rag/retrieval/orchestrator.py`(73)/`app/parsing/processors/processor.py`(49)/`app/services/report_service.py`(35)/`app/rag/engine.py`(28)
- 巨型文件:`app/parsing/processors/processor.py`(5654)/`app/api/v1/pipeline.py`(3122)/`app/api/v1/datasets.py`(2771)/`app/rag/kg/extraction/extractor.py`(2556)
- 配置:`app/core/config.py`(1103+ 字段)

### 测试(critical files)
- DB mock 红旗:`tests/test_chat_helper_option_inputs.py` / `tests/test_connector_url_batch_checkpoint_resume.py` / `tests/test_dataset_ingestion_defaults.py`
- 巨型测试:`tests/test_connector_internal_helpers.py`(1893)/`tests/test_connector_saved_state_resume.py`(1499)
- E2E 不足:`web/e2e/`(仅 6 spec)
- CI:`.github/workflows/ci.yml` / `.pre-commit-config.yaml`
- 复用资源:`tests/conftest.py`(已有 pg_session fixture,直接用)

---

## 可复用的现有资源(实施时优先复用)

- **ConnectorBase ABC**(`app/connectors/base.py:11`)—— A-P2.3 Chunker base 抽象的模板
- **pg_session fixture**(`tests/conftest.py`)—— B-P0.2 DB mock 替换直接接入
- **openapi-typescript 流程** —— A-P0.1 类型合并复用现有 codegen 脚本
- **Zustand 模式**(`web/store/document-view.ts`)—— A-P0.2 chunk-preview 拆分模板
- **OTel observability**(`app/observability/`,MEMORY 提到已规划)—— B-P0.3 logger.exception 可挂 trace_id

---

## 验证(每个主题完工的客观信号)

### 主题 A 验证
```bash
# A-P0.1: 类型重复消除
grep -rn "export interface\|export type" web/types/backend.ts web/types/models.ts | wc -l
# 目标:从 ~152 降至 < 30

# A-P0.2: chunk-preview 拆分
wc -l web/components/chunk-preview/context.tsx
# 目标:< 600

# A-P0.3: router 错误统一
grep -rn "HTTPException" app/api/v1/ | wc -l
# 目标:大幅下降

# A-P1.1: TanStack Query 迁移
grep -rln "useEffect.*\(fetch\|api\.\)" web/ | wc -l
# 目标:每周下降 ~30 文件
```

### 主题 B 验证
```bash
# B-P0.1: async sleep
python scripts/audit_async_sleep.py app/
# 目标:0 命中

# B-P0.2: DB mock
grep -rn "monkeypatch.setattr.*SessionLocal\|MagicMock.*Session" tests/ | wc -l
# 目标:< 3

# B-P0.3: except 加日志
grep -B1 "except Exception" app/rag/retriever.py | grep -c "logger"
# 目标:> 70(对齐 81 处 except)
```

### 主题 C 验证
```bash
# C-P0.1: E2E 数量
ls web/e2e/*.spec.ts | wc -l
# 目标:≥ 11

# C-P0.2: parametrize
grep -rn "@pytest.mark.parametrize" tests/ | wc -l
# 目标:从 23 升至 ≥ 60

# C-P0.3: pre-commit 测试
cat .pre-commit-config.yaml | grep -c "pytest\|vitest"
# 目标:≥ 2

# C-P1.1: slow 分层
grep -rn "@pytest.mark.slow" tests/ | wc -l
# 目标:> 0
```

---

## 工作量估算与排期建议

| 主题 | P0 | P1 | P2 | 累计 |
|---|---|---|---|---|
| A 架构治理 | 5 day | 3-4 周 | 1 季度+ | — |
| B 正确性风险 | 2.5 day | 1-2 周 | 持续 | — |
| C 测试基建 | 3.5 day | 2-3 周 | 持续 | — |
| **P0 合计** | **~11 day(2 周)** | — | — | 1 sprint 可完成 |

**建议两周冲刺**:第 1 周 = B-P0.1/B-P0.2/B-P0.3 + C-P0.3(正确性 + pre-commit 防线先立);第 2 周 = A-P0.1/A-P0.2/A-P0.3 + C-P0.1/C-P0.2(架构 + 测试基建)。完工后产出"前后端测试健康度月报"(沿用 `_self/2026/` 日志风格)。

---

## 不在本 plan 范围

- **拆超大文件作为独立任务** —— 用户已确认不优先;改为 A-P1.1 TanStack Query 迁移时**顺带**完成
- **27 份"向前看" plan 的能力规划**(行业规则库 / 中文 benchmark / 合规自动化 / DeepDoc API 化 / KG 影响分析等)—— 那些是产品/商业层面的优化,本 plan 仅覆盖代码健康度
- **业务功能新增** —— 不引入任何新依赖、不改 API contract、不动 schema
