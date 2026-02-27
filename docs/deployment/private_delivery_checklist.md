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
  - [ ] 配置 `JWT_TENANT_CLAIM`（如启用多租户 claim 绑定）
  - [ ] 可选：`JWT_ENFORCE_TENANT_HEADER_MATCH=true` 防跨租户 header spoofing
- [ ] **RBAC**：owner/admin/auditor/viewer 角色在关键 API 端点生效（settings/observability/audit/lifecycle）
- [ ] **审计日志**：
  - [ ] 能记录敏感操作：数据删除、purge、导出、治理策略变更、连接器运行等
  - [ ] 提供 NDJSON 导出：`GET /api/v1/audit/logs/export`（SIEM 友好）

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

- [ ] **密钥管理**：SECRET_KEY 不使用默认值；支持轮换（fallback keys）
- [ ] **CORS/Hosts**：生产环境限制 `ALLOWED_HOSTS` 与 CORS 来源
- [ ] **限流与配额**：启用 request rate limit（必要时 Redis）；启用 chat token quota（按租户）
- [ ] **最小权限**：数据库账号、对象存储账号、向量库账号权限最小化

---

## 8) 升级/回滚与备份（必须）

- [ ] **迁移**：数据库迁移可回滚策略明确（至少有备份与演练）
- [ ] **回滚**：配置变更与检索策略可通过指纹/版本化回退
- [ ] **备份演练**：至少完成一次 DB + 对象存储恢复演练并记录

