# Security Baseline（MimirQ / Kubernetes）

本页是面向平台/运维团队的 **K8s 安全基线落地指南**，目标是让 MimirQ 的私有化部署：

- 官方镜像默认启用 **安全上下文**（非 root、drop capabilities、seccomp）
- 自定义镜像不兼容时可显式关闭 hardening
- 关键配置 **可审计、可复用、可 copy/paste**

> 原则：默认 PII-safe。不要为了安全审计在日志/导出里写入用户 query / 文档原文。

---

## 1) Helm 关键开关速查

Chart：`deploy/helm/mimirq`

### 1.1 安全上下文（securityContext）

hardening 预设默认启用：

```yaml
security:
  hardened: true
```

仅当自定义镜像无法满足非 root、seccomp 或 capabilities 约束时，才显式设置为 `false`。

你仍然可以显式覆盖：

- 全局：`security.podSecurityContext` / `security.containerSecurityContext`
- 组件级：`api.podSecurityContext` / `api.securityContext`（worker/cronjobs 同理）

> 注意：chart **不会默认开启** `readOnlyRootFilesystem`，因为某些可选本地后端（如 Chroma/FAISS）可能需要写入容器文件系统。若你要开启，请先验证写路径并配合可写 volume（见 1.3）。

### 1.2 ServiceAccount token（建议默认不挂载）

默认值为：

```yaml
automountServiceAccountToken: false
```

除非你的部署明确需要 in-cluster K8s API（通常不需要），否则建议保持关闭，减少 token 暴露面。

如确有需求，可按组件开启：

```yaml
api:
  automountServiceAccountToken: true
```

### 1.3 /tmp 可写目录（emptyDir）

当你启用 `readOnlyRootFilesystem` 或运行时需要稳定可写的 temp 目录时：

```yaml
security:
  tmpEmptyDir:
    enabled: true
    mountPath: /tmp
    sizeLimit: ""
```

---

## 2) PVC 权限（fsGroup）常见坑

镜像默认以 non-root 用户运行。某些集群的 PVC 默认权限可能导致 `/data/uploads` 不可写。

推荐做法：设置 pod-level `fsGroup`（值按你的镜像用户/组策略调整）：

```yaml
security:
  podSecurityContext:
    fsGroup: 1000
    fsGroupChangePolicy: "OnRootMismatch"
```

---

## 3) NetworkPolicy（可选）

### 3.1 总体策略（chart 的默认行为）

当 `networkPolicy.enabled=true` 时：

- `api`：默认允许 **同 namespace** 的 ingress（TCP 8000）
- `worker`：默认拒绝 ingress
- `egress`：默认仍是 allow-all（不创建 egress policy）

配置入口：

```yaml
networkPolicy:
  enabled: true
```

### 3.2 API ingress：Ingress Controller 不在同 namespace 怎么办？

如果你的 Ingress Controller 在 `ingress-nginx` namespace（常见），你需要把它加入 allowlist（示例需要按你集群 label 调整）：

```yaml
networkPolicy:
  enabled: true
  api:
    ingress:
      allowSameNamespace: false
      extraFrom:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
```

你也可以叠加 `podSelector`，进一步收敛来源。

### 3.3 Egress allowlist（强约束，务必谨慎）

只有当你非常确定依赖边界，才建议开启：

```yaml
networkPolicy:
  enabled: true
  egress:
    restrict: true
    allowDNS: true
    rules:
      # Postgres（示例：同集群内网段 + 5432）
      - to:
          - ipBlock:
              cidr: "10.0.0.0/8"
        ports:
          - protocol: TCP
            port: 5432

      # Redis（示例：6379）
      - to:
          - ipBlock:
              cidr: "10.0.0.0/8"
        ports:
          - protocol: TCP
            port: 6379

      # Milvus（示例：19530）
      - to:
          - ipBlock:
              cidr: "10.0.0.0/8"
        ports:
          - protocol: TCP
            port: 19530
```

重要说明：

- `restrict=true` 会影响 **所有 chart 创建的 pods**（api/worker/cronjobs）。请确保定时任务同样能访问依赖。
- 如果你启用了外部 LLM（如 OpenAI / Azure OpenAI / 自建网关），你需要把对应 egress 放行（常见是 443/TCP 到公网或企业网关）。
- URL/连接器类能力也可能需要额外 egress；建议先在预发环境演练。

---

## 4) Helm 渲染自检（推荐）

在上线前先做一次模板渲染检查：

```bash
make helm-template
make helm-lint
```

---

## 5) 审计证据（交付时常用）

交付/安全评审常见会问“你们开了什么安全开关”，建议准备以下输出：

```bash
helm get values mimirq -n <ns>
kubectl -n <ns> get deploy,cronjob,networkpolicy,sa -l app.kubernetes.io/instance=mimirq
```
