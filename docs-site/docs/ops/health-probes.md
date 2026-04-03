---
sidebar_label: "健康探针"
sidebar_position: 2
---

# 健康检查与探针

MimirQ 提供三个 HTTP 健康端点，供 Kubernetes 探针和外部监控系统使用。通过分离 liveness、readiness 和 startup 语义，平台可实现零停机滚动更新和自动故障恢复。

## 健康端点

### GET /health

综合健康检查，返回服务状态及所有依赖项检测结果。

```json
{
  "status": "healthy",
  "version": "1.4.0",
  "uptime": 86420,
  "checks": {
    "postgresql": "ok",
    "milvus": "ok",
    "redis": "ok",
    "minio": "ok"
  }
}
```

### GET /health/live

轻量级存活检查，仅验证进程是否正常运行，不检查外部依赖。

```json
{ "status": "alive" }
```

### GET /health/ready

就绪检查，验证服务是否可以接收流量（所有依赖连接正常、模型加载完毕）。

```json
{ "status": "ready", "checks": { "postgresql": "ok", "milvus": "ok", "redis": "ok" } }
```

## 返回字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `healthy` / `degraded` / `unhealthy` / `alive` / `ready` |
| `version` | string | 当前部署版本号 |
| `uptime` | number | 进程运行秒数 |
| `checks` | object | 各依赖服务状态，值为 `ok` 或错误描述 |

:::tip
当任一依赖检查失败时，`/health` 返回 `degraded` 状态和 HTTP 503，但 `/health/live` 仍返回 200。
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
              path: /health/live
              port: 8000
            periodSeconds: 15
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8000
            periodSeconds: 10
            failureThreshold: 2
```

## 探针类型对比

| 探针 | 用途 | 失败后果 | 推荐 `periodSeconds` |
|------|------|----------|---------------------|
| **startupProbe** | 等待应用完成初始化（模型加载等） | 超时后杀死 Pod 重建 | 5 |
| **livenessProbe** | 检测进程死锁或僵死 | Pod 被重启 | 15 |
| **readinessProbe** | 判断是否可接收流量 | 从 Service 摘除，不再分配请求 | 10 |

:::warning
`livenessProbe` 不应检查外部依赖。如果 PostgreSQL 短暂不可用导致 liveness 失败，Pod 会被无意义地重启，加剧雪崩。始终使用 `/health/live` 而非 `/health`。
:::

## 依赖服务健康检查

`/health` 和 `/health/ready` 会逐一探测以下依赖：

| 依赖 | 检测方式 | 超时 |
|------|----------|------|
| PostgreSQL | `SELECT 1` 连接测试 | 3s |
| Milvus | gRPC `has_collection` 调用 | 5s |
| Redis | `PING` 命令 | 2s |
| MinIO | `bucket_exists` 检查 | 3s |

## 手动测试

```bash
# 综合检查
curl -s http://localhost:8000/health | jq .

# 存活检查
curl -sf http://localhost:8000/health/live && echo "ALIVE" || echo "DEAD"

# 就绪检查（常用于部署后验证）
curl -w "\nHTTP %{http_code}\n" http://localhost:8000/health/ready
```

:::info
生产环境建议配合 `/health` 端点设置外部拨测（如 UptimeRobot、Blackbox Exporter），告警阈值 ≤ 30s。
:::

---

**相关链接**

- [可观测性](./observability.md) — Prometheus 指标与告警规则
- [部署指南](./deployment.md) — K8s Helm Chart 与 Docker Compose 配置
