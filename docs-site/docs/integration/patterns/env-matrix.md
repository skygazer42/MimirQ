---
sidebar_label: "环境变量导读"
sidebar_position: 8
---

# 环境矩阵

MimirQ 的多环境（dev / staging / prod）部署涉及不同的配置策略，本页说明关键配置差异与注意事项。

## 环境对比

| 配置项 | Development | Staging | Production |
|--------|-------------|---------|------------|
| 认证模式 | Header 调试 + JWT | JWT | JWT（强制） |
| 日志级别 | DEBUG | INFO | WARNING |
| CORS | 宽松（`*`） | 限定域名 | 限定域名 |
| 限流 | 关闭或宽松 | 与生产一致 | 严格 |
| SSL/TLS | 可选 | 启用 | 强制 |
| 健康探针 | 手动检查 | K8s 集成 | K8s 集成 + 外部监控 |

## 后端关键环境变量

:::info
完整配置清单以部署文档与 `.env.example` 为准。以下仅列出联调中最常遇到的变量。
:::

| 变量 | 说明 | 典型值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://...` |
| `REDIS_URL` | Redis 连接地址 | `redis://...` |
| `MILVUS_HOST` / `MILVUS_PORT` | 向量数据库地址 | `localhost:19530` |
| `JWT_SECRET_KEY` | JWT 签名密钥 | 随机字符串 |
| `EMBEDDING_MODEL` | 默认 embedding 模型 | `BAAI/bge-m3` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

:::danger 密钥管理
生产环境中，`JWT_SECRET_KEY`、数据库密码等敏感信息**不应写在 `.env` 文件中**，应使用 Secret Manager 或 K8s Secrets 管理。
:::

## 前端环境变量

| 变量 | 说明 | 注意事项 |
|------|------|----------|
| `NEXT_PUBLIC_API_BASE_URL` | 后端 API 地址 | 修改后需重新构建 |
| `NEXT_PUBLIC_*` | 其他公开配置 | 会暴露到客户端 |

:::warning
`NEXT_PUBLIC_` 前缀的变量会被打包到客户端 JS 中，**不要放置敏感信息**。修改后需要重新构建前端。
:::

## 联调常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| CORS 错误 | 前端与后端 origin 不一致 | 检查后端 CORS 配置与前端 base URL |
| API 请求到错误端口 | 环境变量未更新 | 确认 `NEXT_PUBLIC_API_BASE_URL` |
| SSL 证书错误 | 自签名证书在 staging | 配置证书信任或使用 HTTP |
| 配置不生效 | 缓存或未重启 | 清除缓存、重启服务/重新构建前端 |

## 环境切换检查清单

切换环境时确认：

- [ ] `NEXT_PUBLIC_API_BASE_URL` 指向正确的后端地址
- [ ] 认证方式与目标环境一致（dev 可用 Header，prod 必须 JWT）
- [ ] CORS 配置允许当前前端域名
- [ ] 数据库与向量库连接指向正确的实例

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [认证模式](./auth-modes.md) | [租户 Header](./tenant-headers.md)
- [运维 / SRE 角色](../roles/sre-ops.md)
