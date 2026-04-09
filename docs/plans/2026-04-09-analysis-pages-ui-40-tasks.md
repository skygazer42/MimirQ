# 2026-04-09 多页面 UI 深度优化 40 任务计划（KG + 评测 + 报告 + 提示词）

目标页面：
- `/graph/snapshots`（KG 快照）
- `/graph/diagnostics`（KG 检索评测）
- `/evaluations`（RAGAS 评测）
- `/evaluations/ablations`（检索消融）
- `/reports`（报告中心）
- `/prompts`（提示词）

设计准则（基于 UI Pro Max / 数据密度后台规范）：
- 单一视觉骨架：统一 Header、Data Strip、Workbench 三段式
- 单一卡片语义：信息卡、操作卡、表格卡三类，不再自由混搭
- 单一密度节奏：字号层级 14/13/12/11，控件高度 40/36/32
- 单一色彩语义：Primary / Success / Warning / Danger / Muted
- 单一交互语义：主按钮、次按钮、危险按钮、行内操作一致

## P0（基座统一，先做 12 项）

1. 建立 `analysis-*` 页面共享 token 文件（spacing/radius/shadow/typography），替换各页面硬编码 `rounded-[32px]`、`bg-[#fffdfa]` 等值。
2. 统一 6 页 `PageScaffold` 使用策略：头部、top 区、body gutter 全部改为同一配置（建议 `density="system-dense"`）。
3. 统一页面标题区：icon 容器尺寸、标题字号、描述行高、右侧操作按钮高度全部一致。
4. 提供共享 `AnalysisPageShell` 组件，封装 “Header + DataStrip + Body” 布局，供 6 页复用。
5. 提供共享 `WorkbenchSplit` 组件，统一左右/三栏边界线、滚动策略、吸顶/吸底行为。
6. 统一“统计条”组件：将各页 `InlineStat` 合并为单一 `CompactStatChip`。
7. 统一按钮密度：主按钮 `h-9`、次按钮 `h-8`、行内按钮 `h-7`；移除页面内自定义尺寸漂移。
8. 统一输入控件密度：`Input/Select/Textarea` 高度、边框、背景、focus 态一致。
9. 统一卡片边框体系：全部改为 `border-border/70` + `rounded-lg`，移除 2xl/3xl 混用。
10. 统一 hover/focus 反馈：卡片 hover 仅色彩变化，不再出现页面级各自阴影策略。
11. 统一空态组件策略：全部接入同一个 `EmptyState` 视觉规格与文案层级。
12. 统一加载态组件策略：skeleton/loader 的尺寸、位置、文案语气一致。

## P0（导航与信息架构，8 项）

13. 为 6 页定义统一二级导航文案规范（中文主标签 + 英文 key 辅助规则）。
14. 统一每页“主操作流”位置：左侧配置、中央结果、右侧 diff/详情，禁止按钮漂浮。
15. 统一“数据条下放”策略：悬浮 KPI 必须回归到各自工作区 header。
16. 统一 Tab 视觉：触发器高度、下划线样式、active 态颜色在 6 页一致。
17. 统一表格头部规范：表头字号、字重、背景层次、排序/刷新按钮风格一致。
18. 统一日志/JSON 面板结构：标题栏 + 操作区 + 代码区三段式一致。
19. 统一“危险操作”入口：删除/回滚/覆盖必须采用统一警示色与二次确认。
20. 统一“刷新”语义：页面级刷新与局部刷新按钮风格、命名、位置一致。

## P1（页面专项：Prompts，6 项）

21. 将 `/prompts` 从多卡片陈列改为“左侧筛选 + 右侧表格/列表”的密集工作台布局。
22. 重构模板列表项：标题、状态、分类、变量、标签改为两行主信息 + 一行元信息，减少卡片高度。
23. 合并批量操作条与筛选条，避免双层工具条堆叠。
24. 将“预览/编辑/复制/启停/删除”动作改为统一行内操作区，移除每卡片底部按钮堆叠。
25. 优化模板预览弹窗：正文代码区引入行号与语法高亮，顶部元信息改为 compact chips。
26. 将 KG 相关设置卡（抽取提示词/谓词本体）移入统一“高级配置折叠区”，减少主页首屏卡片噪音。

## P1（页面专项：Reports，5 项）

27. 将 `/reports` 顶部参数区重构为单行工具带，导出按钮分组并压缩到一行。
28. 将治理指标与治理效果从“多块散卡”重组为两列固定模板：左指标、右图表。
29. 统一图表卡高度（建议 260/300 双规格），解决各图表卡高不一导致的断层。
30. 统一 `StatCard` 样式与语义色阶，修复当前蓝/青/灰混用导致的层级弱化。
31. 增加“报告快照摘要带”（dataset / pipeline_hash / generated_at / redact）固定于内容区顶部。

## P1（页面专项：KG Snapshots，5 项）

32. 将 `/graph/snapshots` 自定义米白背景切回全局背景 token，消除与其他页底色偏差。
33. 统一 Studio/Audit 顶部控制条：按钮尺寸、tab 风格、统计 chips 对齐到全站规范。
34. 左侧参数栏改为“区块折叠 + 吸底主按钮”，避免大段静态说明占屏。
35. Diff 视图代码区升级为统一 JSON/DIFF viewer 组件（行号、语法色、复制导出动作一致）。
36. Audit 面板指标卡重排为 2xN 紧凑网格，减少纵向滚动。

## P1（页面专项：KG Diagnostics，4 项）

37. 将 `/graph/diagnostics` 的渐变装饰弱化，采用与 snapshots 一致的中性工作台皮肤。
38. 统一左栏参数表单网格：label 高度、控件高度、说明文案密度一致。
39. 统一 run/quality/compare 三个 tab 的“结果头部”结构，避免每 tab 自定义一套卡片。
40. Compare 区域标准化：Run A/Run B 选择、加载按钮、导出按钮采用同一操作行模板。

## P2（扩展执行建议，后续批次）

- 将 `/evaluations` 与 `/evaluations/ablations` 进一步抽象为共享 `EvaluationWorkbench`，统一模式卡、运行列表、diff 工作区。
- 为 6 页补齐视觉回归测试（source test + screenshot baseline）。
- 引入页面级设计 lint（禁止新增 `rounded-[xxpx]`、禁止任意 hex 背景、禁止未登记字号）。
- 若后续接入 Figma MCP：补充 token 映射脚本（Figma Variables -> Tailwind tokens）与自动审计。
