# 深度优化（全栈 20 项，计划 + 执行）

目标：提升 **可维护性/可联调性/可构建性/启动性能/类型契约稳定性**，并把关键校验自动化到 `make verify` / CI。

## 20 项清单（执行记录）

### Tooling / CI / DX
1. [ ] 引入 `ruff.toml`：统一 lint 规则、排除无关目录、减少噪音
2. [ ] 处理 `E402`：对少数“故意在 import 前做事”的入口做 per-file ignore
3. [ ] 处理 DeepDoc vision 的 `F405`：避免 star-import 触发的大量告警
4. [ ] 执行 ruff auto-fix：清理未使用 import/变量（`F401/F841`）
5. [ ] 让 `make verify` 在干净仓库中可通过（至少 lint 阶段）
6. [ ] 强化 `make openapi-check`：生成后校验 **无 diff**（强制提交最新 OpenAPI/Types）
7. [ ] 前端侧增加 `pnpm api-check`/`pnpm openapi-types` 便捷命令
8. [ ] 补充优化文档与回归说明（本文件 + 关联文档更新）

### Backend（性能 + 契约）
9. [ ] `parser_factory` 改为惰性单例：避免 import 时加载 PyMuPDF/打印日志（加速 OpenAPI 导出）
10. [ ] parser 可用性日志降噪（debug/开关控制），避免导 OpenAPI 时刷屏
11. [ ] `GET /api/v1/health` 增加显式 `response_model`（稳定 schema）
12. [ ] `GET /api/v1/health/ready` 增加显式 `response_model`（稳定 schema）
13. [ ] `GET /api/v1/meta` 增加显式 `response_model`（稳定 schema）
14. [ ] OpenAPI 导出模式优化：在导出脚本里设置环境标记，减少副作用（日志/重型初始化）
15. [ ] 增加单测覆盖：验证惰性工厂不会在 import 时初始化重型依赖

### Frontend（契约 + 类型）
16. [ ] 增加 `web/types/backend.ts`：从 `web/types/openapi.ts` 取类型别名，减少手写漂移
17. [ ] `healthApi/metaApi` 改用 OpenAPI 生成类型（端到端对齐）
18. [ ] 清理/整合 `web/types/index.ts` 中重复类型（保留向后兼容导出）
19. [ ] 增加 `web/scripts/README.md`：说明前端侧如何跑契约检查

### Docs（联调）
20. [ ] 更新 `docs/integration/API_CONTRACT.md`：补充 pnpm 命令与“无 diff”策略

