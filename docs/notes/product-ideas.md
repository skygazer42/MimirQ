# Product Ideas (Legacy)

This file was previously tracked as `a.txt` at the repo root and is kept here to reduce repository noise.

---

你这个仓库本身已经有不少“底座”（前端有切片预览/KG/RAGViz/数据治理页；后端有混
合检索、文档级 ACL、URL connector、评测/观测接口等），下面给你按 Dify /
RAGFlow / FastGPT 常见能力对标，列 20 条“可落地”的优化点（你筛选用）：

1. 节点式工作流编排 + 版本化（对标 Dify Workflow / FastGPT Flow）：把“检索→重
   Key；一键生成调用凭证/嵌入脚本
3. Connector 插件体系扩展（对标 RAGFlow/FastGPT）：Notion/Confluence/GitHub/
   Google Drive/飞书文档等；支持增量同步、定时跑、删除同步
4. 网页抓取增强：Sitemap/递归抓取、JS 渲染、登录 Cookie、robots/速率限制；配套
   SSRF allowlist/出网策略
5. 数据集/文档版本与可回滚：基于 doc_hash + pipeline_hash 做增量重算与回滚（避
   免全量重建）
6. 分块策略“模板 + 自动推荐”：按 PDF/MD/Office 给默认参数；结合预览与“检索命中
   率/引用覆盖率”给调参建议
7. 加入 Reranker（对标主流提精度）：cross-encoder / BGE reranker 可选；topk/阈
   值/候选量可配置
8. Query rewrite / multi-query / HyDE（对标 Dify/FastGPT 检索增强）：可开关、
   可观测（命中变化、token 成本）
9. 上下文压缩与去冗：LLM compressor/规则压缩 + chunk 去重合并，显著降 token 成
   本且保留引用
10. 引用更“可解释”（对标 RAGFlow 强项）：sentence-level 引用对齐、高亮、点击跳
    转到原文页/段
11. 多知识库路由：先做意图/领域分类再选 dataset(s)；支持跨库检索融合与权重
    本/延迟/质量策略）
13. 记忆分层（对标 FastGPT）：短期窗口 + 长期摘要/向量记忆；提供“记忆开关/清
    除/可视化”
14. 反馈闭环：点赞/纠错→自动生成评测样本→触发回归评测→看板闭环（产品自进化）
15. 评测体系加强（对标 Dify/RAGFlow）：测试集管理、版本对比、CI gate（PR 自动
16. 质量仪表盘：解析成功率、平均 chunk 数、检索命中率、引用覆盖率、embedding
    cache 命中、失败原因 TopN
17. 任务中心统一化：ingest/KG/重建/评测全部走统一队列；支持进度事件、取消/重
    试、并发限流
18. 成本与配额（企业落地刚需）：按 tenant/dataset 统计 token、向量量、存储、任
    务时长；限额与告警
19. 权限与合规补齐：在现有文档 ACL 上扩展 RBAC（角色/组）、SSO(OIDC/SAML)、审
    计日志、数据导出/删除
20. 前端体验/性能打磨：大列表虚拟化、SSE/WS 流式与断线重连、统一错误提示+可复
    制 traceId、最近会话离线缓存

你先从 20 条里挑 5 条编号发我，我再按你选的点给“落地拆解（改哪些模块/接口/数据
表/页面）+ 预估工作量/风险”。

5 6 10 13 14 16 18 19 20 我不要工作流的类似拖拽节点的不需要那种方式 但是如果你能够操作标准话可以 深度规划并执行35个任务实现

