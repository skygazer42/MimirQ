# 本地模型退出验证记录

日期：2026-11-05。集成基线：`a9b2eb54a01d40fee32596642bee6752af03dcc1`。本记录区分定向验收与原仓库已有失败，不代表全仓测试或部署验收通过。

## 本批验证

- 后端定向验收：27 个文件、264 项通过，25 个已复现的基线失败单独登记。
- 模型退出与审查边界检查：62 项通过，涵盖请求、工厂、持久配置读写、旧启用开关、图片 HTTP 410、历史会话、真实聊天/预览调用、模板继承激活与图片资源权限。
- 前端：9 个文件、119 项通过；包含设置、服务协议保留、旧值显示、自动标注与图片代理/引用。
- Python 3.11 AST、相关 Ruff、前端 ESLint 与 tracked 前端来源及其真实导入的非增量 TypeScript 检查。
- 真实应用 OpenAPI 导出与类型重建；浏览器 API 契约、覆盖、类型漂移、原生弹窗、主题和内部路由检查通过。
- 未运行真实模型服务、生产镜像构建、完整原生 OCR 或数据迁移。现有轻量环境缺少 nltk，原生视觉初始化测试因依赖缺失未纳入验收。

## 独立审查后的回归验证

独立审查指出四个重要问题；另一个退出预设的写入问题按同等优先级处理。先用 19 项失败复现，再修复历史引用被执行校验拦截、数据集/模板退出错误被容错吞掉、模板写入/继承激活漏校验和图片引用绕过被引用资源权限的问题。

新增的[边界回归测试](../../tests/test_retirement_review_boundaries.py)还覆盖受支持的显式请求覆盖、停用或替换旧模板、同租户不可读文档、其他账户预览、合法预览复用、跨租户引用与缺少身份。权限存储故障明确向上传播，未改动既有授权测试或放宽权限来取得通过结果。与原模型退出测试合计 62 项通过，随后重跑上述后端定向验收。

## 已复现的后端基线失败

以下测试在原工作区也失败；资产测试失败集合与本批逐项一致。两个旧 engine 绑定用例在原树的隔离测试进程中补齐导入兼容与测试 SDK key 后仍失败，未修改生产树来伪造基线通过。

- `test_index_manual_document_chunks_characterizes_metadata_merging_and_image_tracking`
- `test_list_queryset_health_runs_filters_newest_first_and_timeseries`
- `test_stream_chat_resolves_rewrite_bindings_through_engine_module`
- `test_stream_chat_resolves_intent_router_through_engine_module`
- `test_hybrid_search_degrades_when_some_runtime_shards_timeout`
- `test_hybrid_search_propagates_retryable_timeout_when_all_runtime_shards_timeout`
- `test_asset_request_header_auth_requires_user_id_by_default`
- `test_asset_request_rejects_query_bearer_promotion[access_token]`
- `test_asset_request_rejects_query_bearer_promotion[token]`
- `test_download_document_forces_attachment_for_active_content[asset.css-body{background:red}]`
- `test_download_document_forces_attachment_for_active_content[asset.html-<html><script>alert(1)</script></html>]`
- `test_download_document_forces_attachment_for_active_content[asset.js-alert(1)]`
- `test_download_document_forces_attachment_for_active_content[asset.svg-<svg xmlns='http://www.w3.org/2000/svg'></svg>]`
- `test_download_document_forces_attachment_for_active_content[asset.xml-<root/>]`
- `test_download_document_hides_object_storage_errors`
- `test_download_document_keeps_inline_for_safe_image_preview`
- `test_download_document_rejects_spoofed_request_tenant_when_verified_jwt_tenant_exists`
- `test_download_document_supports_generic_object_storage_uri`
- `test_download_document_uses_header_auth_and_no_store_cache`
- `test_get_image_enforces_parent_document_acl_from_preview_ownership_metadata`
- `test_get_image_recovers_from_malformed_sidecar_via_exact_legacy_acl`
- `test_get_image_recovers_legacy_binding_through_document_acl`
- `test_get_image_selects_safe_multi_candidate_without_persisting_binding`
- `test_get_image_skips_legacy_lookup_when_preview_file_is_missing`
- `test_get_image_uses_header_auth_and_no_store_cache`

## 其他已有检查问题

- `web/app/settings/use-settings-page-state.test.tsx`：未跟踪的旧 Hook 测试有 12 项 loading 时序失败，已在原工作区复现；受本批维护的 tracked 设置行为测试通过。
- 不限定 tracked 来源的 TypeScript 扫描会包含历史未跟踪草稿并报错；本批检查真实 tracked 来源和其导入，不将该结果称为整个混合工作区类型检查通过。
- design-tokens：原有未跟踪 `web/components/ui/page-status.tsx:22` 使用 tracking-normal。
- interactive-controls：原有未跟踪 `web/app/evaluations/_components/conversation-evaluation.tsx:151` 与 `web/components/chunk-preview/components/workbench/compare-workbench.tsx:52` 的按钮缺少动作绑定。

## 数据与安装边界

退出的旧模型选择会明确失败。已有向量、图片、文档和当前虚拟环境不自动删除或卸载；模型 API 与旧 local 向量空间的迁移需要显式核对。Chroma/FAISS 的可选后端配置继续保留。
