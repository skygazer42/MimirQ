# 前端 UI/UX 优化与工程落地诊断方案

## A. 总体判断：这个前端为什么显得“不像成熟产品”

MimirQ 的前端在技术选型和底层实现上具备一定深度（如 PDF Canvas Worker 渲染、严格的视口锁定与内部滚动容器），但在**视觉表现、空间编排和微交互**上，存在明显的**“用做官网（Landing Page）的手法来做生产力工具（B2B SaaS）”**的错位感。这种错位导致了强烈的“稚嫩感”和“拼凑感”。

具体问题出在：

1. **标题系统（Marketing 风格误用）**：
   在常规的工作台、列表页使用 `text-4xl` 到 `text-5xl`（即 36px - 48px）的特大字号，配合紧凑的行高 `leading-[1.02]` 和负字间距 `tracking-[-0.03em]`，这是典型的营销页（Hero Section）设计。而在生产力工具中，这会导致顶部过度喧宾夺主，严重挤压了核心工作区（表格、图谱、文档）的空间，给人一种“头重脚轻”的夸张感。
2. **布局组织（Magic Numbers 与嵌套断层）**：
   高度和宽度的分配存在硬编码的补丁（Magic Numbers），如 `chat-area.tsx` 中限制 `max-h-48`（192px）但 JS 中又写死 `200px`，PDF 的父容器写死 `min-h-[520px]`，TOC 写死 `max-h-[calc(100vh-220px)]`。这说明没有建立统一的容器伸缩规则，导致极端尺寸或复杂嵌套下布局脆弱。
3. **交互区层级与留白（绝对定位滥用）**：
   对话输入框等区域过多依赖 `absolute` 叠加 UI（发送按钮、工具栏覆盖在输入区上方），而非结构化的流式布局。留白（Padding）未能精确避开悬浮物，导致输入时的文字被直接遮挡，这在成熟产品中是零容忍的阻断性缺陷。
4. **组件组合缺乏一致性节奏**：
   多处独立滚动容器（如 PDF 的 `overflow-y-auto` 与右侧面板的 `overflow-y-auto`）并列时，缺乏清晰的视觉边界和滚动联动（如 TOC 不跟随滚动），让用户难以建立明确的空间心智模型。

**结论**：它**不是**能力不够（PDF 渲染、图谱都很复杂），而是**缺乏一套企业级产品应有的克制、统一、像素级严谨的 Design System 约束**。

---

## B. 产品感审计

从“企业级产品”的标准审视：

- **视觉/品牌统一性**：色彩语义（Primary, Muted, Destructive）应用基本到位，但容器形态在不同页面有断层。聊天页内容区是 `max-w-4xl`，输入区却是 `max-w-3xl`，宽度不对齐打破了视觉连续性。
- **信息密度失衡**：数据治理工作台等页面，顶部的 Title、Icon、Badge、Description 占据了近 1/3 的首屏高度。作为高频操作入口，这种信息密度极其低效。
- **局部设计语言不一致**：部分面板用了重度的毛玻璃（`backdrop-blur-xl` + 阴影 + 圆角），部分又是极其克制的线框，导致页面像是由不同来源的组件拼凑而成。
- **设计系统缺失信号**：缺乏统一的排版缩放比例（Type Scale），全局没有定义标准的文本层级，每次写组件都在重新组合 Tailwind 的 `text-sm`, `text-lg`, `leading-relaxed`。缺少全局的 Z-Index 规划。

---

## C. 字体与排版审计

- **字体选择问题**：全局 CSS 引入了 `Geist Sans` 但如果未配套加载，会回退到系统字体导致跨端渲染不一。在中文环境下，未专门调优中西文混排与字重。
- **字重混乱**：过多使用了 `font-semibold`，且缺乏 `Medium` (500) 的中间过渡，导致界面只有“特别重”和“特别轻”两种对比。
- **“海报标题，表单正文”**：如前所述，页面大标题采用海报级规格，而其下紧跟着的表单或表格又非常紧凑，两者之间没有平滑的层级过渡。
- **排版建议（Type Scale）**：
  - **页面级标题（Page Title）**：从 `text-4xl/5xl` 降级为 `text-2xl`（24px）或 `text-xl`（20px），保留 `font-semibold`，行高设为 `leading-tight`。
  - **区块标题（Section Title）**：`text-base`（16px）或 `text-sm`（14px），配合 `font-medium`。
  - **正文（Body）**：`text-sm`（14px），行高 `leading-relaxed`（中文字体更需要空间呼吸）。
  - **辅助信息（Caption）**：`text-xs`（12px），使用 `text-muted-foreground`。

---

## D. 布局与界面结构审计

### 1. 数据治理工作台
- **当前结构问题**：`WorkbenchScaffold` 的大 Padding（`pt-6 md:pt-8 pb-5`）加上巨大的 `PageHeader` 标题，挤占了首屏。
- **成熟处理方式**：B2B 工作台的 Header 通常极度扁平（Height: 48px-64px），标题字号小巧，右侧紧凑排列操作按钮。
- **保守调整**：为 `PageHeader` 增加 `compact` 模式，字号缩小至 `text-xl/2xl`，图标缩小，移除无谓的上下大内边距，释放至少 100px 垂直空间。

### 2. 对话页
- **当前结构问题**：输入框容器采用绝对定位的工具栏（`absolute right-2 bottom-2`），但在 CSS 中 `padding-bottom` 仅有 `py-5` (20px)，且 `max-height` CSS (192px) 与 JS 逻辑 (200px) 不咬合。
- **成熟处理方式**：输入区（Textarea）与操作区（Actions）物理隔离，或者通过极大的 `padding` 强制隔离出输入死区。
- **保守调整**：给 textarea 增加充分的 `padding-bottom`（如 `3rem`/48px），确保多行输入滚动到最底部时，字永远在按钮上方；统一最大高度限制逻辑。

### 3. 高级解析页
- **当前结构问题**：PDF 渲染容器依赖隐式的撑开，当 `lg:flex-row` 转为 `flex-col` 或父级失去固定高度时，PDF 容器高度坍塌。由于采用了按需懒加载（IntersectionObserver），高度坍塌导致页面永远判定为不在视口内，卡死在“渲染中”。TOC 目录采用了 `100vh` 相关的魔法数字定位。
- **成熟处理方式**：严格的 Flex/Grid 布局，任何使用 `overflow-auto` 的局部滚动面板，其父级必须有确定的边界（如 `flex-1 min-h-0`）。
- **保守调整**：为包含 `<PdfViewer>` 的包裹 `div` 补齐 `flex-1 min-h-0 h-full overflow-y-auto`；TOC 的容器高度基于父级百分比计算，而非 `100vh`。

---

## E. 明确问题诊断

### 1. 数据治理工作台标题过大
- **根因**：`PageHeader` 复用了过重的 Landing Page 级 Typography (`text-4xl/5xl`) 与粗放的间距。
- **严重程度**：中（效率降低）。
- **修复优先级**：高（极易修复，收益明显）。
- **影响**：破坏了专业感，首屏信噪比低，典型的“产品未成年”症状。

### 2. 对话输入区文字被遮挡
- **根因**：`<textarea>` 的 padding 不足以避开内部 `absolute` 定位的发送和语音按钮，且在文本行数增加触发内部滚动时，最后一行被物理遮盖。
- **严重程度**：极高（阻断核心操作）。
- **修复优先级**：最高。
- **影响**：输入心流被打断，用户会认为产品有严重的低级 Bug。

### 3. 高级解析 PDF 长时间“渲染中”
- **根因**：前端 CSS 布局高度坍塌，导致 PDFViewer 根节点不可见，无法触发其内部控制页面渲染的 IntersectionObserver；或者 worker 渲染出现挂起未正确捕获处理。
- **严重程度**：极高（功能不可用）。
- **修复优先级**：最高。
- **影响**：严重丧失系统可信度。这兼具“产品感”（布局脆弱）和“功能稳定性”（假死）双重问题。

### 4. Markdown + TOC 预览体验差
- **根因**：`MarkdownToc` 目前仅是一个静态的锚点列表，只有点击跳转事件（hashchange），**完全没有**实现 IntersectionObserver 来监控正文滚动以双向高亮 TOC 目录树。
- **严重程度**：中（影响长文阅读）。
- **修复优先级**：高。
- **影响**：长文档阅读体验割裂，无法有效定位当前进度。

---

## F. 视觉风格改进方向

以下两个方向均可在不重写结构的前提下通过修改 Tailwind classes 实现：

### 方向 1：精益生产力 (Lean & Dense)
- **核心气质**：克制、紧凑、数据优先。
- **适用原因**：MimirQ 本身是处理数据和知识的基础设施，不需要靠花哨吸睛，需要的是高信噪比。
- **落地手段**：
  - **字体**：全面降级标题字号（最大不超过 24px），统一行高。
  - **间距**：将全局的大 padding（`p-6`, `p-8`）替换为中等 padding（`p-4`, `p-5`）。
  - **卡片/面板**：移除过度厚重的毛玻璃（`backdrop-blur-xl`）和彩色投影，换为干净的 `bg-card` 加 1px 实色边框（`border-border`）和极弱的基础阴影（`shadow-sm`）。

### 方向 2：结构化面板 (Structured Panes)
- **核心气质**：IDE/编辑器级别的专业感。
- **适用原因**：解析页、图谱页已经采用了典型的左右/多面板结构，强化面板边缘能增加系统稳定感。
- **落地手段**：
  - **边框**：强化 pane 之间的分割线（`border-r`, `border-b`），取消悬浮卡片式设计。
  - **导航**：TOC 目录从一个漂浮的 sticky 块变成一个右侧固定宽度的实心边栏。
  - **滚动区**：明确每一个局部滚动区，确保互不干涉。

---

## G. 可执行的前端改造方案

### 1. 页面级：数据治理工作台
- **目标**：回收头部空间。
- **调整对象**：`web/components/workbench/workbench-scaffold.tsx`
- **调整方向**：
  - `<div className="px-6 md:px-8 pt-6 md:pt-8 pb-5 md:pb-6">` → 改为 `px-4 md:px-6 pt-4 pb-3`
  - 向 `PageHeader` 传递一个 `compact={true}` 属性。
- **验收**：工作台打开时，头部紧凑，表格数据区上移。

### 2. 组件级：PageHeader (`page-header.tsx`)
- **目标**：降低标题压迫感。
- **调整对象**：`<h1>` 标签及外层容器。
- **调整方向**：
  - 增加 `compact` 参数逻辑。
  - 如果 `compact` 为真：图标尺寸 `size-14` → `size-10`；标题字号 `text-4xl/5xl` → `text-xl/2xl`；消除紧缩字距。
- **风险**：影响其他未传入 `compact` 的独立大页面，故采用可选参数，不破坏老页面。

### 3. 组件级：Chat Composer (`chat-area.tsx`)
- **目标**：彻底解决输入区文字遮挡。
- **调整对象**：`textarea` 元素及 JS 高度计算。
- **调整方向**：
  - 移除 `py-5`，改为 `pt-4 pb-14`（保证底部有绝对安全的留白）。
  - CSS 限制 `max-h-[200px]` 配合 JS 的 `Math.min(..., 200)`，确保严格一致。
  - 去掉发送按钮外层的无效 wrapper。
- **验收**：粘贴长文本直到出现内部滚动条，光标移动到最后一行，文字的下半部绝不被按钮遮挡。

### 4. 页面级：高级解析页 (`parsing-active-file-pane.tsx`)
- **目标**：修复 PDF 高度坍塌与 TOC 魔法数字定位。
- **调整对象**：包裹 `PdfViewer` 的 div 和包裹 `MarkdownToc` 的 div。
- **调整方向**：
  - PDF 父级添加：`className="flex-1 min-h-0 h-full relative"`，确保容器有严格的高度基准。
  - TOC 容器移除 `100vh` 相关的算式，改为基于 Flex 父级的 `h-full overflow-y-auto` 或使用较稳定的 `sticky top-4 self-start`。
- **风险**：可能需要在极窄屏幕（mobile）下重新分配 Flex flex-col 的权重，确保 PDF 至少有一个最小高度如 `min-h-[400px]`。

### 5. 组件级：MarkdownToc (`markdown-toc.tsx`)
- **目标**：实现滚动联动。
- **调整对象**：添加 `IntersectionObserver`。
- **调整方向**：
  - 使用 React `useEffect` 获取所有 `headings.map(h => document.getElementById(h.id))`。
  - 设置 `rootMargin: "-20% 0px -60% 0px"` 观察哪些标题进入视野。
  - 增加内部 state `activeId`，给对应 `<li>` 赋予强高亮样式。
- **验收**：滚动 Markdown 预览时，侧边栏目录跟随变亮。

---

## H. Quick Wins 与第二阶段

**Quick Wins (应立即执行)**:
1. (G3) 修复聊天输入框遮挡（修改 textarea padding 即可解决）。
2. (G4) 修复 PDF 懒加载渲染假死（补齐 `flex-1 min-h-0 h-full` 即可解决）。
3. (G1+G2) 压缩 Workbench 标题区（添加 `compact` 属性调整 class 即可）。

**第二阶段产品化优化**:
1. (G5) Markdown TOC 滚动跟随（需要手写或引入 ScrollSpy 的 Hook 逻辑）。
2. 全局剥离冗余的阴影和大字号，建立统一的 Typography Scale。
3. 统一个大模块的内容最大宽度（统一 Chat 的 max-w-3xl/4xl 差异）。

---

## I. 验收标准

- [ ] **空间利用**：“数据治理工作台”首屏可见数据列表行数至少增加 2-3 行，标题区不显得突兀。
- [ ] **输入无阻断**：在对话框输入连续的 10 行以上文字，触发滚动后，位于底部的中文字符及光标完全可见，绝不与发送/语音按钮重叠。
- [ ] **PDF 可靠性**：上传并打开任意多页 PDF，即便在调整浏览器窗口大小、收起展开侧边栏时，PDF 均能顺畅渲染当前视野内的页面，不再无限卡在“渲染中”。
- [ ] **MD 导航**：在解析预览区滚动长 Markdown 文档时，右侧目录（TOC）会自动且精准地高亮当前正在阅读的章节。
- [ ] **视觉气质**：页面显得更加紧凑、专业，摆脱了“大字号 + 大留白”的 Landing Page 既视感。

---

## 给 Claude 的实施摘要

**修复目标**：针对当前系统 UI/UX 进行 4 项核心局部阻断级/体验级修复，压缩多余空间，修复高度坍塌，消除输入遮挡。不重构整体布局。

**修改优先级与范围**：
1. **(P0) 对话区输入遮挡** (`chat-area.tsx`)：修改 `<textarea>` 的 padding，使用 `pt-4 pb-14` 或类似值，并在 CSS 和 JS 中对齐高度最大值（如 200px），确保无论如何滚动，文本都不被 `absolute` 的发送按钮遮挡。
2. **(P0) PDF 预览不显示** (`parsing-active-file-pane.tsx`)：给包裹 `<PdfViewer>` 的父级 div 添加 `flex-1 min-h-0 h-full relative` 等约束，防止 Flex 布局下高度坍塌成 0 导致 IntersectionObserver 失效。
3. **(P1) 工作台大标题空间浪费** (`page-header.tsx`, `workbench-scaffold.tsx`)：为 `PageHeader` 添加 `compact` boolean prop，为 true 时缩小 icon、将 title 降级至 `text-xl/2xl`，同时在 scaffold 中缩减 padding。
4. **(P1) Markdown TOC 无滚动监听** (`markdown-toc.tsx`)：引入基于 `IntersectionObserver` 的 ScrollSpy 逻辑，监听 headings 数组中的 id，实现目录项随正文滚动自动高亮 (`activeId` state)。

**验收要求**：严格使用 Tailwind 现存类名，不引入新依赖。PDF 高度修复必须在桌面和窄屏（flex-col）下均工作。保持原有组件 API 向后兼容。