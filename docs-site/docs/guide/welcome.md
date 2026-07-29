---
sidebar_label: "完整操作指南"
sidebar_position: 1
---

# MimirQ 完整操作指南

这是一条面向实际使用者的端到端路径：部署并登录、建立数据集、上传解析、切块索引、检索测试、带引用问答、评测回归和生产运维。模块实现与 API 字段不在这里展开，需要时沿链接进入专项文档。

```mermaid
flowchart LR
  A[启动与登录] --> B[数据集]
  B --> C[入库]
  C --> D[解析与治理]
  D --> E[切块与索引]
  E --> F[检索测试]
  F --> G[带引用问答]
  G --> H[评测与反馈]
```

## 1. 启动与首次登录

### Docker 一键启动

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
# 编辑 .env，真实模型调用至少填写 LLM_API_KEY
make up-web
make ps
make api-ping
```

打开 `http://localhost:3000`。默认栈运行 Web、API、Worker、PostgreSQL、Milvus、Etcd、MinIO 和 Redis 共 8 个容器。

:::info 首个 owner
已配置 `INITIAL_ADMIN_*` 时直接登录；全新空库也可在页面注册第一个 owner。若页面提示首次初始化已关闭，说明数据库已有租户或 owner，不要直接删除生产数据。完整规则见[快速开始](../ops/getting-started)。
:::

源码开发使用 `make setup-host`，再分别运行 `make backend` 和 `make web`。模型地址、Windows 和独立 Worker 见[部署指南](../ops/deployment)。

## 2. 跑通第一个知识库

### Step 1：创建数据集

1. 打开 `/datasets`。
2. 点击“新建数据集”。
3. 填写名称和说明。
4. 选择访问范围并保存。

数据集是权限、索引、检索范围与评测的边界。敏感资料使用 `only_me` 或 `partial_members`，不要全部放入默认公开范围。

![创建并选择数据集](/screenshots/guide-create-dataset.png)

创建后先在数据集页面检查权限范围、文档数与 Chunk 数。

### Step 2：上传并建立索引

1. 打开 `/knowledge/ingestion?datasetId=<dataset_id>`。
2. 在“执行阶段”选择“解析 + 索引”。
3. 拖入一份包含唯一测试短语的小文件。
4. 点击“解析并建索引”。
5. 等待状态从 `pending`、`processing` 进入 `completed`。

![上传文档并建立索引](/screenshots/guide-ingestion.png)

入库工作台统一选择数据集、数据源和执行阶段，并显示任务进度与失败状态。

如果进入 `failed`，查看失败详情；进入 `quarantined`，到 `/knowledge/quarantine` 审核。文档长期不结束时使用[文档卡住排障](../integration/tasks/document-stuck)。

### Step 3：检查解析与 Chunk

| 入口 | 检查内容 |
|:---|:---|
| `/parsing` | 解析任务、解析器和结果 |
| `/knowledge` | 文档、状态、元数据和 Chunk |
| `/chunk-preview` | 标题、段落、表格和父子块边界 |

Chunk Preview 用于试验策略，正式资产仍从入库页面进入目标数据集。默认 DeepDoc 不需要额外容器；复杂 PDF 可按文档类型启用 Marker、MinerU、PaddleOCR-VL 等解析器。

### Step 4：做检索测试

1. 打开 `/knowledge` 并选择数据集。
2. 切换到“检索测试”。
3. 输入文件中的唯一短语或已知答案问题。
4. 检查命中 Chunk、来源、分数、通道和 Trace。

![检索测试与命中证据](/screenshots/guide-retrieval-test.png)

候选排序与命中细节应能说明召回来源、重排分数和所用证据。

没有命中时先检查文档状态、Chunk、索引、数据集范围和 ACL；不要先改 Prompt。

### Step 5：做带引用问答

1. 回到首页 `/`。
2. 点击“选择数据集”。
3. 选择刚创建的数据集并提问。
4. 展开“来源与证据”。
5. 确认引用指向正确文件和支撑原文。

![回答中的来源与证据](/screenshots/guide-source-evidence.png)

生成答案必须能回到具体文件、页码与证据片段。

完整闭环的验收标准：文档 `completed`、检索命中正确证据、答案与证据一致、引用可定位。API 方式见[上传后对话](../integration/scenarios/s01-upload-chat)和[知识库问答验收](../integration/tasks/knowledge-base-qa)。

## 3. 日常知识库运营

| 工作 | Web 入口 | 操作原则 |
|:---|:---|:---|
| 数据集与权限 | `/datasets` | 按部门、保密范围或 Embedding runtime 拆分 |
| 文档与批量操作 | `/knowledge` | 先查看失败原因，再重试或重处理 |
| 文件与 Connector 入库 | `/knowledge/ingestion` | 长期同步优先 Connector |
| 解析检查 | `/parsing` | 解析器变化后重解析 |
| 数据治理 | `/data-governance` | 先预览规则命中，再应用 |
| 治理画像 | `/data-governance/profiles` | 把清洗规则做成可版本化模板 |
| 隔离审核 | `/knowledge/quarantine` | 人工确认后放行或拒绝 |
| 切块调试 | `/chunk-preview` | 用真实样本比较策略 |

更换 Embedding 模型、供应商或向量维度后必须重建索引，不能把不同 embedding space 混入同一索引。

## 4. 检索、问答和 Dify

MimirQ 把“找到证据”和“生成答案”分开验收：

- “检索测试”判断召回与重排是否正确。
- 首页问答判断 LLM 是否基于证据作答。
- 检索正确但答案错误时，检查 Prompt、上下文裁剪和 LLM，而不是为单题增加业务特判。

Dify 支持两种接入：

- **External Knowledge API**：`POST /api/v1/integrations/dify/retrieval`。
- **Workflow HTTP 节点**：Dify 传查询、数据集范围和过滤参数，MimirQ 返回证据和 Trace。

Dify 负责编排和生成，MimirQ 继续负责知识治理、检索、重排、权限过滤与证据。请求字段与调用顺序以 [OpenAPI](https://skygazer42.github.io/MimirQ/) 为准。

## 5. 评测与持续改进

打开 `/evaluations`：

1. 录入问题、期望答案和期望引用，或从文档/对话生成候选题。
2. 人工审核后形成 Golden 题集。
3. 固定数据、模型和检索配置，运行首个基线。
4. 每次修改解析、切块、Embedding、重排或 Prompt 后重跑。
5. 比较完成率、准确/部分准确/证据不足、证据覆盖和 P95。

线上反馈在 `/knowledge/feedback` 处理，证据在 `/knowledge/evidence` 核对，报告从 `/reports` 导出。确认过的 hardcase 应回写 Golden 题集。

可选 KG 在 `/datasets/{dataset_id}/kg` 或 `/graph` 使用。KG 是增强通道，不替代基础检索。

## 6. 权限与管理员操作

| 入口 | 用途 |
|:---|:---|
| `/settings/rbac` | 成员、角色与权限 |
| `/settings/groups` | 用户组和组成员 |
| `/settings` | 租户与功能配置 |
| `/audit` | 审计事件 |
| `/usage` | 调用与用量 |

数据集权限支持 `all_team_members`、`only_me` 和 `partial_members`，文档还可叠加 ACL。生产环境应使用正式 JWT、OIDC 或 SAML，不能把 Header 调试模式暴露到公网。

## 7. 启停、备份和升级

| 目的 | 命令 | 数据卷 | 镜像 |
|:---|:---|:---:|:---:|
| 查看状态 | `make ps` | 保留 | 保留 |
| 查看日志 | `make logs` | 保留 | 保留 |
| 停止 | `make down` | 保留 | 保留 |
| 清空数据 | `make docker-reset` | 删除 | 保留 |
| 删除数据和镜像 | `make docker-purge` | 删除 | 删除 |

后两项不可恢复，执行前必须完成备份与恢复演练。MimirQ 使用独立项目名 `mimirq`；Windows PowerShell、Dify 共存和旧版恢复见[部署指南](../ops/deployment)。不要运行全局 `docker system prune` 来替代项目级清理。

## 8. 排障顺序

| 现象 | 首先检查 |
|:---|:---|
| 页面打不开 | Docker、`make ps`、Web/API 日志 |
| 管理员无法注册 | 是否已有 owner，`INITIAL_ADMIN_*` 是否一致 |
| 文档卡住 | Worker、Redis、解析器和失败详情 |
| completed 但检索为空 | Chunk、索引、数据集范围、ACL、Embedding runtime |
| 检索正确但回答错误 | Prompt、上下文裁剪、LLM 和引用 |
| 403 | 租户、角色、数据集权限和文档 ACL |
| 延迟高 | Trace 阶段耗时、模型服务、Milvus 和 admission |
| 清理输出出现 Dify | 立即停止，不运行 prune，按部署恢复流程处理 |

记录页面返回的 `request_id`，用同一标识关联 API、Worker、模型服务和代理日志。更多入口见[健康检查](../ops/health-probes)与[可观测性](../ops/observability)。

## 9. 上线前检查

- [ ] 真实 LLM、Embedding、Reranker 已调用成功，不只看 readiness。
- [ ] 至少一份真实样本文档完成解析、切块、索引、检索和带引用问答。
- [ ] 正式认证、RBAC、数据集权限和文档 ACL 已验证。
- [ ] Golden 题集和回归阈值已保存。
- [ ] API、Worker 和全部数据依赖有监控与告警。
- [ ] 备份已实际恢复，并重新验证检索和引用。
- [ ] 升级、数据库迁移、回滚和并发已在预发验证。

仓库内更详细、可离线阅读的版本见 [MimirQ 全流程操作指南](https://github.com/skygazer42/MimirQ/blob/main/docs/user_guide.md)。
