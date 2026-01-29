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

## 3) 目标规范（落地后的“约束”）

### 3.1 Import 规范（强制）

- 内部模块（`app.*`）禁止通过 `try/except` 做降级；应修复根因（循环依赖、初始化时机等）。
- 可选第三方依赖：
  - import 边界只捕获 `ImportError`
  - 统一使用工具函数：
    - `optional_import("pkg", feature="...")`：返回模块/None，并打印结构化告警日志
    - `require_dependency("pkg", feature="...")`：抛 `RuntimeError`，包含安装提示与 remediation
- 禁止 `except Exception` 包裹 import（除非立即 re-raise 并补充上下文，且有明确理由）。

### 3.2 错误处理与可观测性（企业级基线）

- 任何“best-effort/降级”都必须可观测：至少 `warning` 日志，包含：
  - feature、dependency、reason、remediation
- 明确区分：
  - 缺依赖（`ImportError`）
  - 运行时异常（bug/版本不兼容）
  - 输入不合法/格式不支持

### 3.3 脚本命名规范（企业级基线）

- Python：`snake_case.py`，动词优先（`check_*` / `verify_*` / `export_*` / `gen_*` / `benchmark_*` / `doctor_*` / `clean_*`）。
- PowerShell：`snake_case.ps1`，动词优先；dev 启动脚本统一 `dev_*` 前缀。
- 若必须重命名：
  - 至少保留一个版本周期的兼容 wrapper
  - 同步更新 Makefile 目标与脚本文档

## 4) 执行计划（剩余任务）

> 每个任务必须包含：代码变更 + 测试（单测/必要时集成）+ 日志/指标验证。
>
> 说明：已完成项已从本文件移除（如需追溯请查看 git history）。

### Phase 1 - 修 P0（收尾）

- T10：QA 清理：去掉内部 `try import` 降级，必要时通过分层/解耦解决循环依赖。
- T11：PII 脱敏链路：确保“开关开启=实际生效”，禁止静默绕过。

### Phase 2 - vendor 隔离与一致性收敛（T14-T17）

- T14：格式化/规范策略：
  - vendor：尽量小改动，保留上游 diff 可追踪
  - app：严格执行企业级规范
- T15：解析/切分链路的 optional-dep 行为统一（错误信息、安装提示、降级信号）。
- T16：补开发者文档：“如何安全引入可选依赖/如何写降级逻辑”。
- T17：对所有依赖降级点补充结构化日志，便于运维面板统计与排障。

### Phase 3 - scripts 命名与仓库治理（T19）

- T19：脚本命名规范化（如需改名，保留 wrapper；同步更新 Makefile）。

## 5) 每个 PR 的验收清单

- `python3 -m pytest -q` 通过
- `make lint-py` 通过
- 不新增 import 的 broad except
- optional-dep 行为满足：
  - 缺依赖 => 明确报错或明确 degraded（带日志/原因）
  - 功能已启用/已选择 => fail-fast + remediation（怎么装/怎么开）

## 6) 发布/灰度策略

- 小步快跑：每个 PR 1-3 个任务，减少回归风险。
- 行为变化（fail-fast vs degrade）使用配置项控制，默认值以“安全/可观测”为先，并在文档中写清楚。
- release notes 记录依赖与行为变化，避免线上惊喜。
