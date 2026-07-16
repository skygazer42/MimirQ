# 运维 / CI 工具说明

本文汇总仓库内的“自检 / 验证 / 安全审计 / 回归门禁”脚本，方便本地与 CI 复用。

## 1) 环境自检（doctor）

快速确认本机工具链是否齐全：

```bash
python scripts/doctor.py
```

常见提示：
- Windows 没有 `make`：用 `scripts/*.ps1` 替代（见下文）。
- `git core.autocrlf` 开启会导致 CRLF/LF 抖动：仓库通过 `.gitattributes` 强制 LF，建议关闭自动转换。

## 2) 仓库校验（verify）

### Linux/macOS（有 make）

```bash
make verify
```

### Windows（无 make）

```powershell
powershell -File scripts/verify.ps1
```

常用参数：

```powershell
# 跳过后端测试
powershell -File scripts/verify.ps1 -SkipTests

# 跳过前端检查
powershell -File scripts/verify.ps1 -SkipWeb

# 跳过 Python ruff
powershell -File scripts/verify.ps1 -SkipLintPy

# 额外执行 OpenAPI 导出 + types 生成 + 检查
powershell -File scripts/verify.ps1 -RunOpenApiCheck
```

## 3) 依赖安全审计（audit）

### Linux/macOS（有 make）

```bash
make audit
```

### Windows

```powershell
powershell -File scripts/audit.ps1
```

可选跳过：

```powershell
powershell -File scripts/audit.ps1 -SkipPython
powershell -File scripts/audit.ps1 -SkipWeb
```

## 4) 生成 SECRET_KEY

生产环境建议使用 `AUTH_MODE=jwt` 并设置 `SECRET_KEY`（>= 32 chars）：

```bash
python scripts/gen_secret_key.py
```

初始化 env 文件时可选自动填充（仅对“本次新创建的 env 文件”生效，避免误改已有配置）：

```bash
python scripts/init_env.py --gen-secret-key
```

## 5) OpenAPI 导出 / types

后端导出 OpenAPI：

```bash
python scripts/export_openapi.py --out web/openapi.json
```

前端生成 types：

```bash
pnpm -C web run gen:api-types
```

检查产物是否存在/是否干净：

```bash
python scripts/openapi_check.py
```

## 6) 全接口冒烟（API smoke）

用于快速验证 OpenAPI 覆盖接口可调用（通常对 Docker 后端执行）：

```bash
python scripts/api_smoke.py --base-url http://localhost:8000 --skip-llm-test --skip-mineru
```

## 7) 回归门禁（RAGAS regression gate）

用于在 CI/回归测试中对评测指标做阈值门禁：

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --user-id demo \
  --cases path/to/cases.json \
  --metrics faithfulness,response_relevancy \
  --thresholds path/to/thresholds.json
```

说明：
- `AUTH_MODE=header` 用 `--user-id`；`AUTH_MODE=jwt` 用 `--bearer`。
- `--skip-import` 可以跳过导入（假设用例已在系统中存在）。

## 8) 结构化日志（JSON logs）

后端支持可选的结构化 JSON 日志，便于 ELK / Datadog / Loki 检索与关联：

- 开启方式：设置 `LOG_FORMAT=json`
- 常见字段：
  - `request_id`：请求链路 id（响应头也会返回 `X-Request-ID`）
  - `tenant_id`：租户 id（来自 `TENANT_HEADER`，默认 `X-Tenant-ID`；在 JWT 模式下优先使用 token claim。生产环境要求配置 `JWT_TENANT_CLAIM` 或显式 `TENANT_HEADER_TRUSTED=true`，启动时强制校验）
  - `route`：路由模板（低基数，例如 `/api/v1/rag/retrieve`，用于聚合与检索）
  - `trace_id` / `span_id`：当启用 OpenTelemetry 时自动附带

示例（字段会按实际情况出现/缺省）：

```json
{
  "ts": "2026-03-03T12:00:00+00:00",
  "level": "INFO",
  "logger": "api.rag",
  "msg": "RAG request completed",
  "request_id": "b1a2c3d4",
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "route": "/api/v1/rag/retrieve"
}
```

## 9) 季度 Retrieval Debt Audit

用于持续跟踪“长期但不紧急”的检索质量债务（阈值老化、flaky 信号、profile 风险、TODO 热点）：

```bash
python scripts/generate_retrieval_debt_audit.py --out runs/retrieval_debt_audit.md
```

建议制度化节奏：

- Cadence：每季度至少 1 次（建议季度首月第一周）。
- Owner：检索负责人（主责）+ 当季 oncall（共评）。
- Artifact：产出 `runs/retrieval_debt_audit.md` 并在迭代计划中登记处理项。

模板位置：

- `docs/templates/retrieval_debt_audit_template.md`

## 10) Query-set Health 诊断元数据约定

用于解释“同一 query 集趋势变化”是否来自真实召回退化，还是仅由阈值策略调整导致。

推荐流程：

```bash
python scripts/validate_queryset_health_policy.py --policy ci/queryset_health_policy.v1.json
python scripts/run_queryset_health_diagnostics.py \
  --benchmark-report runs/sample_bench.json \
  --out runs/queryset_health/snapshot.json \
  --history runs/queryset_health/history.jsonl \
  --policy-json ci/queryset_health_policy.v1.json \
  --cron
```

关键字段（snapshot 与 cron 输出都可见）：

- `policy_source`：策略来源（`default` / `policy_json` / `cli_overrides` / `policy_json+cli_overrides`）
- `policy_hash`：归一化策略 JSON 的稳定哈希（用于跨 PR/跨时间对比）
- `trend.policy_changed`：与上一个 snapshot 比较后策略是否变更

解读建议：

- 若 `trend.policy_changed=true`，先判断是否策略改动导致门禁变化，再判断检索质量是否真实退化。
- 若 `trend.policy_changed=false` 且核心指标下降，则优先排查召回/重排链路回归。

## 11) Must-Recall + Provenance 一体化门禁

用于发版前同时验证：

- must-recall 合同通过率
- provenance（evidence capsule）完整性

```bash
python scripts/must_recall_provenance_gate.py \
  --run-json artifacts/run.detail.json \
  --must-recall-min 1.0 \
  --provenance-min 1.0 \
  --out artifacts/must_recall_provenance_gate.report.json
```

输出字段：

- `summary.must_recall_pass_rate`
- `summary.provenance_integrity_rate`
- `passed` / `failures`

## 12) Evidence Capsule 持久化与回放

### 持久化 API

- `POST /api/v1/evidence/capsules`
- `GET /api/v1/evidence/capsules/{capsule_id}`

配置：

- `EVIDENCE_CAPSULE_PERSIST_ENABLED`
- `EVIDENCE_CAPSULE_STORE_DIR`

### 回放工具

```bash
python scripts/replay_from_evidence_capsule.py \
  --capsule runs/evidence_capsules/<capsule_id>.json \
  --out runs/evidence_replay.json
```

用于快速回答“这次回答为什么可追溯 / 现在还能否复现”。
