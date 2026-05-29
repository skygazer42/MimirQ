# MimirQ 优化收敛与横向 Gap 总览 (2026-Q2 / 05-29)

> 创建日期:2026-05-29
> 性质:**meta 总览**,不是又一份审查。项目已有 63 份 plan,代码质量维度被 `fullstack-code-audit-60items`(05-19,持续更新)/ `fullstack-code-quality-top15` / `code-health-audit` 彻底覆盖。本 plan 只做两件既有 plan **没做**的事:
> - **Part A**:站在 05-29(刚完成 API 文档对齐 + OneKE 接入)指出当前最该收口的高优先级项,并补 60-items 的**盲区**。
> - **Part B**:识别 63 份 plan **从未系统覆盖**的 2 个横向工程 gap(有实证支撑)。

---

## 现状速判(为什么不再写代码质量 plan)

| 维度 | 覆盖度 | 证据 |
|---|---|---|
| 代码质量/健康度 | ★★★★★ 极完整 | 60-items(Critical 11/High 15/Medium 11/Low 6,05-13 仍更新)+ top15 + code-health |
| RAG 功能能力 | ★★★★★ 极完整 | 40+ 份 deep-dive(KG/评测/解析/检索/安全/可视化/agentic…) |
| 产品化/商业化 | ★★★★ | 行业规则库/合规/DeepDoc API/边缘/中文 benchmark |
| 测试覆盖 | ★★★★ 强 | 后端 1307 test 文件 + 前端 631;TODO 债仅后端 8/前端 0 |
| **依赖/环境可复现** | ★ **空白** | 无 lock 文件;训练环境未固化(OneKE 实证) |
| **生产可观测性/SRE** | ★★ 有零件无体系 | `app/core/otel.py` 存在,但无 SLO/告警/性能回归 |

**结论**:不缺功能 plan,不缺代码质量 plan。缺的是 ①把 60-items 的盲区补上 ②两个横向工程 gap 系统化。

---

## Part A — 当前最该收口(补 60-items 盲区,不重列已覆盖项)

### A1 🔴 RAG 核心引擎巨石未进任何拆分计划(60-items 盲区)

60-items 拆了 **API 层**(documents 11770→2235、connectors 10697→523、chat 3653→494),成绩斐然。但 **RAG 核心引擎**这三块最大、最核心、风险最高的巨石,**没有任何 plan 覆盖拆分**:

| 文件 | 行数 | 角色 | 现状 |
|---|---|---|---|
| `app/rag/retriever.py` | **6605** | HybridRetriever(Vector+BM25+SPLADE+ColBERT) | 无拆分计划 |
| `app/rag/retrieval/orchestrator.py` | **5495** | 检索编排器 | 无拆分计划 |
| `app/rag/engine.py` | **4404** | RAGEngine streaming 主路径 | 无拆分计划 |
| `app/parsing/processors/processor.py` | **5711** | 解析主管线 | 60-items H14 提及未动 |

**为什么没人碰**:它们是热路径核心,拆分风险高、测试依赖重。但正因如此最该有**受控拆分计划**(像 chat.py 那样:先抽 service helper,留兼容 wrapper,逐步下沉)。

**建议**:开独立子 plan `rag-core-engine-decomposition`,套用 chat.py 已验证的拆分范式(`services/chat_*` 模式)。**P0**,但需先补这三个文件的 happy-path 测试网(见 A3)再动刀。

### A2 🔴 前端持续膨胀的巨石(60-items H13 漏 ingestion)

| 文件 | 行数 | 60-items 覆盖 |
|---|---|---|
| `web/app/knowledge/ingestion/page-client.tsx` | **5841** | ❌ 未列(最大但漏了) |
| `web/components/ragviz/similarity-workbench.tsx` | 3426 | ✅ H13 标"倒退" |
| `web/app/knowledge/quarantine/page.tsx` | 2909 | ✅ H13 标"倒退" |
| `web/components/graph/kg-snapshots-page.tsx` | 3548 | 部分 |

`ingestion/page-client.tsx` 5841 行是全前端最大文件,且 `rag-ingestion-frontend-deep-dive` plan 已规划"拆 3720 行为 4 子组件"——但实测它已涨到 5841,**规划与现实脱节**。**P0**:按 ingestion-frontend plan 落地拆分。

### A3 🟠 高风险零测试 service(60-items H17 延续)

`dataset_precheck_scan_runner`(1924)/ `dataset_profile_service`(1579)/ `rag_metrics_dashboard`(1500)三个 1500+ 行 service **零测试**。A1 的引擎拆分也依赖先建测试网。**P0**:每个补 ≥5 happy-path test。

### A4 🟡 API 文档/类型 drift 收尾(本轮 05-29 工作延续)

刚完成 API 对齐(openapi 重生成 + industry_rules schema + drift 脚本)。剩余长尾:
- endpoint description 60%(248/407);60-items C9 说还有 160 个缺 docstring
- 13 个前端模块手写类型(settings.ts 26 / rag.ts 11 / evaluation 8 / parsing 8 / prompts 5…),`check-api-types-drift.mjs` baseline 已建,需后端补 response_model 后逐模块迁移并棘轮收紧

**P1**:按 drift 脚本 baseline 渐进,每迁一个模块下调 `HANDWRITTEN_MODULE_BASELINE`。

---

## Part B — 横向 Gap(63 份从未系统覆盖,本 plan 主要价值)

### B1 🔴 依赖与环境可复现性(OneKE 实证,最高价值新 gap)

**实证**:本周做 OneKE 微调时,远端机器经历 torch 2.11→被 pip 升 2.12(破坏 torchvision)、bitsandbytes 0.43↔0.49 与 CUDA 12.4↔13 不匹配、nvidia-cu13 wheel 缺失等一连串环境地狱,耗费大量时间。根因是**依赖与运行环境没有可复现固化**。

| 问题 | 现状 | 风险 |
|---|---|---|
| 无 lock 文件 | 只有 `requirements.txt`(pin 直接依赖),传递依赖未锁 | 不同机器/时间装出不同依赖树 |
| 训练/GPU 环境未固化 | 无 `docker/*train*`,OneKE 环境临时拼装 | 微调/推理环境不可复现,踩坑重复发生 |
| torch/cuda/bnb 版本矩阵脆弱 | requirements 注释提示 Linux 要 `--extra-index-url cpu`,但 GPU 训练栈(peft/bnb/cuda)未纳入管理 | 量化/LoRA 栈随机崩 |

**建议子 plan** `dependency-env-reproducibility`:
- ① 引入 lock(`uv lock` / `pip-tools compile`)锁定全依赖树,CI 校验 lock 与 requirements 一致
- ② 固化 GPU 训练/推理环境:`docker/train.Dockerfile`(pin torch+cuda+peft+bnb 兼容矩阵)+ 一键脚本,把 OneKE workspace 的踩坑经验沉淀为可复现镜像
- ③ 依赖健康看板:CVE 扫描(已有 `make audit`)+ 过时依赖报告 + 升级策略文档
- **P0**(踩坑已造成实际成本,ROI 明确)

### B2 🟠 生产可观测性 / SRE 系统化

**现状**:`app/core/otel.py` 有 OTel 基础,`rag-visualization-deep-dive` 提过埋点,但缺**生产运维闭环**:

| 缺口 | 说明 |
|---|---|
| SLO / 错误预算 | 无定义(p95 延迟、可用性、检索成功率目标) |
| 告警 | 无规则(慢查询、错误率、队列积压、GPU OOM) |
| 性能回归基线 | 有零散 benchmark(`scripts/*benchmark*`)但无 CI 回归门禁 |
| 慢链路追踪 | OTel span 有,但无"最慢 N 个 RAG 查询"运维视图 |

**建议子 plan** `production-observability-sre`:基于现有 otel.py,定义 SLO + 接告警 + 把 `scripts/run_sample_retrieval_benchmark.py` 等纳入 CI 性能回归门禁。**P1**(生产化前必须,但当前若仍 POC 阶段可缓)。

---

## 优先级矩阵

| 项 | 优先级 | 工作量 | 依赖 | 价值 |
|---|---|---|---|---|
| B1 依赖/环境可复现 | **P0** | 1-2 周 | 无 | OneKE 实证,止血重复踩坑 |
| A3 高风险 service 补测试 | **P0** | 1 周 | 无 | A1 前置 |
| A2 ingestion 前端拆分 | **P0** | 1 周 | 无 | 全前端最大文件 |
| A1 RAG 核心引擎拆分 | P0(A3 后) | 3-4 周 | A3 测试网 | 最核心可维护性 |
| A4 API drift 收尾 | P1 | 渐进 | 无 | 本轮延续 |
| B2 可观测性/SRE | P1 | 2-3 周 | 无 | 生产化前必须 |

---

## 立即可做(不需审批,半天内)

1. `uv lock` 或 `pip-tools compile` 生成 lock 文件(B1 第一步)
2. 把 OneKE workspace(`work/oneke_workspace/`)的环境踩坑经验写成 `docs/ops/gpu-training-env.md`(B1 沉淀)
3. `check-api-types-drift.mjs --strict` 跑一次确立基线数(A4)
4. 给 `dataset_profile_service` 补第一个 happy-path test(A3 起步)

---

## 建议拆出的独立子 plan

| 子 plan | 对应 | 优先级 |
|---|---|---|
| `dependency-env-reproducibility-2026-q2.md` | B1 | P0 |
| `rag-core-engine-decomposition-2026-q2.md` | A1 | P0(A3 后) |
| `production-observability-sre-2026-q2.md` | B2 | P1 |

（A2/A3/A4 已有对应既有 plan 或本轮工作覆盖,不必新开。）

---

## 与既有 plan 的边界(不重复声明)

- 代码质量细项 → 见 `fullstack-code-audit-60items`(权威,持续更新),本 plan 不重列
- 前端 ingestion 拆分细节 → 见 `rag-ingestion-frontend-deep-dive`(本 plan 只指出"规划已脱节,实测涨到 5841")
- RAG 功能能力 → 见各 deep-dive,本 plan 不涉及功能
- 本 plan 唯一新增:**A1 核心引擎拆分(60-items 盲区)+ B1/B2 两个横向 gap**

## 一句话

项目代码质量与功能能力已被 63 份 plan 充分覆盖且持续推进;真正的优化空白是 ① **RAG 核心引擎三大巨石**(retriever/orchestrator/engine)无拆分计划 ② **依赖与 GPU 环境不可复现**(OneKE 踩坑实证)③ **可观测性缺生产运维闭环**。其中 B1 依赖可复现性 ROI 最明确,建议先做。
