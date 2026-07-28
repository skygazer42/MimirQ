---
sidebar_label: "环境变量导读"
sidebar_position: 8
---

# 环境矩阵

MimirQ 的配置主要分成三类：本地开发、Docker 一键启动、生产部署。权威变量定义见 [设置 / Meta](../../ops/settings-meta.md)。

## 环境对比

| 场景 | 前端 | 后端 | 说明 |
|---|---|---|---|
| 开发机主机启动 | `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` | `make init` 后填写 `LLM_API_KEY` | `make setup-host` + `make backend` / `make web`；仅启用任务队列时运行 `make worker` |
| Docker 一键启动 | `NEXT_PUBLIC_API_URL_DOCKER=/`、`API_INTERNAL_URL_DOCKER=http://mimirq-api:8000` | `make init` 后填写 `LLM_API_KEY` | 适合 `make up-web`；本地基础设施可保留默认值 |
| 生产部署 | 按实际域名设置浏览器地址 | 强 JWT/数据库/对象存储凭据、可信租户来源和受限 CORS/Hosts | 敏感值应通过 Secret / `_FILE` 注入 |

## 最小必填清单

1. 运行 `make init`，让工具生成缺失配置与本地 `SECRET_KEY`。
2. 填写 `LLM_API_KEY`，完成默认硅基流动 LLM 与 Embedding 的真实调用。
3. 需要重排时设置 `ENABLE_RERANKER=true`；独立服务必须填写完整 `RERANKER_API_BASE`。
4. 需要无人值守首登时，再配置 `INITIAL_ADMIN_EMAIL` / `INITIAL_ADMIN_USERNAME` 和一种密码来源。

Embedding 默认复用 LLM 的 Key/Base URL。Reranker 默认关闭；启用后 Key 可复用 LLM，但请求地址必须是供应商的完整 rerank 端点。

## 前端变量

| 变量 | 说明 | 注意事项 |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | 主机模式前端访问后端的地址 | 修改后需要重新构建前端 |
| `NEXT_PUBLIC_API_URL_DOCKER` | Docker 浏览器侧使用的 API 地址 | 默认同源 `/`，不要写成容器内主机名 |
| `API_INTERNAL_URL_DOCKER` | Docker SSR 访问后端的地址 | 只给前端容器内部用 |
| `FORWARDED_ALLOW_IPS_DOCKER` | 可信代理来源 | 不要设成 `*` |

## 常见问题

| 问题 | 原因 | 解决方式 |
|---|---|---|
| 前端请求 404 / CORS | API 地址填错 | 检查 `NEXT_PUBLIC_API_URL` 或 `NEXT_PUBLIC_API_URL_DOCKER` |
| Docker 里看不到后端 | 把浏览器地址写成了容器名 | 改回同源 `/`，SSR 再用 `API_INTERNAL_URL_DOCKER` |
| 首次管理员没生效 | 已有成员或 bootstrap 变量不一致 | 清理 `INITIAL_ADMIN_*` 并确保所有实例一致 |

## 相关链接

- [快速入门](../../ops/getting-started.md)
- [部署指南](../../ops/deployment.md)
- [设置 / Meta](../../ops/settings-meta.md)
