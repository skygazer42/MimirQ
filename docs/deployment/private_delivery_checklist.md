# Private Delivery Checklist（MimirQ）

本清单用于企业私有化交付验收与上线前自检。目标：**可部署、可升级、可回滚、可审计、可合规、可评估**。

> 原则：默认 **PII-safe**。除非明确需要并具备权限，避免在公共日志/trace/导出中写入用户 query、文档原文、真实标识符或过滤器明文。

---

## 1) 基础部署

- [ ] **Docker/Helm**：使用 `docs/deployment/helm.md` 完成 Helm 安装与 values 参数化
- [ ] **多副本策略**：API 与 Worker 分离部署；支持水平扩缩
- [ ] **Readiness**：K8s readiness 使用 `GET /api/v1/health/ready`
- [ ] **反向代理**：Ingress/Nginx 配置超时与上传大小（大文件 ingestion）
- [ ] **静态资源**：前端构建产物可缓存；API 响应 `Cache-Control` 合理设置

---

## 2) 身份认证与权限（必须）

- [ ] **禁用不安全模式**：生产必须 `AUTH_MODE=jwt`（禁止 header 模式）
- [ ] **JWT 校验**：
  - [ ] 选择 JWKS URL 或 OIDC discovery（`JWT_JWKS_DISCOVERY_ENABLED=true`）
  - [ ] 设置 `JWT_ISSUER` / `JWT_AUDIENCE`（如适用）
  - [ ] **租户来源（启动强制）**：配置 `JWT_TENANT_CLAIM`（推荐，租户取自已验签的 token claim）；或确认可信网关会剥离并重新注入租户头后，显式设 `TENANT_HEADER_TRUSTED=true`。两者均未配置时生产环境拒绝启动（防止伪造 `X-Tenant-ID` 跨租户读取团队共享资源）
  - [ ] 可选：`JWT_ENFORCE_TENANT_HEADER_MATCH=true` 防跨租户 header spoofing
- [ ] **Tenant Groups（组目录，推荐企业必须）**：
  - [ ] 组管理 API 可用：`GET/POST /api/v1/groups`、`GET /api/v1/groups/{id}`、`GET/POST /api/v1/groups/{id}/members`
  - [ ] 权限收敛：仅具备 settings 权限的账号可管理 groups/memberships（避免越权加组）
  - [ ] 组 provisioning 策略明确（两选一或组合）：
    - [ ] **手工/半自动**：通过 UI / API 创建组、维护成员（最稳妥，便于灰度）
    - [ ] **IdP 同步**（可选）：从 JWT groups claim best-effort 同步（见下一项）
- [ ] **OIDC/JWT groups claim 同步（可选，默认关闭）**：
  - [ ] 已完成安全前置：签名校验 + `JWT_ISSUER`/`JWT_AUDIENCE` 约束（信任边界明确）
  - [ ] 已启用 tenant 绑定：`JWT_TENANT_CLAIM=...`（建议同时 `JWT_ENFORCE_TENANT_HEADER_MATCH=true`）
  - [ ] 安全默认值（建议起步）：
    - [ ] `JWT_GROUPS_SYNC_ENABLED=true`（仅在预发/灰度阶段打开）
    - [ ] `JWT_GROUPS_CLAIM=groups`（或 `realm_access.roles` 等）
    - [ ] `JWT_GROUPS_MAX_GROUPS=200`（防过大 groups 列表放大写入/基数）
    - [ ] `JWT_GROUPS_SYNC_TTL_SEC=60`（降低写放大；逐步调优）
  - [ ] 明确限制：当前实现 **add-only**（只补齐，不做删除）；撤权/离职需要额外流程（见 access review）
  - [ ] 配置与 IdP 示例文档：`docs/guides/oidc_groups_claim.md`
- [ ] **RBAC**：owner/admin/auditor/viewer 角色在关键 API 端点生效（settings/observability/audit/lifecycle）
- [ ] **审计日志**：
  - [ ] 能记录敏感操作：数据删除、purge、导出、治理策略变更、连接器运行等
  - [ ] 提供 NDJSON 导出：`GET /api/v1/audit/logs/export`（SIEM 友好）
- [ ] **权限访问图谱导出（合规）**：
  - [ ] 可导出 groups + ACL allowlists 的 NDJSON/JSON 分页快照：`GET /api/v1/audit/access-graph/export`
  - [ ] 可获取 PII-minimal 的计数汇总（access review 快速体检）：`GET /api/v1/audit/access-graph/summary`
- [ ] **Access Review（访问复核，强烈建议）**：
  - [ ] 定义复核节奏：例如每月/每季度一次（按数据敏感等级分层）
  - [ ] 复核内容至少包含：
    - [ ] tenant groups 列表与成员关系（`/api/v1/groups` + `/members`）
    - [ ] dataset/document allowlists（`partial_member_list` / `partial_group_list`）
    - [ ] 关键变更审计：group/ACL 变更审计日志 NDJSON 导出留痕
  - [ ] 撤权流程明确：当 IdP 组变更不能自动删除时，必须有“手工移除成员/禁用账号/回收 token”的兜底

> 推荐 rollout（从安全到可用的最短路径）：
> 1) 先用手工 groups + allowlist 跑通权限语义（小租户/小数据集验证）
> 2) 再在预发开启 JWT groups 同步，观察审计与指标（确认没有跨租户写入/异常基数）
> 3) 最后在生产灰度开启，同步 TTL/上限保守起步，配套 access review 与撤权兜底

---

## 3) 数据与存储（必须）

- [ ] **Postgres**：连接池与备份策略明确（RPO/RTO）
- [ ] **Redis**：用于 task queue / 缓存（如启用）；设置合理的超时与容量
- [ ] **向量库**：Milvus/Chroma 连接与健康检查通过；容量规划明确
- [ ] **对象存储（可选）**：MinIO/S3 配置与权限正确（上传/下载/删除）
- [ ] **数据生命周期**：
  - [ ] Dataset 文档清单导出（默认脱敏）：`GET /api/v1/datasets/{dataset_id}/documents/export`
  - [ ] Dataset bundle ZIP 导出：`GET /api/v1/datasets/{dataset_id}/export`
  - [ ] Dataset purge（bounded，默认 dry-run）：`POST /api/v1/datasets/{dataset_id}/purge`
  - [ ] 审计日志 purge（bounded，默认 dry-run）：`POST /api/v1/audit/logs/purge`

---

## 4) 合规与治理（建议）

- [ ] **治理规则包**：存在默认安全基线（regex/PII/secret/license）且可审计
- [ ] **Ingestion policy**：可导出/导入，便于跨环境迁移
- [ ] **FLS（字段级安全）**：敏感字段默认不出现在对外可见输出（除非有权限）

---

## 5) 可观测与运维（必须）

- [ ] **Runbook**：按 `docs/deployment/runbook.md` 可定位 ingest/index/retrieval/rerank/LLM 问题
- [ ] **指标与追踪**：
  - [ ] retrieval_config_hash 可用于跨版本对比（PII-safe）
  - [ ] 关键链路（retrieve → rerank → citations）可 replay/导出
- [ ] **告警**：依赖不可用、索引一致性问题、quota/rate-limit 频繁触发等

---

## 6) 质量闭环（强烈建议）

- [ ] **回归套件**：Evidence/RegressionCase 可持续积累（HITL gating）
- [ ] **Gate**：预发/CI 有统一阈值（Hit/MRR/NDCG 等），失败能产出 diff 报告
- [ ] **回放**：线上 trace 可 PII-safe capture 并离线复现

---

## 7) 安全基线（必须）

- [ ] **Helm/K8s 安全开关（推荐）**：
  - [ ] `security.hardened=true`（opt-in 安全上下文默认值）
  - [ ] `automountServiceAccountToken=false`（默认即为 false，除非明确需要）
  - [ ] 可选：`serviceAccount.create=true`（或 `serviceAccount.name=...`）
  - [ ] 可选：`networkPolicy.enabled=true`（先在预发演练；如开启 egress allowlist：`networkPolicy.egress.restrict=true`）
  - [ ] 可选：`security.tmpEmptyDir.enabled=true`（配合 readOnlyRootFilesystem 或需要可写 /tmp）
  - [ ] PVC 权限：必要时设置 `security.podSecurityContext.fsGroup`（避免 non-root 写入失败）
- [ ] **密钥管理**：SECRET_KEY 不使用默认值；支持轮换（fallback keys）
- [ ] **CORS/Hosts**：生产环境限制 `ALLOWED_HOSTS` 与 CORS 来源
- [ ] **限流与配额**：启用 request rate limit（必要时 Redis）；启用 chat token quota（按租户）
- [ ] **最小权限**：数据库账号、对象存储账号、向量库账号权限最小化

---

## 8) 升级/回滚与备份（必须）

- [ ] **迁移**：数据库迁移可回滚策略明确（至少有备份与演练）
- [ ] **回滚**：配置变更与检索策略可通过指纹/版本化回退
- [ ] **备份演练**：至少完成一次 DB + 对象存储恢复演练并记录
