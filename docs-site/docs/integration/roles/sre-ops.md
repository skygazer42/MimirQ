---
sidebar_label: "运维 / SRE"
sidebar_position: 3
---

# 运维 / SRE

SRE 负责 MimirQ 平台的可用性、可恢复性与可观测性。故障时需要快速定位问题层级（网关 / 应用 / 依赖 / 数据面），并以业务可用性（能登录、能上传、能问答）作为恢复标准。

## 职责概览

| 职责 | 说明 |
|------|------|
| 部署与升级 | 容器编排、滚动更新、版本回滚 |
| 监控告警 | 健康探针、指标采集、告警规则配置 |
| 故障响应 | 快速定位、止损、恢复、事后复盘 |
| 容量规划 | 依赖组件（Milvus / PostgreSQL / Redis）的资源监控与扩容 |

## 推荐阅读路径

| 阶段 | 目标 | 推荐页面 |
|------|------|----------|
| 1. 部署验证 | 确认服务启动并健康 | 健康检查 API（见下表） |
| 2. 监控接入 | 配置探针与告警 | [可观测性与请求追踪](../patterns/observability-requests.md) |
| 3. 业务止损 | 处理用户可见故障 | [文档卡住排障](../tasks/document-stuck.md) |
| 4. 环境管理 | 多环境配置与差异 | [环境矩阵](../patterns/env-matrix.md) |
| 5. 日常运维 | 备份、审计、容量 | [场景: 用量审计](../scenarios/s11-usage-audit.md) |

## 首日清单

- [ ] **部署验证** — 确认所有服务容器正常运行

```bash
# 存活探针
curl -s "$BASE_URL/api/v1/health" | jq .

# 就绪探针（检查依赖连接）
curl -s "$BASE_URL/api/v1/health/ready" | jq .
```

- [ ] **监控配置** — 将健康探针接入 K8s liveness/readiness 或外部监控
- [ ] **告警规则** — 配置关键指标的告警阈值（API 延迟、错误率、队列深度）
- [ ] **备份策略** — 确认 PostgreSQL 与 Milvus 的备份计划

:::tip K8s 探针配置
- Liveness: `GET /api/v1/health`，间隔 10s，失败阈值 3
- Readiness: `GET /api/v1/health/ready`，间隔 5s，失败阈值 2
:::

## 健康检查 API

| 检查项 | 路径 | 说明 |
|--------|------|------|
| 存活探针 | `GET /api/v1/health` | 应用进程存活 |
| 就绪探针 | `GET /api/v1/health/ready` | 所有依赖连接正常 |
| 系统信息 | `GET /api/v1/meta/info` | 版本、构建信息 |

## 关键依赖与监控维度

| 组件 | 监控重点 | 故障影响 |
|------|----------|----------|
| PostgreSQL | 连接池、慢查询、磁盘 | 全功能不可用 |
| Milvus | 向量索引延迟、内存 | 检索与 RAG 不可用 |
| Redis | 内存、连接数 | 缓存失效、会话异常 |
| 对象存储 | 可用性、延迟 | 文档上传/下载失败 |
| Worker 队列 | 积压深度、消费速率 | 文档处理延迟 |

## 常见故障与定位

| 现象 | 排查方向 |
|------|----------|
| 全站 502/503 | 网关配置 → 应用健康 → 依赖连接 |
| 文档批量卡住 | Worker 状态 → 队列积压 → 解析器依赖 |
| 检索延迟飙升 | Milvus 负载 → embedding 服务 → 并发量 |
| 间歇性 401 | 时钟同步（NTP）→ Token 签发服务 |

## 与其他角色的协作

- **管理员** — 管理员报告业务异常，SRE 定位基础设施问题
- **集成工程师** — 网关、超时、body 限制变更时需同步通知（上传与 SSE 最易受影响）

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [错误码与响应体](../patterns/errors-4xx-5xx.md)
- [SSE 流式](../patterns/sse-streaming.md)（代理缓冲配置）
