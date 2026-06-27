---
sidebar_label: "健康探针"
sidebar_position: 2
---

# 健康检查与探针

MimirQ 提供 **两个** HTTP 健康端点，供 Kubernetes 探针和外部监控系统使用：`/health`（轻量存活检查，不触达外部依赖）与 `/health/ready`（就绪检查，逐一探测依赖）。两者配合可实现零停机滚动更新与自动故障恢复。

> 实现位置：`app/api/v1/health.py`（`@router.get("/health")` 与 `@router.get("/health/ready")`）。

## 健康端点

### GET /health

轻量级存活检查，仅确认进程正常运行，**不检查外部依赖**。响应恒为 HTTP 200。

```json
{
  "ok": true,
  "time": "2026-06-23T08:00:00+00:00",
  "vector_backend": "milvus",
  "use_langgraph_pipeline": true
}
```

适合作为 Kubernetes **livenessProbe**：进程活着就返回 200，不会因 PostgreSQL/Redis 短暂抖动而误杀 Pod。

### GET /health/ready

就绪检查，逐一探测所有必需依赖。全部可达返回 HTTP 200，任一不可达返回 HTTP 503。结果有短时缓存以降低探测压力。

```json
{
  "ok": true,
  "database": "ok",
  "vector": "ok",
  "redis": "ok",
  "minio": "ok"
}
```

依赖故障时（HTTP 503）：

```json
{
  "ok": false,
  "database": "ok",
  "vector": "error: connection refused",
  "redis": "ok",
  "minio": "ok"
}
```

适合作为 Kubernetes **readinessProbe** 与 **startupProbe**。

## 返回字段说明

| 端点 | 字段 | 类型 | 说明 |
|------|------|------|------|
| `/health` | `ok` | bool | 进程存活恒为 `true` |
| `/health` | `time` | string | 当前 UTC 时间（ISO 8601） |
| `/health` | `vector_backend` | string | 当前向量后端（`milvus` 等） |
| `/health` | `use_langgraph_pipeline` | bool | 是否启用 LangGraph 管线 |
| `/health/ready` | `ok` | bool | 全部依赖可达为 `true`，否则 `false`（HTTP 503） |
| `/health/ready` | `database` / `vector` / `redis` / `minio` | string | 各依赖状态，`ok` 或错误描述 |

:::tip
依赖故障只影响 `/health/ready`（返回 503），`/health` 始终返回 200。这正是 liveness 与 readiness 分离的目的：依赖抖动时 Pod 应被摘流（readiness 失败）而非被重启（liveness 失败）。
:::

## Kubernetes 探针配置

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mimirq-api
spec:
  template:
    spec:
      containers:
        - name: api
          ports:
            - containerPort: 8000
          startupProbe:
            httpGet:
              path: /health/ready
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 5
            failureThreshold: 30        # 最多等 150s 完成启动
          livenessProbe:
            httpGet:
              path: /health           # 轻量、不检依赖
              port: 8000
            periodSeconds: 15
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health/ready     # 检查依赖，决定是否分配流量
              port: 8000
            periodSeconds: 10
            failureThreshold: 2
```

## 探针类型对比

| 探针 | 用途 | 失败后果 | 推荐端点 | 推荐 `periodSeconds` |
|------|------|----------|----------|---------------------|
| **startupProbe** | 等待应用完成初始化 | 超时后杀死 Pod 重建 | `/health/ready` | 5 |
| **livenessProbe** | 检测进程死锁或僵死 | Pod 被重启 | `/health` | 15 |
| **readinessProbe** | 判断是否可接收流量 | 从 Service 摘除 | `/health/ready` | 10 |

:::warning
`livenessProbe` 不应检查外部依赖。如果 PostgreSQL 短暂不可用导致 liveness 失败，Pod 会被无意义地重启，加剧雪崩。**liveness 用 `/health`（轻量），readiness/startup 用 `/health/ready`（检依赖）。**
:::

## 依赖服务健康检查

`/health/ready` 会逐一探测以下依赖（`/health` 不探测任何依赖）：

| 依赖 | 检测方式 | 备注 |
|------|----------|------|
| PostgreSQL | `check_database()` 连接测试 | 必需 |
| 向量后端 | Milvus `get_collection_count` 等 | 按 `VECTOR_BACKEND` |
| Redis | `check_redis()` PING | 必需 |
| MinIO | `bucket_exists` 检查 | 仅当 `MINIO_ENABLED=true` |

## 手动测试

```bash
# 存活检查（liveness）
curl -sf http://localhost:8000/health && echo " ALIVE" || echo " DEAD"

# 就绪检查（readiness，常用于部署后验证）
curl -w "\nHTTP %{http_code}\n" http://localhost:8000/health/ready
```

:::info
生产环境建议对 `/health/ready` 设置外部拨测（如 UptimeRobot、Blackbox Exporter），告警阈值 ≤ 30s。
:::

---

**相关链接**

- [可观测性](./observability.md) — Prometheus 指标与告警规则
- [部署指南](./deployment.md) — K8s Helm Chart 与 Docker Compose 配置
