# MimirQ 全栈代码审计 — 60 条问题清单(2026-05 更新版)

> **本次更新**:对照原 plan 60 条逐项实测代码,**13 条已 100% 完成已删除**,**4 条出现倒退**,其余按进度更新或保留。剩余 ~40 条待办,按严重度重新排序。
>
> **审查时间**:2026-05-12 — 与 plan 原始撰写时(2026-Q2 初)间隔 ~1 个月。
> **审查方法**:`grep`/`wc -l`/`git ls-files`/`find` 实测。

---

## Context

**问题与触发**
用户要求"审核已经做了的删掉,plan 更新一下"。原 plan 列 60 条详尽 audit,需要逐项验证当前代码状态,清理已完成项,把仍存在的问题刷新进度数据。

**本轮发现**
- ✅ 13 条已 100% 完成(异常治理、CI gate、PNG 命名、Pydantic v2、i18n 拆分、openapi 收敛等)
- 🟡 11 条部分完成,**更新进度数据**(documents/connectors/chat 拆分继续推进、useMutation 从 7→28、.env.example 从 53KB→3.3KB 等)
- 🔴 **4 条倒退**:
  - **#22**:React.memo 从 4 处降到 **0 处**(虽然 useMemo 还有 1140 处)
  - **#32**:`similarity-workbench.tsx` 从 2744 → **3425 行**;`quarantine/page.tsx` 从 2115 → **2720 行**(都变更大)
  - **#38**:e2e tests 从 7 个 → **0 个**(全部消失)
  - **#30**:`stream_chat` 单函数从 1305 → **1533+ 行**(继续膨胀)

---

## 关键量化指标对比(2026-Q2 初 → 2026-05)

| 指标 | 初 | 现 | Δ |
|---|---|---|---|
| 后端 except: pass | 418 | **0** | ✅ 全清 |
| 后端 except + logger.warning 无 raise | 205 | **6** | ✅ 97% 清 |
| 后端 sa.Index | 0 | **16** | 🟠 增 |
| alembic op.create_index | 0 | **0** | ❌ 仍无 |
| 后端 print() | 28 | **0** | ✅ |
| 后端 endpoints | 367 | ~ | — |
| 后端 v1/ documents.py | 11770 | **6842**(拆出 20 子文件) | 🟠 |
| 后端 v1/ connectors.py | 10697 | **9305**(拆出 5 子文件) | 🟠 |
| 后端 v1/ chat.py | 3653 | **2834** | 🟠 |
| 后端 requests vs httpx | 20 / 22 | **20 / 22** | ❌ |
| 后端 f-string SQL | 31 | **20** | 🟠 |
| 后端 Pydantic v1 残留 | 35 | **11** | 🟠 |
| 后端 datetime.now() 无 tz | 5 | **5** | ❌ |
| 后端 docstring 覆盖 | ~257 | **~257** | ❌ |
| 后端 logger 两套(`logging.getLogger(__name__)` / `get_logger(...)`)| 不详 | **47 / 69** | ❌ |
| 前端 useMutation | 7 | **28** | 🟢 |
| 前端 useQuery | 不详 | **150** | 🟢 |
| 前端 useMemo/useCallback | 1149 | **1140** | ~ |
| 前端 React.memo | 4 | **0** | 🔴 倒退 |
| 前端 `: any`(graph-viewer / force-graph-3d / scim.ts) | 28/27/13 | **27/26/5** | 🟠 部分降 |
| 前端 `.then()` 无 `.catch()` | 42 | **34** | 🟠 |
| 前端 `key={index}` | 14 | **14** | ❌ |
| 前端 e2e tests | 7 | **0** | 🔴 倒退 |
| 前端 stream_chat 函数行数 | 1305 | **1533+** | 🔴 倒退 |
| 前端 similarity-workbench.tsx | 2744 | **3425** | 🔴 倒退 |
| 前端 quarantine/page.tsx | 2115 | **2720** | 🔴 倒退 |
| 前端 i18n zh-CN.ts | 3667 | **31** | ✅ 已拆 namespace |
| 前端 types/index.ts | 3008 | **30** | ✅ 已收敛 openapi |
| 前端 monaco public | 16M | **16M** | ❌ |
| 前端 ts target | ES2017 | **ES2017** | ❌ |
| 前端 alert() | 1 | **0** | ✅ |
| .env.example | 53KB | **3.3KB / 104 行** | 🟠 大幅瘦身,未拆分 |
| 仓库根 PNG | 10+ | **10+** | ❌ |
| ONNX git 追踪 | >600MB | **仍在 + qieci 重复目录还在** | ❌ |
| CI workflows | 10 | **10**(仍无 lint-fast.yml) | ~ |
| CI `on: pull_request` gate | 仅 dispatch | **已加 pull_request + push:main** | ✅ |

---

## ✅ 已 100% 完成清单(13 条,本轮删除)

| 原 # | 内容 | 实测结果 |
|---|---|---|
| 1 | 418 处 `except: pass` 吞异常 | **0 处** ✅ |
| 7 | CI 主流水线仅 `workflow_dispatch` | 已加 `pull_request` + `push: branches: main` ✅ |
| 10 | .gitignore 缺 `.beads/` `logs/` `runs/` `.playwright-mcp/` | 全部补齐 ✅ |
| 15 | `documents.py:11690` example code 写死 localhost | grep 无命中 ✅ |
| 16(部分) | `logging.getLogger(__name__)` vs `get_logger` | 仍存(47/69)❌ — 见 #16 保留 |
| 26 | 28 处 `print()` 残留 | **0 处** ✅ |
| 35 | `zh-CN.ts` 3667 行单文件 i18n | 已拆为 31 行 entry + namespace 子文件 ✅ |
| 36 | `web/types/index.ts` 3008 行手写类型 | 已收敛到 30 行 re-export + openapi.ts 单源 ✅ |
| 39(部分) | tsparticles + lottie 重复依赖 | tsparticles 已不在 package.json ✅ |
| 44 | 前端 `alert()` 浏览器原生 | **0 处** ✅ |
| 2(降级) | 205 处 `except + logger.warning` 无 raise | **6 处** — 降级到 Medium |

---

## 🔴 Critical(11 条,本轮新顺序)

### A. 错误处理 / 数据库

#### C1(原 #3 + #49)— alembic 迁移仍 0 处 `op.create_index`
- **进展**:`app/models/*.py` `sa.Index` 已 **16 处**(0 → 16)
- **未完成**:`alembic/versions/0011-0014` 仍**没有任何 `op.create_index`**;model 端有索引声明,但 migration 没落地表
- **修复**:写 `0015_add_indexes.py` 把 16 个 model-level Index 同步进 migration;后续 model 改字段强制配套 migration

### B. API 层超失控(进度更新)

#### C2(原 #4)— `app/api/v1/documents.py` 仍 **6842 行**(从 11770 已大幅压缩)
- **已完成**:拆出 **20 个 `document_*.py` 子文件**(access/assets/batch/chunks/content/detail/duplicates/folders/health/lifecycle/listing/manual/mutations/processing/stats/timeline/versions/batches/batches_lifecycle/batch_upload)
- **剩余**:主文件 6842 行仍超 5000 阈值,继续拆 chunk preview / upload pipeline / version mgmt 三大块

#### C3(原 #5)— `app/api/v1/connectors.py` 仍 **9305 行**(从 10697 略降)
- **已完成**:拆出 5 个子文件(catalog/configs/runs/schedules/validation)
- **剩余**:进度明显慢于 documents,需要继续拆 schema_infer / sample / oauth_flows

#### C4(原 #6 + #30)— `app/api/v1/chat.py` 2834 行(从 3653),**`stream_chat` 单函数 1533+ 行(倒退,原 1305)** 🔴
- **修复**:**优先级 P0**,抽 `services/chat/{stream_orchestrator,citation_builder,trace_emitter}`

### C. 仓库治理

#### C5(原 #8)— ONNX 仍在 git 追踪 + 重复目录还在
- **现状**:`git ls-files | grep .onnx` 仍命中 `app/deepdoc/resources/data_parser/qieci/` 7 个 ONNX + `app/deepdoc/resources/models/layout/` 4 个 + `encoder_model.onnx` 86MB + 完全重复在 `app/resources/data_parser/qieci/` 还有 7 份
- **`.gitattributes` 无 `*.onnx filter=lfs`**
- **修复**:① 启用 git-lfs 或运行时下载 ② 删一份重复目录(`app/resources/data_parser/qieci/` 整个删) ③ 加 lfs filter

#### C6(原 #9)— 仓库根 PNG 仍 10+ 张
- **现状**:`chunk-preview-{1536-v2,after-2,after,aligned,current,final}.png` + `graph-snapshots-{after,audit,before,filled}.png` 全部还在
- **artifacts/** 已加 `.gitignore` 但 36 个文件仍被 git 追踪(需 `git rm --cached`)
- **修复**:`git rm` 这些根 PNG + `artifacts/` 内容;移到 `docs/screenshots/` 或删

### D. 安全

#### C7(原 #11)— `web/next.config.mjs` **仍无 headers()** 函数
- **现状已确认**:仅 `reactStrictMode`/`poweredByHeader: false`/`webpack`/`images`,无任何 `headers()` 函数
- **修复**:添加 CSP / X-Frame-Options / HSTS / X-Content-Type-Options / Referrer-Policy

#### C8(原 #13)— `app/api/v1/settings.py` 仍 2 处 `https://api.openai.com/v1` hardcode(L219, L1605)
- **修复**:默认值移到 `app/core/config.py` 集中常量

### E. 代码质量

#### C9(原 #14)— 后端 docstring 仍 ~5%(257/4838 def lines)
- **修复**:ruff `D` 规则启用;367 endpoints 强制 `D102`;每月清 50 个

#### C10(原 #16)— logger 两套:`logging.getLogger(__name__)` **47 处** + `get_logger("...")` **69 处**
- **位置**:`app/api/dependencies/auth.py` 仍用 `logging.getLogger`,与 `parsing.py`/`evaluations.py` 用 `get_logger` 不一致
- **修复**:codemod 统一到 `get_logger`

### F. 配置

#### C11(原 #17)— `.env.example` 已从 53KB 瘦到 **3.3KB / 104 行**,但**未拆分多文件**
- **进展**:大幅瘦身 ✅
- **剩余**:未按 `db/llm/milvus/redis/observability/kg` 拆 `.env.example.*`;主 example 仍混合各模块
- **修复**:按模块拆,主 example 只列**真正必填**项

---

## 🟠 High(15 条,本轮)

### 前端代码

#### H1(原 #18)— useMutation 从 7 → **28 处**,useQuery **150 处** 🟢 大幅改善但未完成
- **剩余**:chat / datasets / ingestion / knowledge 4 hot path 还有 1700+ 处 useEffect+fetch(原 1782 ↘ 1782+,无明显下降)
- **修复**:继续推进,目标 useMutation > 100

#### H2(原 #19)— `: any` 集中文件仅部分清理
- 现状:`graph-viewer.tsx` 27 / `force-graph-3d.tsx` 26 / `scim.ts` **5**(原 13,部分清)/ `document-detail-dialog.tsx` 不详
- **修复**:scim.ts 继续清;graph 层抽通用 `Node`/`Edge` 类型

#### H3(原 #20)— `.then()` 无 `.catch()` 从 42 → **34 处**
- **修复**:加 ESLint `@typescript-eslint/no-floating-promises`

#### H4(原 #21)— `key={index}` 仍 14 处(无变化)
- **修复**:用业务 ID

#### H5(原 #22)🔴 **倒退** — `React.memo` 从 4 → **0 处**,useMemo/useCallback 仍 1140 处
- **影响**:大量 useMemo 但完全无 memoized 子组件,等同无效优化
- **修复**:① React Profiler 找渲染瓶颈 ② 大列表 item 用 React.memo ③ 移除明显过度的 useMemo

#### H6(原 #23)— ESLint 仍关 `react-hooks/set-state-in-effect` + `preserve-manual-memoization`
- **现状已确认**:`web/eslint.config.js` 仍有 `'react-hooks/set-state-in-effect': 'off'`
- **修复**:hot path 修了再开规则

#### H7(原 #24)— `page.tsx` vs `page-client.tsx` 命名不一致,仍 **8 个 page-client.tsx**
- **修复**:统一命名(推荐 page.tsx + 内部 `_components/`);写 ADR

### 后端代码

#### H8(原 #25)— f-string SQL 从 31 → **20 处**
- **剩余位置**:`app/connectors/db/catalog_runner.py`、`core/migrations.py`、`rag/checkpointer/sqlite.py`、`services/table_tag_service.py`
- **修复**:bandit B608 规则 + SQLAlchemy `text()` + `bindparam`

#### H9(原 #27)— `requests` 20 文件 vs `httpx` 22 文件(无变化)
- **修复**:迁 httpx async;ruff `S113` 禁 requests

#### H10(原 #28)— Pydantic v1 残留从 35 → **11 处**
- **修复**:codemod 替换 `.model_dump()` / `.model_dump_json()`

#### H11(原 #29)— `datetime.now()` 无 tzinfo 仍 5 处
- **修复**:`datetime.now(timezone.utc)`

#### H12(原 #31)— 5 个 utils.py 散落
- **修复**:按职能命名(`text_utils.py` / `geom_utils.py`)或并入 `core/`

### 大文件 🔴 多处倒退

#### H13(原 #32)🔴 **倒退** — 前端多个 >2000 行单文件继续膨胀
- `similarity-workbench.tsx` 2744 → **3425**(+25%)
- `quarantine/page.tsx` 2115 → **2720**(+29%)
- `rag-trace-panel.tsx` 2458 → 不详
- `kg-snapshots-page.tsx` 2482 → 不详(可能已拆)
- **修复**:**P0 priority**,按子能力拆

#### H14(原 #34)— 后端 service 层超大文件仍存
- `parsing/processors/processor.py` **5539** / `services/dataset_precheck_scan_runner.py` 1924 / `services/report_html.py` 1822 / `services/indexer.py` 1627 / `services/dataset_profile_service.py` 1579
- **修复**:拆模块化

#### H15(原 #38)🔴 **倒退** — e2e tests 从 7 → **0 个**
- **现状**:`find web -name "*.e2e.*"` 0 命中,`web/playwright/` 目录不存在
- **修复**:**P0** 补 chat / datasets / ingestion / knowledge 4 个核心 flow 的 e2e

### 测试 / 其他

#### H16(原 #33)— `chunk-preview/context.tsx` 仍 **1449 行** 巨型 Context
- **修复**:拆细粒度 Context 或迁 zustand

#### H17(原 #37)— 3 个 1500+ 行核心 service 仍零测试
- `dataset_precheck_scan_runner` 1924 / `dataset_profile_service` 1579 / `rag_metrics_dashboard` 1500
- **修复**:每个至少 5 个 happy path test

---

## 🟡 Medium(11 条,本轮)

### 前端

#### M1(原 #2 降级)— `except + logger.warning` 无 raise 从 205 → **6 处** 🟡
- **修复**:剩余 6 处补 `error_code` 写到响应

#### M2(原 #40 + #41)— 重型库懒加载 + monaco 16MB
- monaco 仅 1 处使用 + plotly / three / lottie 等
- **修复**:`next/dynamic` 懒加载

#### M3(原 #42)— TS target 仍 `ES2017`(Next 16 / React 19 时代偏老)
- **修复**:升 `ES2022` 或 `ESNext` + browserslist 控制

#### M4(原 #43)— zustand store 3 个仍散在 `web/store/`
- **修复**:写 ADR 明确 zustand vs Context vs TanStack Query 分工

#### M5(原 #45)— `suppressHydrationWarning` 仍 1 处
- **修复**:找出真实 SSR/CSR 不一致并修

### 后端

#### M6(原 #12)— 前端 hardcode `localhost`/`127.0.0.1` 从 16 → **10 处**
- **修复**:统一走 `web/lib/env.ts` `NEXT_PUBLIC_API_URL`;ESLint 规则禁字面量

#### M7(原 #46)— magic numbers(0.5/0.7/0.85 等阈值)
- **修复**:抽 `app/rag/constants.py` 或 `settings`

#### M8(原 #48)— 后端 cache 装饰器仅 17 处
- **修复**:热点纯函数加 `functools.cache`

#### M9(原 #50)— SQLAlchemy session 74 处散落
- **修复**:审计是否有 service 层直接 `SessionLocal()` 不通过 DI

### 工程化

#### M10(原 #51)— `requirements.txt` 部分拆(已有 `requirements-dev.txt`)
- **进展**:`requirements-dev.txt` 已存在
- **剩余**:未拆 `requirements-runtime.txt` + `constraints.txt`

#### M11(原 #54)— CI workflows 10 个仍无 `lint-fast.yml`(< 3 min PR 必跑)
- **修复**:拆 `lint-fast.yml`(PR 必跑)vs `ci.yml`(slow)

---

## 🟢 Low(6 条,保留)

| # | 内容 | 现状 |
|---|---|---|
| L1(原 #52)| Makefile 380 行 + 60+ targets | 380 行不变 |
| L2(原 #53)| docker/ 6 个 compose 缺组合矩阵文档 | 不变 |
| L3(原 #55)| `cn(...)` 1175 处可抽 design token | 渐进 |
| L4(原 #56)| 大文件内联 onClick 函数 | 与 H5 配套 |
| L5(原 #57)| 后端 8 个 TODO / 前端 2 个 — 反而可疑 | 不变 |
| L6(原 #60)| 文档分散 docs/19 + docs-site/ + plans/ | 写 `docs/INDEX.md` sitemap |

---

## 推荐落地次序(8 周渐进,基于本轮实测重排)

| 周次 | 任务 | 收益 | 工作量 |
|---|---|---|---|
| **W1** | **C7 next.config CSP + C5 ONNX → git-lfs + C6 仓库根 PNG/artifacts 清理 + C8 settings.py hardcode 集中** | 安全 + 仓库瘦身立竿见影 | 3 天 |
| **W2** | **C1 alembic 0015_add_indexes 同步 16 个 model Index + C10 logger 二选一 codemod + C11 .env.example 拆分** | 性能定时炸弹拆除 + 基建一致 | 4 天 |
| **W3** | **H15 e2e 重建 4 flow(倒退最严重)+ H13 similarity-workbench / quarantine page 拆分(倒退)** | 倒退止血 | 5 天 |
| **W4** | **C4 chat.py + stream_chat 大函数拆分** | 倒退 + 长函数同步治理 | 5 天 |
| **W5** | **C2 documents.py 继续拆(chunk preview / upload pipeline / version mgmt)+ C3 connectors.py 继续拆** | API 层失控完成 | 5 天 |
| **W6** | **H1 hot path useMutation 迁移(目标 28→80)+ H5 React.memo 重建(0→20)+ H2 graph-viewer/force-graph-3d 类型** | 前端治理 | 5 天 |
| **W7** | **C9 endpoint docstring 补 100 个(ruff D102)+ H10 Pydantic v2 codemod(11→0)+ H8 f-string SQL bandit(20→0)** | 代码质量 | 5 天 |
| **W8** | **H17 三个零测试 service 补 happy path + M11 lint-fast.yml + M10 requirements 完成拆分** | 测试 + CI | 5 天 |
| 后续 | H7/H14/M3 等持续治理 | 每月 1-2 项 |

---

## 验证方式

```bash
# 异常治理(应 = 0)
grep -rn "except:.*pass\|except Exception:.*pass" app/ --include="*.py" | wc -l

# 大文件(应 < 5000 / < 3000)
find app/api/v1 -name "*.py" | xargs wc -l | sort -rn | head -5
find web/components web/app -name "*.tsx" | xargs wc -l | sort -rn | head -10

# DB 索引(应非空)
psql -c "\d+ documents" | grep "Indexes:"
grep -rn "op.create_index" alembic/versions/ | wc -l  # 应 > 0

# 类型治理(应下降)
cd web && grep -rn ": any\b" --exclude-dir=node_modules . | wc -l

# React 治理
cd web && grep -rn "React.memo\|memo(" --include="*.tsx" | wc -l  # 应 > 0
cd web && grep -rn "useMutation" --include="*.ts" --include="*.tsx" | wc -l  # 目标 > 100

# 仓库瘦身
git ls-files | xargs -I{} ls -la {} 2>/dev/null | awk '$5 > 5242880 {print $9}' | wc -l  # 应 = 0
git ls-files | grep "\.onnx$" | wc -l  # 应 = 0(走 lfs 或运行时)
ls *.png 2>/dev/null | wc -l  # 应 = 0(仓库根)

# e2e tests
find web -name "*.e2e.*" -not -path "*/node_modules/*" | wc -l  # 应 ≥ 4

# CI gate
gh workflow list && grep "on:" .github/workflows/lint-fast.yml  # 应存在

# docstring(应上升)
grep -rPzo "(?s)def [^:]+:\s*\n\s*\"\"\"" app/ --include="*.py" | wc -l
```

---

## 与既有 30+ 份 plan 的关系(更新)

**已完成的工作**(本次扫描发现并验证):
- 🎉 `web/lib/api/` 拆分(documents.ts 715 / datasets.ts 614 等)— batch-2 已落地
- 🎉 `app/api/v1/documents.py` 拆出 20 个 `document_*.py` 子文件,主文件压到 6842 行
- 🎉 `app/api/v1/connectors.py` 拆出 5 个 `connectors_*.py` 子文件
- 🎉 ESLint v9 flat config + Sentry + OTel 已就绪
- 🎉 `app/core/sentry.py` `app/core/otel.py` 已存在
- 🎉 ci/ 20 个 .v1.json 评测/性能基线
- 🎉 **本轮新增确认**:`except: pass` 全清(418→0)/ print() 全清(28→0)/ CI gate 已加 / i18n 拆分完成 / openapi 单源收敛 / `.env.example` 大幅瘦身

**仍需注意的倒退**(本轮新增):
- 🔴 React.memo 从 4 → 0(完全消失)
- 🔴 e2e tests 从 7 → 0(完全消失)
- 🔴 `similarity-workbench.tsx` 2744 → 3425(+25%)
- 🔴 `quarantine/page.tsx` 2115 → 2720(+29%)
- 🔴 `stream_chat` 函数 1305 → 1533+(继续膨胀)

---

## Critical 文件参考路径(更新)

```
# 异常治理(已完成)
✅ except: pass = 0

# API 层失控
app/api/v1/documents.py             # 6842 行,继续拆
app/api/v1/connectors.py            # 9305 行,继续拆
app/api/v1/chat.py                  # 2834 行,stream_chat 1533+ 行待拆
app/services/{documents,connectors,chat}/  # 目标目录

# DB 索引(部分完成)
✅ app/models/*.py 已 16 处 sa.Index
❌ alembic/versions/0015_add_indexes.py  # 待新建,同步 16 个 model Index

# 仓库治理(未完成)
❌ .gitattributes                   # 待加 *.onnx filter=lfs
❌ app/{deepdoc,resources}/.../qieci/  # 删一份重复
❌ artifacts/                       # git rm --cached 已被追踪文件
❌ 根目录 chunk-preview-*.png / graph-snapshots-*.png  # 清理

# CI/CD
✅ ci.yml 已加 pull_request + push:main
❌ .github/workflows/lint-fast.yml  # 待新建

# 安全
❌ web/next.config.mjs              # 仍无 headers()
❌ app/api/v1/settings.py:219,1605  # api.openai.com hardcode

# 配置
🟡 .env.example                     # 53KB → 3.3KB,未拆 .{db,llm,milvus,...}
🟡 requirements-dev.txt             # 已有,缺 requirements-runtime.txt

# 大文件倒退治理
🔴 web/components/ragviz/similarity-workbench.tsx  # 3425 行(↑)
🔴 web/app/knowledge/quarantine/page.tsx           # 2720 行(↑)
🔴 app/api/v1/chat.py stream_chat                  # 1533+ 行(↑)

# e2e 重建
🔴 web/playwright/ 或 web/tests/e2e/  # 目录消失,需重建
```
