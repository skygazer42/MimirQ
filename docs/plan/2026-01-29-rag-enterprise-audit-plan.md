# MimirQ RAG 企业级审计与优化计划（2026-01-29）

> 覆盖范围：import 降级策略、企业级代码规范（Dify/RAGFlow 风格）、脚本命名规范。
>
> 说明（Corridor）：`AGENTS.md` 要求在生成代码前使用 Corridor MCP 做安全分析，但当前环境未配置 `corridor` MCP
> Server。本计划基于人工审计 + 本地测试结论整理。

## 1) 目标

- 消除由于 “try import + broad except” 带来的隐藏降级、静默失效与行为漂移。
- 对齐企业级 RAG 项目基线（可观测、可定位、默认安全、分层清晰、错误处理一致）。
- 标准化 `scripts/` 的命名与接口，便于运维/CI/CD 稳定调用与长期治理。

## 2) 本轮非目标

- 不做大规模的 RAG 流程重写（除非为修复安全/一致性问题必须改动）。
- 不替换现有技术栈（FastAPI/LangChain/Milvus/Postgres/Next.js）。

## 3) 审计发现（按优先级）

### P0 - 必须修（语义 bug / 静默失效 / 风险高）

1) `StrEnum` 降级实现存在语义错误（会引发隐性行为差异）
- 证据：`app/rag/chunking/ragflow/common/constants.py:7-10`
- 当前行为：缺少 `strenum` 时，用 `Enum` 伪装成 `StrEnum`，导致字符串枚举语义失效。
- 目标行为：
  - Python 3.11+：优先使用标准库 `enum.StrEnum`
  - Python <3.11：使用 `strenum.StrEnum`（或实现一个最小但正确的 `str` 枚举 fallback）

2) “try import + except Exception” 吞掉真实异常，造成“看似可用、实际部分失效”
- 证据：
  - `app/rag/chunking/ragflow/chunkers/naive.py:39-42`（`except Exception: TCADPParser=None`）
  - `app/services/document_qa_service.py:268-272`（`except Exception: hybrid_retriever=None`）
  - `app/tasks/locks.py:12-17`（`except Exception: return None`，影响 `arq.Retry` 语义）
- 风险：
  - 非 ImportError（版本不兼容、运行时异常、语法错误）被吞掉，导致排障困难。
  - 功能静默半失效（例如 QA 索引清理跳过，导致检索污染/数据陈旧）。
  - 任务锁/重试语义可能退化为“无重试/无并发限制”，线上风险高。

3) 可选依赖的降级策略“静默”，对运维不友好、对质量不透明
- 证据：
  - `app/services/web_crawler.py:125-128`（`lxml` 导入失败直接返回空链接）
  - `app/services/table_routing.py:101-104`（`openpyxl` 缺失导致 shape 不可得，行为降级不透明）
  - `app/services/dataset_precheck_scan_runner.py:380-409`（`pdfplumber` 异常直接返回空样本）
  - `app/services/dataset_precheck_scan_runner.py:467-470`（`openpyxl` 异常返回 None）
- 目标行为：
  - import 边界只捕获 `ImportError`（真正的“缺依赖”）。
  - 降级必须显式：告警日志 + 结构化 `degraded_reason` 回传给调用方/前端。
  - 当功能被启用/被选择（selected/enabled）时，缺依赖应 fail-fast 并给出可执行的修复提示。

### P1 - 强烈建议（企业级可维护性/一致性）

4) Lint 门禁偏弱，不足以约束企业级代码规范
- 证据：`ruff.toml` 仅启用 `E4/E7/E9/F`
- 影响：无法有效约束：
  - broad-except（`except Exception`/`BaseException`）
  - import 排序
  - 命名规范
  - 复杂度/可读性
  - 类型友好性

5) ragflow 搬运代码未隔离，导致全局风格难统一
- 证据：`app/rag/chunking/ragflow/...`
- 影响：难以在不破坏上游 diff 的情况下强推全局规范；也容易让“非企业级模式”扩散到业务层。

### P2 - 仓库治理/运维

6) 仓库存在杂项跟踪文件
- 证据：根目录 `a.txt` 已被 git 跟踪
- 影响：降低仓库信噪比，影响合规/审计/CI 质量。

## 4) 目标规范（落地后的“约束”）

### 4.1 Import 规范（强制）

- 内部模块（`app.*`）禁止通过 `try/except` 做降级；应修复根因（循环依赖、初始化时机等）。
- 可选第三方依赖：
  - import 边界只捕获 `ImportError`
  - 统一使用工具函数：
    - `optional_import("pkg", feature="...")`：返回模块/None，并打印结构化告警日志
    - `require_dependency("pkg", feature="...")`：抛 `RuntimeError`，包含安装提示与 remediation
- 禁止 `except Exception` 包裹 import（除非立即 re-raise 并补充上下文，且有明确理由）。

### 4.2 错误处理与可观测性（企业级基线）

- 任何“best-effort/降级”都必须可观测：至少 `warning` 日志，包含：
  - feature、dependency、reason、remediation
- 明确区分：
  - 缺依赖（`ImportError`）
  - 运行时异常（bug/版本不兼容）
  - 输入不合法/格式不支持

### 4.3 脚本命名规范（企业级基线）

- Python：`snake_case.py`，动词优先（`check_*` / `verify_*` / `export_*` / `gen_*` / `benchmark_*` / `doctor_*` / `clean_*`）。
- PowerShell：`snake_case.ps1`，动词优先；dev 启动脚本统一 `dev_*` 前缀。
- 若必须重命名：
  - 至少保留一个版本周期的兼容 wrapper
  - 同步更新 Makefile 目标与脚本文档

## 5) 执行计划（20 个任务）

> 每个任务必须包含：代码变更 + 测试（单测/必要时集成）+ 日志/指标验证。

### Phase 0 - 先立规矩和门禁（T01-T03）

- T01：新增 `docs/standards/import-policy.md`，把 import/降级策略写成“硬规则”。
- T02：升级 ruff 规则集（至少加入 BLE/B/I/N 等），对 vendor 目录做 per-dir ignore。
- T03：引入 pre-commit（ruff/format/基础安全检查）+ CI 门禁（至少 `make lint-py` + `pytest`）。

### Phase 1 - 修 P0（T04-T12）

- T04：修复 `StrEnum` fallback（py311 优先 `enum.StrEnum`）。
- T05：把广泛 except 的 import 改为仅捕获 `ImportError`：
  - `app/tasks/locks.py`
  - `app/services/document_qa_service.py`
  - `app/services/web_crawler.py`
  - `app/services/table_routing.py`
  - `app/services/dataset_precheck_scan_runner.py`
- T06：实现统一的 `optional_import()/require_dependency()` 工具，并迁移核心热路径。
- T07：Web crawler：依赖缺失时返回结构化 degraded 结果 + 告警日志，避免“返回空=看似成功”。
- T08：Dataset 预检：返回结构化 `dependency_missing` / `parse_failed` 等原因，禁止静默空结果。
- T09：Table routing：`.xlsx` shape 不可读时的行为改为显式、可配置、默认安全。
- T10：QA 清理：去掉内部 `try import` 降级，必要时通过分层/解耦解决循环依赖。
- T11：PII 脱敏链路：确保“开关开启=实际生效”，禁止静默绕过。
- T12：为上述 P0 场景补单测（覆盖 ImportError 与 degraded signaling）。

### Phase 2 - vendor 隔离与一致性收敛（T13-T17）

- T13：将 ragflow 搬运代码隔离到 `third_party/`（或 `app/third_party/`），业务层通过 adapter 访问。
- T14：格式化/规范策略：
  - vendor：尽量小改动，保留上游 diff 可追踪
  - app：严格执行企业级规范
- T15：解析/切分链路的 optional-dep 行为统一（错误信息、安装提示、降级信号）。
- T16：补开发者文档：“如何安全引入可选依赖/如何写降级逻辑”。
- T17：对所有依赖降级点补充结构化日志，便于运维面板统计与排障。

### Phase 3 - scripts 命名与仓库治理（T18-T20）

- T18：新增 `scripts/README.md`（每个脚本：用途/参数/退出码/示例/常见故障）。
- T19：脚本命名规范化（如需改名，保留 wrapper；同步更新 Makefile）。
- T20：仓库治理：处理 `a.txt`（删除/迁移/解释用途），补充 housekeeping 规则。

## 6) 每个 PR 的验收清单

- `python3 -m pytest -q` 通过
- `make lint-py` 通过
- 不新增 import 的 broad except
- optional-dep 行为满足：
  - 缺依赖 => 明确报错或明确 degraded（带日志/原因）
  - 功能已启用/已选择 => fail-fast + remediation（怎么装/怎么开）

## 7) 发布/灰度策略

- 小步快跑：每个 PR 1-3 个任务，减少回归风险。
- 行为变化（fail-fast vs degrade）使用配置项控制，默认值以“安全/可观测”为先，并在文档中写清楚。
- release notes 记录依赖与行为变化，避免线上惊喜。
