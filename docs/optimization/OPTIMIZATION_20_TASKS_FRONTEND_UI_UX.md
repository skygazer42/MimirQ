# 前端 UI/UX：20 项优化清单（按设计规范落地）

> 目标：统一视觉语言（design tokens）、提升可访问性（focus/aria/reduced-motion）、减少“硬编码颜色”回归，保证页面/对话框交互一致。

## A. 规范与回归守卫（1–4）

1. [x] **新增 UI 规范检查脚本**：`web/scripts/check-design-tokens.mjs`（阻止高风险硬编码样式回归）
2. [x] **接入 pnpm scripts**：`web/package.json` 新增 `ui-check`
3. [x] **扩展禁用规则**：禁止 `bg-white` / `text-white` / `bg-white/<alpha>` / `border-white` / cyan palette 等高风险 Tailwind 颜色
4. [x] **接入 Makefile 验证链路**：新增 `make ui-check`，并把它加入 `make verify`

## B. 基础组件一致性（5–12）

5. [x] **Button 语义化扩展**：新增 `success / warning / info` variants（统一语义按钮而非散落的 `bg-xxx`）
6. [x] **ModelProviderCard 组件重构**：使用 token（`bg-card/border-border`）、改为 `button`（可聚焦/可键盘触达）、状态用 `Badge`
7. [x] **ModelConfigDialog 表单可访问性**：Label + htmlFor、输入框统一用 `Input`，icon-only 按钮补齐 `aria-label`
8. [x] **ModelConfigDialog 提示样式统一**：测试结果用 `Alert`（success/destructive）
9. [x] **ChunkStrategySelect token 化**：容器/下拉框/说明文字统一使用 tokens（去掉 `bg-white`/`border-gray-*`）
10. [x] **StepIndicator token 化**：步骤完成/当前/未完成用 `primary/muted`，并加 `motion-reduce`
11. [x] **StatsCard token 化**：使用 `success/warning/info/destructive` 语义色，加入 `motion-reduce`
12. [x] **CinematicTypewriter 动效治理**：支持 `prefers-reduced-motion`，避免流式打字在 reduce-motion 下卡住

## C. 复杂对话框 / 面板（13–18）

13. [x] **IngestionDetailDialog 去硬编码白底**：Header/卡片/预格式文本块改用 `bg-card` + `border-border`
14. [x] **IngestionDetailDialog 危险操作强调**：重试/错误提示按钮改用 `destructive` 语义色（token）
15. [x] **TestGenerationDialog 去硬编码白底/白字**：弹窗容器与列表卡片改用 `bg-card`
16. [x] **TestGenerationDialog Switch 统一**：替换自绘 toggle，使用 `Switch`（含 role/aria）
17. [x] **DataGovernancePanel CTA 按钮统一**：上传 CTA 与保存按钮改用 `info` variant，移除 `text-white`
18. [x] **FileQueueItem 列表项 token 化**：active/inactive 状态改用 `bg-card`/`bg-info/10` 等，并加 `motion-reduce`

## D. 页面级收敛（19）

19. [x] **关键页面去 `bg-white/text-white`**：Graph/History/Knowledge(Feedback/Quarantine) 等页面统一 token（尤其是卡片、对话框 Header、主 CTA）

## E. 质量门槛（20）

20. [x] **全量校验通过**：`pnpm lint` / `pnpm typecheck` / `pnpm ui-check` / `pnpm api-check` / `pnpm build`

