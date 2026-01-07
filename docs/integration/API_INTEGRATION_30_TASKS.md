# MimirQ：前端↔后端接口接入审查（30 个任务，已执行）

目标：以“前端实际调用”为准，逐项核对后端路由与响应结构，补齐缺失接口与不一致点，确保页面功能可跑通且接口契约可持续校验。

## 30/30 已完成

1. ✅ 盘点 `web/lib/api-client.ts` 的所有 axios 路由调用点
2. ✅ 盘点前端所有 `fetch(${API_V1_BASE_URL}...)` 直连调用点（chat/navbar/graph）
3. ✅ 汇总前端调用路径 + HTTP 方法，形成“前端 API 面”
4. ✅ 盘点 `app/api/v1/__init__.py` 的路由挂载前缀（prefix）
5. ✅ 盘点后端各模块 `@router.<method>(...)` 路由定义（含 KG 路由）

6. ✅ 修复 Documents 上传返回结构与前端不一致（`/documents/upload` 返回完整文档字段）
7. ✅ 修复 Documents 手动入库返回结构与前端不一致（`/documents/manual` 返回完整文档字段）
8. ✅ 修复 `documents.metadata` ORM 映射：后端实际字段为 `doc_metadata`，序列化应输出为 `metadata`
9. ✅ 修复 `document_chunks.metadata` ORM 映射：后端实际字段为 `doc_metadata`，序列化应输出为 `metadata`
10. ✅ 避免文档列表接口意外触发 chunks 懒加载：仅当显式设置 `chunks_loaded` 才序列化 `chunks`

11. ✅ `GET /documents/{id}`：当 `include_chunks=true` 时，后端显式设置 `chunks_loaded` 以返回切片
12. ✅ `GET /documents/`：列表返回不再隐式带 chunks，前端列表/侧边栏加载更稳定

13. ✅ 增加 KG 图谱节点扩展接口：`GET /kg/graph/expand`
14. ✅ 增加 KG 图谱节点搜索接口：`GET /kg/graph/search`
15. ✅ KG 图谱相关接口统一做 document ACL 过滤（按可访问文档范围）

16. ✅ 前端 GraphService：`expandNode()` 接入 `/kg/graph/expand`（UUID 节点优先走后端）
17. ✅ 前端 GraphService：`searchNodes()` 接入 `/kg/graph/search`
18. ✅ GraphService 保留非 UUID / KG 未启用时的 mock fallback（确保离线/GraphML 上传仍可用）

19. ✅ 补齐数据治理→切块预览的数据传递：新增 `useParsedFiles.updateParsedFile()`
20. ✅ 数据治理“保存并继续”：将清洗后的 markdown 回写到共享存储，并 toast 提示

21. ✅ 增加自动化“接口契约存在性”校验脚本：`scripts/check-api-contract.mjs`
22. ✅ Makefile 增加 `make api-check`（运行接口契约校验）
23. ✅ Makefile 增加 `make verify`（api-check + frontend lint + backend compileall）

24. ✅ 增加后端单测：验证 Document Schema 优先读取 `doc_metadata`（避免误读 SQLAlchemy `.metadata`）
25. ✅ 补充 schema 可变默认值清理（`Field(default_factory=...)`），避免跨请求污染

26. ✅ 运行 `make api-check`：确认前端调用的路由在后端均存在
27. ✅ 运行 `cd web; pnpm run lint`：确认前端无 lint 错误
28. ✅ 运行 `python3 -m compileall app`：确认后端语法可编译

29. ✅ 全仓检查并清零前端 TODO（数据治理保存链路已落地）
30. ✅ 输出本审查文档，作为后续回归与 PR Checklist 基准

## 关键落点文件

- 后端 Documents 契约修复：`app/api/schemas/document.py`、`app/api/v1/documents.py`
- 后端 KG 增量接口：`app/rag/kg/api/routes.py`
- 前端 KG 接入：`web/services/graph-service.ts`
- 数据治理保存链路：`web/hooks/use-parsed-files.ts`、`web/components/data-governance-panel.tsx`
- 自动化校验：`scripts/check-api-contract.mjs`、`Makefile`
