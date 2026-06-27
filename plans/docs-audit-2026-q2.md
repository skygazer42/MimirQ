# MimirQ 文档审核报告 — docs/ + docs-site/ 全量

> 日期：2026-06-23
> 方法：8 个并行 Explore agent 审核 316 个文档文件（docs/ 173 + docs-site/ 143），三维度（准确性 / 完整性 / 结构），全部以真实代码 `grep`/`wc` 为基准。关键争议事实由主审 Claude 亲自二次核实（见 §2）。
> 配套：能力基准见 `plans/capability-master-map-2026-q2.md`。

---

## 1. 执行摘要

**整体健康度 ≈ 2.6 / 5**。文档**结构组织良好、覆盖面广**，但存在一条贯穿全库的系统性问题：**能力声明跑在实现前面**——文档描述的是"设计意图"，不是"当前代码"。对内部开发会误导排查方向，对外（docs-site 面向客户）会造成过度承诺。

### 8 组健康度评分

| 文档组 | 文件范围 | 评分 | 主要病症 |
|---|---|---|---|
| 核心技术文档 | docs/ architecture/backend_structure/API… | 2.5 | 功能成熟度标注混乱（已实现 vs 框架 vs 占位不分） |
| API 参考 000-013 | docs/api/reference/ | 2.5 | 3 处代码示例跑不通（token 未定义、client.chat() 不存在） |
| API 参考 014-027 | docs/api/reference/ | **1.5** | 隐瞒指标数（只列 3/37）、安全功能 stub 未标注 |
| guides/prompts/templates | docs/guides/ … | 3.2 | 个别夸大（feedback 闭环、late_chunking），template 是空壳 |
| deployment/integration | docs/deployment/ … | 3.2 | pgvector stub 隐瞒、GPU 诊断缺失、限流 key 未说明 |
| docs-site 后端 | docs-site/docs/backend/ | 2.5 | SPLADE/connector/embedding provider 数夸大 |
| docs-site 前端 | docs-site/docs/frontend/ | 2.8 | API 拆分结构滞后、治理 UI 边界模糊 |
| docs-site ops + README | docs-site/docs/ops/ + 顶层 | 2.5 | **/health/live 死链**、README 特性过度承诺 |

---

## 2. 已核实纠正的 agent 矛盾（严谨性记录）

8 组 agent 之间存在互相冲突的结论，主审已逐一用代码核实，**以下为最终事实**（避免按错误二手结论改文档）：

| 争议 | 部分 agent 的说法 | 核实真相（代码佐证） |
|---|---|---|
| `/health/live` 端点 | 存在 | ❌ **死链** — `health.py` 仅 `/health` + `/health/ready` |
| `/minio/health/live` | 死链 | ✅ **MinIO 官方真端点**，不可改（一个 agent 误判） |
| `system_prompts.py` | 26 行 / 40+ 行 | **26 行**（确） |
| `useMutation` 使用 | 0% / 136 处 | **48 处 / 19 文件**（两说都错） |
| `agentic_beam_search.py` | 纯 stub / 完整实现 | **143 行，含 5 处 LLM 调用 = 轻量实现**；但 `plan_on_graph.py` 仅 37 行偏薄 |
| config 项数 | 800+ / 1198 / 1241 | **1210** |
| embedding provider | 7 个 / 5-6 个 | **8 个文件**（4 真实现 + voyage/cohere/jina/bedrock 4 空壳） |
| 文档写了 "4261" | 文档过时写了 4261 | ❌ **docs 里零出现**（agent 臆测，api-client 文档实际未写行数） |

> 教训：多 agent 审核必须有主审复核层，否则会把"幻觉"写进修复。

---

## 3. 三大系统性问题（跨组归纳）

### 问题 A：能力声明跑在实现前（最普遍，占高严重度 70%）
文档把"框架/占位/默认关闭"描述成"已交付能力"：
- `health-probes.md` 整篇虚构端点与返回格式（✅ 已修）
- `014-安全最佳实践`：output_guard 123 行 + llama/prompt guard 是正则 stub，文档当"最佳实践"讲
- `016-评估-ragas`：只列 3 个 metric，实际 37 个（且无统计显著性未提）
- `026-分块策略`：late_chunking_jina（798 行 NotImplementedError）、RAPTOR（仅 leaf 层）当完整功能列
- `backend/more/retrieval.md`：SPLADE 默认关闭却写进默认混合检索
- README / feature_benchmark：LTR/ColBERT/KG/Self-RAG/FLARE 框架态当核心特性

### 问题 B：配置与结构数字过时
- config「800+/1198」实际 1210（✅ 已批量修正 5 处）
- embedding「15 模型 7 provider」实际 8 文件含 4 空壳
- 前端 api-client「单文件」实际已拆 132 行索引 + lib/api 9 模块
- useMutation 描述「0%/缺失」实际 48 处已用

### 问题 C：能力边界未说明（沉默的缺口）
文档不写"做不到什么"，客户按文档踩坑：
- **chunk 级权限缺失**（仅 document 级 ACL）——多处文档暗示可做 chunk 级
- **反馈无自动 re-train**（dispatcher 是 pull/batch）——文档说"自动化闭环"
- **行业规则库前端 UI 不存在**——governance 文档列了组件
- **任务队列无持久保证/无 DLQ**（arq 可选）——部署文档未提
- **pgvector 仅 7 行 stub**——部署文档当可选后端列

---

## 4. 🔴 高严重度清单（带修复状态）

| # | 文件 | 问题 | 状态 |
|---|---|---|---|
| 1 | `docs-site/docs/ops/health-probes.md` | 整篇虚构：`/health/live` 死链、返回字段 status/version/uptime 全不存在、liveness 探针配错（会致 Pod 雪崩） | ✅ **已重写** |
| 2 | `docs-site` config 项数 800+/1198 | 实际 1210 | ✅ **已修 5 处** |
| 3 | `docs/quickstart.md` LLM 小节 | Claude `ChatAnthropic` 示例跑不通（仅 OpenAI-compatible，无 native Claude/Gemini） | ⏳ 待修 |
| 4 | `docs/api/reference/013` L99/112 | `token` 变量未定义，Vue 示例 runtime 报错 | ⏳ 待修 |
| 5 | `docs/api/reference/010` L40 | `client.chat()` 方法不存在（示例仅实现 chat_stream） | ⏳ 待修 |
| 6 | `docs/api/reference/016` + `guides` | 只列 3 个 metric，实际 37 个；无统计显著性未标注 | ⏳ 待修 |
| 7 | `docs/api/reference/014` 安全最佳实践 | output/llama/prompt guard 是 stub，未标注 best-effort；chunk 级权限承诺过度 | ⏳ 待修 |
| 8 | `docs/api/reference/026` 分块策略 | late_chunking_jina / RAPTOR 简化版未标注 | ⏳ 待修 |
| 9 | `docs-site/backend/more/retrieval.md` | SPLADE 默认关闭却写进默认混合检索；reranker/pgvector 描述不准 | ⏳ 待修 |
| 10 | `docs-site/backend/documents/connectors.md` | 暗示有 Web Crawl 等，实际仅 2 个 DB catalog | ⏳ 待修 |
| 11 | `docs-site/backend/welcome.md` | 「15 模型 7 provider」实际 8 文件 4 真+4 空壳 | ⏳ 待修 |
| 12 | `README.md` L69-72 | LTR/ColBERT/KG 框架态当核心特性宣传 | ⏳ 待修 |
| 13 | `SECURITY.md` L20-39 | output/llama/prompt guard 当完整安全能力声明 | ⏳ 待修 |
| 14 | `docs/feature_benchmark.md` | Self-RAG/FLARE「已实现」实为框架骨架 | ⏳ 待修 |

> #1#2 已修（最高影响：死链致生产事故 + 配置数字）。#3-#14 多为「加一句限制说明 / 改一个数字 / 降级表述」，单项 5-30 分钟，建议下一轮批量处理。

## 5. 🟠 中 / 🟡 低严重度（归类）

- **过时引用/死链**：architecture.md 引用不存在的 guides；errors.md 链向 backend/testing.md 需验证存在性
- **示例不可移植**：多处 curl 硬编码 `http://localhost:8000`，建议改 `${MIMIRQ_API_HOST}`
- **空壳文档**：`templates/retrieval_debt_audit_template.md`（32 行纯占位）、`prompts/…` A.3 章只有 TOC 无内容
- **标题/内容不符**：`guides/lexical_fallback.md` 讲 Postgres FTS 却叫 fallback
- **版本/迁移缺失**：`021-版本历史` 无 breaking changes；`API_CONTRACT.md` 迁移无时间承诺
- **默认值不准**：embedding 默认 `text-embedding-3-small`（部分文档写 bge-m3）

## 6. 📋 完整性缺口（应补文档）

| 缺口 | 优先级 |
|---|---|
| LLM 模型支持矩阵（OpenAI-compatible 边界、是否支持 Claude/Gemini native） | 高 |
| 系统 prompt 设计原则（engine 26 行 prompt 无说明文档） | 高 |
| chunk 级权限「已知限制」说明 | 高 |
| 连接器真实清单（仅 2 DB catalog）+ 扩展指南 | 中 |
| GPU/VRAM 运行时诊断（ColBERT/MinerU 部署） | 中 |
| pgvector「experimental」标注 | 中 |
| types/index.ts 类型系统说明（已重构 30 行索引） | 中 |
| 反馈闭环边界（无自动 re-train）说明 | 中 |

---

## 7. 本轮已执行修复

1. ✅ **重写 `docs-site/docs/ops/health-probes.md`** — 端点改为真实的 `/health`（liveness 轻量）+ `/health/ready`（readiness 检依赖）；返回示例改为真实字段；K8s livenessProbe 由死链 `/health/live` 改为 `/health`（修复潜在 Pod 雪崩）；删除虚构的 status/version/uptime 字段。
2. ✅ **批量修正 config 项数** — `backend/welcome.md`、`backend/more/platform.md`、`ops/welcome.md` 及 2 个 i18n en-override，`800+` → `1200+`（实测 1210），共 5 文件。
3. ✅ **`docs/quickstart.md` Claude 接入** — 删除跑不通的 `ChatAnthropic` 代码，改为 `LLM_API_BASE`/`LLM_MODEL` OpenAI 兼容配置 + 协议转换说明（符合真实架构）。
4. ✅ **`backend/more/retrieval.md`** — SPLADE 标注「默认关闭」、ColBERT 标注「可选」，mermaid 后补默认混合检索（Vector+BM25+RRF）说明。
5. ✅ **`backend/welcome.md` embedding 段** — 默认模型改为真实的 `text-embedding-3-small`（原误写 bge-m3），provider 标注 4 真实现 + 4 占位，检索模式与 retrieval.md 对齐。
6. ✅ **`README.md`** — 检索质量特性 SPLADE/ColBERT/LTR 标注「可选」（L71「文档级 ACL」经核实为诚实表述，保留）。
7. ✅ **`013-前端集成指南.md`** — Vue 示例补 `token` 定义（原 `${token}` 未声明，runtime 报错）。
8. ✅ **`010-实战场景示例.md`** — 场景2 `client.chat()`（SDK 不存在）改为真实的 `client.chat_stream()` 流式收集；结构化输出引导至后端能力说明。
9. ✅ **`016-评估系统-ragas.md`** — metric 从只列 3 个补全为全部 **37 个**（10 RAGAS + 27 确定性，按代码 `frozenset` 逐一列出），并加「无统计显著性」限制警告。

**经核实判定「无需修改」（agent 高估，避免误改）**：
- `connectors.md` — 表述克制准确（已写明"主要支持 URL + DB"，Web Crawl 标「(扩展)」）
- `SECURITY.md` — 实际未声称 guard 能力（grep 仅请求体大小限制），无夸大
- `welcome.md`/`minio_integration.md` 的 `/minio/health/live` — MinIO 官方真端点，非死链

**§4 高严重度最终状态（权威，覆盖 §4 表中的 ⏳ 标记）**：
- **已修 9 项**：#1 health-probes 重写 / #2 config 数字 / #3 quickstart Claude / #4 013 token / #5 010 SDK / #6 016 metric / #9 retrieval SPLADE / #11 welcome embedding / #12 README 特性。
- **经代码核实判定「无需改」5 项（agent 幻觉或高估，盲改会破坏）**：
  - #7 `014` — grep 确认**未声称任何 guard**（是完整性缺口，非夸大）
  - #8 `026` — grep 确认**未提 late_chunking/RAPTOR**；且 `late_chunking_jina.py` 实为 25 行 0 NotImpl（非"798 行未实现"）
  - #10 `connectors.md` — 表述克制准确（已标"主要支持 URL+DB"）
  - #13 `SECURITY.md` — 未声称 guard 能力
  - #14 `feature_benchmark` — grep 确认**未提 Self-RAG/FLARE**；且 `self_rag.py`=89 行 / `flare.py`=78 行均 **0 个 NotImplementedError = 真已实现**，agent 双重幻觉

> 关键教训：8 组 agent 报告中，**约 10 处结论是幻觉或高估**（虚构端点为真、把已实现说成 stub、把准确文档说成夸大、臆造行数）。全部经主审 `grep`/`wc` 复核拦截。**多 agent 审核必须有主审复核层，否则会把幻觉写进修复。**

## 8. 后续修复优先级

- **P0（本轮已做）**：死链 health-probes + config 数字
- **P1（高严重度 #3-#14，建议下一轮批量）**：跑不通的示例（quickstart Claude / 013 token / 010 chat）、安全 stub 标注、metric 数补全、SPLADE/connector/embedding 数字校正、README/SECURITY 降级表述
- **P2（中低 + 缺口）**：空壳文档补内容、curl 变量化、补 LLM 矩阵 / chunk 权限限制 / pgvector experimental 标注

> 一句话：本轮清除了最危险的「虚构 + 死链」（生产事故级），其余高严重度集中在「加一句限制 / 改一个数字 / 降级一个表述」，已逐条定位到文件:行，可机械化批量修。
