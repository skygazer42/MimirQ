# System Pages UI Pro Max - 50 Tasks Plan & Execution

Date: 2026-04-08  
Scope: Sidebar `系统` 下 7 个页面（`/diagnostics`, `/usage`, `/audit`, `/access-review`, `/settings/rbac`, `/settings/groups`, `/settings`）  
Status: Executed in current session

## 1) Shared Foundations (8/8)

1. [x] 为 `StatCard` 增加 `dense` 变体，统一紧凑信息卡密度与字体层级。  
2. [x] 为 `StatsGrid` 增加 `dense` 变体，统一系统页 KPI 栅格间距。  
3. [x] 将系统页按钮统一为 `h-8` 小尺寸密度规范（主按钮/描边按钮）。  
4. [x] 将系统页输入控件统一为 `h-9`、`text-[12px]`、`rounded-lg` 规范。  
5. [x] 统一系统页面板圆角为 `rounded-lg`，降低卡片“胖感”。  
6. [x] 统一系统页边框强度为 `border-border/70`，减少视觉噪音。  
7. [x] 统一系统页表头为 uppercase + tracking 小字重风格。  
8. [x] 统一系统页 hover 交互为轻量 `bg-muted/20`，保持 dense 且可读。  

## 2) Diagnostics (`/diagnostics`) (8/8)

9. [x] 页面标题由“诊断”升级为“诊断中心”，提升信息架构语义。  
10. [x] 诊断页描述重写为多维诊断范围（健康/依赖/质量/漂移/性能）。  
11. [x] 顶部 `/docs` 动作按钮统一为 dense outline 风格。  
12. [x] 顶部 `openapi.json` 动作按钮统一为 dense outline 风格。  
13. [x] 诊断页宽度提升至 `size="7xl"`，减小拥挤与换行压力。  
14. [x] 引入 `DenseCard` 包装，统一诊断页卡片圆角/阴影/hover 行为。  
15. [x] 统一诊断页 icon-only 按钮为 `h-8 w-8 rounded-lg`。  
16. [x] 保留全部无障碍 `title`/`aria-label`，并通过 icon-button 可访问性测试。  

## 3) Usage & Quota (`/usage`) (7/7)

17. [x] 页面标题调整为“用量/配额”，与侧边栏命名一致。  
18. [x] 筛选下拉触发器改为 dense 尺寸与字体。  
19. [x] 刷新按钮改为 dense outline 样式并保留 loading 旋转反馈。  
20. [x] 顶部 KPI 区切换为 `StatsGrid dense` + `StatCard dense`。  
21. [x] 两块主面板改为 `Panel padding="md"` + `rounded-lg` + `shadow-none`。  
22. [x] 用量与成本表头改为 sticky dense 表头样式。  
23. [x] 表格行加入 hover 反馈，数值列统一 `tabular-nums` 紧凑排版。  

## 4) Audit Logs (`/audit`) (7/7)

24. [x] 页面副标题改写为“可按 actor/action/request 回溯”的任务导向描述。  
25. [x] 顶部刷新与重置按钮统一 dense outline 样式。  
26. [x] 快捷预设按钮降高并统一字重，减少视觉占用。  
27. [x] 全部过滤输入框统一 dense 输入控件样式。  
28. [x] 分页按钮统一 dense outline 样式。  
29. [x] 审计列表卡片统一为 rounded-lg + 细边框 + 高亮 hover。  
30. [x] 展开 JSON 区字体降至 `text-[11px]`，提升信息密度。  

## 5) Access Review (`/access-review`) (7/7)

31. [x] 页面描述重写为“审查 + 导出”的任务流表达。  
32. [x] 顶部刷新按钮统一 dense outline 风格。  
33. [x] 顶部导出按钮统一 dense primary 风格。  
34. [x] 摘要 KPI 区切换为 `StatsGrid dense` + `StatCard dense`。  
35. [x] 分布卡片（dataset/document）改为 rounded-lg + 紧凑字体。  
36. [x] 导出区 `Select`/`Input`/`Switch` 容器全面统一 dense 控件样式。  
37. [x] 导出进度文案统一为小号等宽数字风格，提升可扫描性。  

## 6) Members Permissions (`/settings/rbac`) (5/5)

38. [x] 页面描述改写为更直接的权限影响说明。  
39. [x] 页面主容器由 Card 风格收敛为 dense Panel 风格。  
40. [x] 搜索输入、角色下拉改为 dense 控件体系。  
41. [x] 当前成员状态由纯文本 `yes/no` 升级为统一 `Badge` 标识。  
42. [x] 保存按钮改为 dense primary，整表行 hover 与字号统一。  

## 7) Group Management (`/settings/groups`) (5/5)

43. [x] 页面描述压缩并统一术语表达。  
44. [x] 顶部刷新/新建组按钮统一 dense 规范。  
45. [x] 新建组对话框输入、确认/取消按钮统一 dense 样式。  
46. [x] 列表容器切换为 dense Panel，表头采用 uppercase dense 规范。  
47. [x] “items 计数”升级为 Badge，并统一删除按钮尺寸与圆角。  

## 8) Settings (`/settings`) (3/3)

48. [x] 设置页标题描述改写，强调统一配置中心语义。  
49. [x] 顶部“刷新/保存配置”按钮切换到 dense 行为与尺寸。  
50. [x] 左侧目录导航与主内容区间距、滚动锚点、section 节奏重新压缩。  

## Verification

- `pnpm exec eslint app/diagnostics/page-client.tsx app/usage/page.tsx app/audit/page.tsx app/access-review/page.tsx app/settings/rbac/page.tsx app/settings/groups/page.tsx app/settings/page.tsx components/ui/stats-card.tsx`  
- `pnpm vitest run app/settings/page.structure.source.test.ts i18n/settings-groups-routing.source.test.ts app/governance-admin-messages.source.test.ts app/diagnostics/page.a11y-labels.source.test.ts app/diagnostics/page.embedding-drift.source.test.ts app/diagnostics/page.perf-suite.source.test.ts components/icon-buttons.a11y.source.test.ts`

## Round 3 (Token Layer Harmonization)

- 新增 `web/components/ui/system-page-tokens.ts` 并作为系统页文本层级基准（heading/body/subtle/microLabel/monoMeta/tableHead）。  
- 将 token 接入 7 个系统页及关键设置子区块（`system-status` / `rag`），统一标题、弱化文案、表头与等宽元信息样式。  
- 该轮仅做样式层收敛，不改业务数据流与交互逻辑。  

### Round 3 Verification

- `pnpm exec eslint app/diagnostics/page-client.tsx app/usage/page.tsx app/audit/page.tsx app/access-review/page.tsx app/settings/page.tsx app/settings/rbac/page.tsx app/settings/groups/page.tsx app/settings/_sections/system-status-section.tsx app/settings/_sections/rag-section.tsx components/ui/system-page-tokens.ts`  
- `pnpm vitest run app/settings/page.structure.source.test.ts i18n/settings-groups-routing.source.test.ts 'app/settings/groups/[id]/page.source.test.ts' app/diagnostics/page.a11y-labels.source.test.ts app/diagnostics/page.perf-suite.source.test.ts app/diagnostics/page.embedding-drift.source.test.ts components/icon-buttons.a11y.source.test.ts`

## Round 4 (Dense Table/List Balance)

- `usage` 两张主表改为 `table-fixed`，为数值列设置固定宽度，提升纵向扫描速度并降低“右侧拥挤漂移”。  
- `usage` 数据集主键列新增 `truncate + title`，长数据集 id 在 dense 场景下避免挤压数值列。  
- `audit` 事件卡片操作按钮缩小为行内紧凑版本（`h-7`），并收紧卡片内边距与 JSON 区高度。  
- `settings/rbac` 成员表压缩行高、细化列占比（`user_id/role/current/actions`）并缩小角色下拉/保存按钮。  
- `settings/groups` 组列表压缩行高，`external_id` 与 `id` 列重新配比并统一图标操作按钮尺寸。  

### Round 4 Verification

- `pnpm exec eslint app/usage/page.tsx app/audit/page.tsx app/settings/rbac/page.tsx app/settings/groups/page.tsx`  
- `pnpm vitest run app/settings/page.structure.source.test.ts i18n/settings-groups-routing.source.test.ts 'app/settings/groups/[id]/page.source.test.ts' app/diagnostics/page.a11y-labels.source.test.ts app/diagnostics/page.perf-suite.source.test.ts app/diagnostics/page.embedding-drift.source.test.ts components/icon-buttons.a11y.source.test.ts`

## Round 5 (Filter Bar Single-Line + Breakpoint Collapse)

- `audit` 过滤区改为两段式：主筛选（Action/Actor/Request）在大屏保持单行；高级筛选（Resource/Since/Until）在小屏使用 `details` 折叠。  
- `audit` 分页状态栏改为 `mobile stacked / desktop inline`，避免窄屏时按钮与状态互挤。  
- `usage` 顶部窗口选择 + 刷新动作改为 `mobile vertical / desktop inline`，小屏点击区更稳。  
- `settings/rbac` 搜索区改为单行主操作带（搜索 + 可见计数），减少顶部断裂感。  
- `settings/groups` 搜索区改为单行主操作带（搜索 + 过滤提示），保持列表入口整洁。  
- `access-review` 导出配置区改为 `xl` 12 列分配（format/limit/gzip 单行并排），并优化 include-sensitive 行在小屏的换行行为。  

### Round 5 Verification

- `pnpm exec eslint app/audit/page.tsx app/usage/page.tsx app/settings/rbac/page.tsx app/settings/groups/page.tsx app/access-review/page.tsx`  
- `pnpm vitest run app/settings/page.structure.source.test.ts i18n/settings-groups-routing.source.test.ts 'app/settings/groups/[id]/page.source.test.ts' app/diagnostics/page.a11y-labels.source.test.ts app/diagnostics/page.perf-suite.source.test.ts app/diagnostics/page.embedding-drift.source.test.ts components/icon-buttons.a11y.source.test.ts`
