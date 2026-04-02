# API 文档拆分索引

> 由 `scripts/docs/split_api_md.py` 从 `docs/api/source/legacy-api-narrative.md`（或 `docs/API.md`）自动切分（忽略代码围栏内的 `#` 行）。
> 更新长文：编辑 legacy 文件后重新运行本脚本，或直接改 `reference/` 下分片。

## 分片列表

| 文件 | 标题 |
| --- | --- |
| [`000-title.md`](./000-title.md) | MimirQ API 接口文档 |
| [`001-快速入门.md`](./001-快速入门.md) | 快速入门 |
| [`002-核心使用流程.md`](./002-核心使用流程.md) | 核心使用流程 |
| [`003-完整代码示例.md`](./003-完整代码示例.md) | 完整代码示例 |
| [`004-api-详细参考.md`](./004-api-详细参考.md) | API 详细参考 |
| [`005-常见问题解答.md`](./005-常见问题解答.md) | 常见问题解答 |
| [`006-附录.md`](./006-附录.md) | 附录 |
| [`007-错误码详解.md`](./007-错误码详解.md) | 错误码详解 |
| [`008-rag-配置参数详解.md`](./008-rag-配置参数详解.md) | RAG 配置参数详解 |
| [`009-postman-使用指南.md`](./009-postman-使用指南.md) | Postman 使用指南 |
| [`010-实战场景示例.md`](./010-实战场景示例.md) | 实战场景示例 |
| [`011-调试与排错指南.md`](./011-调试与排错指南.md) | 调试与排错指南 |
| [`012-高级功能-知识图谱.md`](./012-高级功能-知识图谱.md) | 高级功能：知识图谱 |
| [`013-前端集成指南.md`](./013-前端集成指南.md) | 前端集成指南 |
| [`014-安全最佳实践.md`](./014-安全最佳实践.md) | 安全最佳实践 |
| [`015-性能优化建议.md`](./015-性能优化建议.md) | 性能优化建议 |
| [`016-评估系统-ragas.md`](./016-评估系统-ragas.md) | 评估系统 (RAGAS) |
| [`017-提示词模板管理.md`](./017-提示词模板管理.md) | 提示词模板管理 |
| [`018-系统配置-api.md`](./018-系统配置-api.md) | 系统配置 API |
| [`019-术语表.md`](./019-术语表.md) | 术语表 |
| [`020-api-模块索引.md`](./020-api-模块索引.md) | API 模块索引 |
| [`021-版本历史.md`](./021-版本历史.md) | 版本历史 |
| [`022-快速参考卡片.md`](./022-快速参考卡片.md) | 快速参考卡片 |
| [`023-高级功能-文档处理管道.md`](./023-高级功能-文档处理管道.md) | 高级功能：文档处理管道 |
| [`024-用户反馈-api.md`](./024-用户反馈-api.md) | 用户反馈 API |
| [`025-系统元数据-api.md`](./025-系统元数据-api.md) | 系统元数据 API |
| [`026-分块策略详解.md`](./026-分块策略详解.md) | 分块策略详解 |
| [`027-部署指南.md`](./027-部署指南.md) | 部署指南 |

## 全栈手册

- [Docusaurus 手册（GitHub Pages）](https://skygazer42.github.io/MimirQ/handbook/)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)

### 联调与业务剧本

- [集成总览](https://skygazer42.github.io/MimirQ/handbook/docs/integration/welcome)
- [业务剧本：新租户首日上线](https://skygazer42.github.io/MimirQ/handbook/docs/integration/tasks/go-live-tenant)
- [业务剧本：知识库可对用户问答](https://skygazer42.github.io/MimirQ/handbook/docs/integration/tasks/knowledge-base-qa)
- [业务剧本：文档卡在解析或索引](https://skygazer42.github.io/MimirQ/handbook/docs/integration/tasks/document-stuck)
