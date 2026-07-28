---
sidebar_label: "健康探针"
sidebar_position: 3
---

# 健康检查与探针

MimirQ 提供两个公开探针和一个管理员明细端点。完整路由统一带 `/api/v1` 前缀。

| 端点 | 鉴权 | 用途 |
|:---|:---|:---|
| `GET /api/v1/health` | 无 | 轻量 liveness，只确认 API 进程可响应 |
| `GET /api/v1/health/ready` | 无 | readiness，检查必需运行依赖并返回 200/503 |
| `GET /api/v1/health/details` | 需要管理员权限 | 查看数据库、向量库、Redis、对象存储、Worker 等详细状态 |

## Liveness

```http
GET /api/v1/health
```

```json
{
  "ok": true,
  "status": "ok"
}
```

该端点不访问外部依赖，适合作为 `livenessProbe`。PostgreSQL 或 Milvus 短暂抖动时，不应因此重启 API Pod。

## Readiness

```http
GET /api/v1/health/ready
```

依赖可用时返回 HTTP 200：

```json
{
  "ok": true,
  "status": "ready"
}
```

任一必需依赖不可用时返回 HTTP 503：

```json
{
  "ok": false,
  "status": "unready"
}
```

公开 readiness 故意不暴露具体依赖错误，适合作为 `readinessProbe` 与 `startupProbe`。它会检查数据库、当前向量后端、Redis、启用的对象存储，以及被配置为 readiness 必需的运行时预热。

:::note 模型服务不在默认 readiness 中
LLM、Embedding 与 Reranker 的外部调用不由该公开探针证明。部署验收仍需上传小文档并完成一次真实检索或问答。
:::

## 管理员明细

`GET /api/v1/health/details` 需要已认证账号和租户可观测性权限。它会返回数据库、向量后端、Milvus、Redis、MinIO/对象存储、RAG 预热、任务队列与上传目录等明细。不要把该端点直接配置成无需鉴权的 Kubernetes 探针，也不要向未授权用户暴露依赖错误。

## Kubernetes 配置

```yaml
containers:
  - name: api
    ports:
      - containerPort: 8000
    startupProbe:
      httpGet:
        path: /api/v1/health/ready
        port: 8000
      periodSeconds: 5
      failureThreshold: 30
    livenessProbe:
      httpGet:
        path: /api/v1/health
        port: 8000
      periodSeconds: 15
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /api/v1/health/ready
        port: 8000
      periodSeconds: 10
      failureThreshold: 2
```

仓库 Helm Chart 已使用这些完整路径，通常无需手写探针。

## 手动验证

```bash
curl -f http://localhost:8000/api/v1/health
curl -f http://localhost:8000/api/v1/health/ready
```

如需依赖明细，应通过正常登录获得 JWT，并在所属租户上下文中请求 `/api/v1/health/details`。

相关页面：[快速开始](./getting-started) · [部署指南](./deployment) · [可观测性](./observability)
