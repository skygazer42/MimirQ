# 主流 RAG / AI Chat 产品 UI/UX 设计研究报告 (2025-2026)

> 研究日期: 2026-04-14
> 研究范围: Perplexity AI, ChatGPT, Vercel AI Chat, Dify.ai, RAGFlow, Coze, Cursor, Linear

---

## 一、Perplexity AI — 搜索优先的 RAG UI

### 1.1 布局 (Layout)

| 属性 | 值 |
|------|-----|
| 内容区最大宽度 | `--thread-max-width: 42rem` (672px) |
| 整体结构 | 左侧边栏 + 中央内容区 + 右侧 Sources 面板 |
| 侧边栏宽度 | 可拖拽调整，无固定公开值 |
| 搜索栏定位 | 首页居中大尺寸，进入对话后缩至顶部 |
| 响应式 | 移动端隐藏侧边栏，Sources 面板折叠到回答下方 |

**布局特色**: 搜索优先设计 — 首页以大号欢迎文案 + 醒目搜索框为核心，答案页采用「回答 + 来源」双栏布局，来源面板在右侧展示所有引用 URL。

### 1.2 字体 (Typography)

| 属性 | 值 |
|------|-----|
| 品牌字体 | FK Grotesk (刚性几何但不冰冷，兼具精确与亲和感) |
| 正文字体 | FK Grotesk Neue (更少装饰，适合大段阅读) |
| 词标字体 | FK Display |
| 自定义字体 | Perplexity Sans Variable, Perplexity Serif Variable |
| 字间距 | 适中，不过紧不过松，小尺寸优先可读性 |
| 排版风格 | 编辑式 (editorial)，借鉴杂志和传统媒体设计 |

### 1.3 色彩系统 (Color System)

| 角色 | 色值 |
|------|------|
| 主色 (True Turquoise) | `#20808D` |
| 品牌青色 | `#1FB8CD` |
| 交互高亮 | `#20b8cd` |
| Off-black | `#091717` / `#13343B` |
| Paper White | `#FBFAF4` / `#F3F3EE` |
| 暗色背景 | `#1a1a1a` |
| 表面层级 | `#1a1a1a` → `#242424` → `#3a3a3a` |
| 搜索栏背景 | `#282828`，边框 `#CCCCCC`，聚焦边框 `#F5C1A9` |
| 搜索栏圆角 | `5px` |

**色彩策略**: 青色 (teal/cyan) 刻意避开竞品的蓝色 (Google, Meta)，传达清晰、沟通和创新感。色彩使用极度克制 — 团队发现实际只有链接会大量用到颜色。

### 1.4 聊天 UI

- **回答格式**: 回答以 sparkle 图标 + "Answer" 标题开头
- **引用样式**: 行内脚注编号 `[1][2]`，点击可展开原文摘要
- **来源卡片**: 右侧面板展示所有引用 URL，带可展开预览
- **无气泡设计**: 不使用传统消息气泡，采用全宽答案区域

### 1.5 微交互 (Micro-interactions)

- **加载动画**: 自定义 Loader Morph 动画（形态变化）
- **过渡动画**: 使用 Jitter 工具制作 hover 效果和状态转换
- **设计理念**: Motion 不是点缀，而是品牌表达和用户引导的核心手段
- **搜索过程**: 显示实时搜索进度，逐步展示 Sources

### 1.6 空状态 / 欢迎页

- 大号欢迎标语 + 居中搜索框
- 下方展示 Discover 标签页内的精选热门话题
- 搜索框内带 focus 选择器、附件按钮、Pro Search 开关
- 左侧边栏显示搜索历史和已保存 Spaces

### 1.7 高级感来源

1. **编辑式排版** — 借鉴杂志设计的权威感和可信度
2. **极度克制的色彩** — 几乎只有青色一个强调色
3. **"超现实但复古"的美学** — 品牌调性独特
4. **大量留白** — 网站和应用界面均以白色空间为主
5. **引用优先** — 将可验证性作为核心 UX 差异化

---

## 二、ChatGPT (GPT-4o 时代) — 对话式 AI UI

### 2.1 布局 (Layout)

| 属性 | 值 |
|------|-----|
| 消息最大宽度 | `48rem` (768px)，`.rounded-3xl.bg-token-message-surface` |
| 消息内边距 | `padding: 4px 0px 30px 0px` |
| 侧边栏 | 浮动模式 (floating)，不推挤内容，软性消失 (soft dismiss) |
| 侧边栏宽度 | ~260px (社区脚本参考值) |
| 文本区最大高度 | `65dvh` |
| 输入框 | 底部固定，圆角矩形 |

### 2.2 字体 (Typography)

| 属性 | 值 |
|------|-----|
| 品牌字体 | OpenAI Sans (2025年初发布，5个字重 + 对应斜体) |
| 界面字体 | Söhne (Klim Type Foundry 商业字体) |
| 字体栈 | `"Söhne", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif` |
| 代码输入框 | Victor Mono |
| Logo 字体 | SF Pro Display Heavy |
| 基础字号 | 16px (1rem, Tailwind 默认) |
| 正文样式 | `.text-base` 类 |

### 2.3 色彩系统 (Color System)

| 角色 | 色值 |
|------|------|
| 品牌色 (Sea Nymph) | `#74AA9C` |
| 暗色主背景 (历史版本) | `#343541` |
| 暗色主背景 (当前) | `#212121` |
| 消息表面 | `#303030` (`.bg-token-message-surface`) |
| 暗色色阶 | `#141414` → `#282828` → `#3c3c3c` |
| 主文字 (暗模式) | `#C0C0C0` |
| 标题文字 | `#fff` |
| 加粗文字 | `#e5fdff` |
| 链接色 | `#53b7ff` |
| CSS 变量 | `var(--main-surface-secondary)`, `var(--token-message-surface)` |
| 主题系统 | 支持自定义强调色，应用于气泡、语音按钮、选中文字 |

### 2.4 聊天 UI

- **消息样式**: 用户消息使用 `.rounded-3xl` 圆角气泡，AI 回复无显式气泡
- **代码块**: 独立背景色区域，带语言标签和复制按钮
- **流式输出**: 逐字出现的打字机效果 + 闪烁光标
- **光标动画**: SVG + CSS `@keyframes flicker` 动画，`0.5s infinite`
- **思考指示器**: 脉冲点 + "AI is responding..." 文字
- **自动滚动**: 随新内容流式输出自动向下滚动

### 2.5 空状态 / 欢迎页

- 居中大号 "ChatGPT" 标题
- 下方排列建议提示词 (starter prompts) 卡片
- 底部输入框带模型选择器
- 整体设计极简，引导用户直接开始对话

### 2.6 导航

- **侧边栏**: 浮动式，悬停时出现，离开时 soft dismiss 淡出
- **对话历史**: 按时间分组（今天、昨天、过去7天等）
- **模型切换**: 输入框上方的下拉选择器

### 2.7 高级感来源

1. **Söhne 字体** — 商业高端字体，几何但不冷漠
2. **浮动侧边栏** — 不打断内容流的优雅导航
3. **极窄内容区** — 48rem 限制保证最佳阅读体验
4. **流式动画** — 打字机效果 + 闪烁光标创造"正在思考"的拟人感
5. **CSS Token 系统** — 完整的 `--token-*` 变量体系保证主题一致性

---

## 三、Vercel AI Chat / v0.dev — 开发者导向的 AI 聊天

### 3.1 技术栈与设计系统

| 属性 | 值 |
|------|-----|
| CSS 框架 | Tailwind CSS v4 |
| 组件库 | shadcn/ui |
| 基础色板 | Zinc (`"baseColor": "zinc"`) |
| 字体 | Geist Sans + Geist Mono |
| 主题方式 | CSS 自定义属性 (`globals.css`) + `@theme` 指令 |
| 认证 | Auth.js for Next beta |

### 3.2 Geist 字体系统

| Token | 字号 | 备注 |
|-------|------|------|
| `--text-xs` | 12px | 辅助信息 |
| `--text-sm` | 14px | 次要内容 |
| `--text-base` | 16px | 正文基准 |
| `--text-lg` | 18px | 小标题 |
| `--text-xl` | 24px | 章节标题 |
| `--text-2xl` | 32px | 页面标题 |
| `--text-3xl` | 48px | 大标题 |
| `--text-display` | 64px | 展示用 |

| 行高 | 值 |
|------|-----|
| `--leading-tight` | 1.15 |
| `--leading-base` | 1.5 |
| `--leading-relaxed` | 1.625 |

| 字间距 | 值 |
|--------|-----|
| `--tracking-tight` | -0.04em |
| `--tracking-normal` | -0.01em |

**Geist 特点**: 比 Inter 字间距更紧 (默认负值)，给文字更"被设计过"的感觉。高 x-height 提升跨尺寸的可读性。9 个可变字重 (100-900)。无斜体，用字重对比做强调。

### 3.3 CSS 变量系统 (shadcn/ui)

```css
/* 语义化背景/前景对 */
--background / --foreground
--card / --card-foreground
--popover / --popover-foreground
--primary / --primary-foreground
--secondary / --secondary-foreground
--muted / --muted-foreground
--accent / --accent-foreground
--destructive / --destructive-foreground
--border
--ring

/* 侧边栏专用 */
--sidebar-background
--sidebar-foreground
--sidebar-primary
--sidebar-accent
--sidebar-border
```

暗色模式通过 `.dark` 选择器覆盖相同变量实现。

### 3.4 聊天模板功能

- **并排 UI**: 输出和聊天消息同时在屏幕上显示
- **模型切换器**: 支持 Mistral, Moonshot, DeepSeek, OpenAI, xAI
- **生成式 UI**: 根据工具调用动态渲染 UI 组件（如天气卡片）
- **AI Elements**: 替代原 ChatSDK，提供更灵活的 AI 界面构建块

### 3.5 高级感来源

1. **Geist 字体** — Vercel 专属开源字体，融合 Swiss 设计精髓
2. **负字间距** — 紧凑而精致的文字排列
3. **shadcn/ui** — 语义化 token 系统保证跨主题一致性
4. **Tailwind v4** — 最新 CSS 工具链的技术先进感
5. **生成式 UI** — 不只是文字回复，而是动态渲染结构化内容

---

## 四、Dify.ai — 开源 RAG 平台

### 4.1 布局

| 属性 | 值 |
|------|-----|
| 前端框架 | Next.js |
| 样式方案 | Tailwind CSS (混合 CSS Modules) |
| 整体布局 | 左侧边栏导航 + 中央工作区 (画布/对话) |
| 工作流编辑器 | 拖拽式可视化画布 |
| 渲染方式 | 大量 `'use client'`，基本为 CSR |

### 4.2 设计特点

- **亮色为主**: 以白色/浅灰为主背景
- **暗色模式**: 长期社区呼吁功能，GitHub issues #2015 (2024.01) 和 #13508 (2025.02) 均提出需求
- **配色风格**: 偏企业化、正式，品牌蓝为主强调色
- **组件风格**: 清爽现代，大量卡片式布局
- **工作流画布**: 节点 + 连线式 DAG 编辑器

### 4.3 聊天 UI

- **WebApp 模板**: 提供 MIT 开源的 SDK 和前端模板
- **对话界面**: 标准聊天气泡布局
- **多模态**: 支持文档上传、图片输入

### 4.4 高级感来源

1. **拖拽工作流** — 降低复杂性的可视化编程
2. **Prompt IDE** — 专业的提示词调试环境
3. **企业级感受** — 干净、功能导向的界面设计
4. **弱设计系统** — 早期缺乏统一设计系统，属于功能优先型产品

---

## 五、RAGFlow — 开源 RAG 引擎

### 5.1 技术栈

| 属性 | 值 |
|------|-----|
| 前端框架 | React + TypeScript |
| 构建框架 | UmiJS (配置文件 `.umirc.ts`) |
| UI 组件库 | Ant Design (antd) |
| 样式方案 | LESS |
| 部署 | Nginx 静态服务 |

### 5.2 布局

- **管理后台**: 标准 Ant Design 后台布局 — 顶部导航 + 侧边栏 + 内容区
- **知识库管理**: 文档列表 + 分块预览面板
- **对话界面**: 标准聊天布局
- **工作流编辑器**: 可视化 DAG 编辑器，节点表示管线各阶段

### 5.3 设计特点

- **Ant Design 默认风格**: 蓝色主题 (`#1677ff`)，标准间距和圆角
- **主题定制**: 通过 `.umirc.ts` 中的 `theme` 字段配置 antd 主题变量
- **功能导向**: 重点在分块可视化和检索质量调试
- **信息密度高**: 文档管理和分块预览面板展示大量元数据

### 5.4 高级感来源

1. **分块可视化** — 独特的 USP，让用户看到文档如何被切分
2. **人工干预** — 用户可校验和调整 AI 输出
3. **专业工具感** — 面向技术用户的高信息密度界面
4. **标准 Ant Design** — 成熟组件库保证基本质量，但缺乏品牌差异化

---

## 六、Coze (ByteDance) — AI Bot 构建器

### 6.1 技术栈

| 属性 | 值 |
|------|-----|
| 前端 | React + TypeScript |
| 后端 | Golang |
| 架构 | 微服务 + DDD (领域驱动设计) |
| 最低配置 | 双核 CPU + 4GB 内存 |

### 6.2 设计系统 (Coze Design System)

| 属性 | 值 |
|------|-----|
| 组件数量 | 66 个 |
| 组件分类 | Action & Menu, Status, Selection & Input, Content, Presentation, Navigation & Layout |
| 页面覆盖率 | >50%，部分页面 100% |
| 暗色模式 | 计划中（目标用户为开发者） |
| 风格演进 | 从"商务正式"向"有趣有个性 + 极客味"转变 |

### 6.3 布局

- **Bot 构建器**: 可视化拖拽界面，无代码/低代码
- **工作流编辑器**: 节点连线式画布
- **模块化**: Cards 模式，可跨 Bot 复用 prompt、工具和逻辑块
- **多平台部署**: 预览面板支持 Discord, WhatsApp, Telegram 等

### 6.4 设计理念

- **图标系统**: 设计师在 Figma 中维护"购物车"式图标收集流程，按 Coze 图标设计规范调整后上传 IconBox
- **移动端**: 正在从原子组件到复杂组件逐步建设移动端组件库
- **使用指南**: 每个组件附带用法指南和最佳实践

### 6.5 高级感来源

1. **完整设计系统** — 从 Style 到 Resource 到 Component 到 Pattern 的全覆盖
2. **可视化编排** — 拖拽节点创建复杂工作流的直观感
3. **"极客味"的品牌调性** — 有意识地从企业风转向开发者友好
4. **跨平台部署预览** — 构建即可预览在各社交平台上的表现

---

## 七、Cursor — AI 代码编辑器 (Chat Panel)

### 7.1 布局

| 属性 | 值 |
|------|-----|
| 基于 | VS Code Fork |
| Chat 面板 | 侧边栏集成，`Ctrl+L` / `Cmd+L` 打开 |
| Agent 面板 | `Ctrl+Shift+A` / `Cmd+Shift+A` |
| 主题系统 | VS Code 主题兼容 + Cursor 专属定制 |
| CSS 变量 | `--vscode-editor-background`, `--vscode-sideBar-background` |

### 7.2 Chat Panel 样式

| 选择器 | 用途 |
|--------|------|
| `.anysphere-markdown-container-root` | 聊天主文字 |
| `.view-line` | 代码行 |
| `.aislash-editor-input` | 聊天输入框 |

**推荐字号配置** (通过 APC Customize UI++ 扩展):
- 聊天文字: 16px
- 代码行: 14px
- 输入框: 15px

### 7.3 Cursor 2.0 UI 重设计

- **Agent-Centric**: 从"VS Code + 聊天面板"转变为 Agent、Plan、Run 作为一等公民
- **多 Agent 并行**: 可同时运行多个 Agent（重构、修测试、UI 打磨），像切换终端一样切换
- **Plan Mode**: 输入 prompt 选择 "plan"，Cursor 爬取项目生成可编辑 Markdown 计划
- **Visual Editor** (2.2, 2025.12): 拖拽重排、React props 侧边栏、滑块/取色器控件、点击+提示交互

### 7.4 高级感来源

1. **深度集成** — LLM 直接整合到渲染管线，不是简单的聊天面板附加
2. **Agent-Centric 布局** — 将 AI 交互提升为核心工作流
3. **多 Agent 并行** — "小团队 of agents" 的心智模型
4. **Visual Editor** — 跨越设计与代码的界限
5. **暗色优先** — 与开发者偏好的编码环境一致

---

## 八、Linear — 应用 UI 密度与打磨的黄金标准

### 8.1 字体

| 属性 | 值 |
|------|-----|
| 主字体 | Inter UI |
| 字体栈 | `"Inter UI", "SF Pro Display", -apple-system, system-ui, "Segoe UI", Roboto, ...` |
| 大标题 | 62px, weight 800, line-height 72px |
| 内容文字 | 20px, weight 400, line-height 31px |
| 导航标签 | 12px, weight 600, 大写, letter-spacing 11px |

### 8.2 色彩系统

| 属性 | 值 |
|------|-----|
| 色彩空间 | LCH (替代 HSL，感知均匀) |
| 主题定义 | 仅 3 个变量: base color, accent color, contrast |
| 品牌色 | Indigo 紫, Woodsmoke 深灰, Oslo Gray 中性灰, Black Haze, White |
| 次要文字 | `#95A2B3` |
| 主标题文字 | `#F7F8F8` |
| 暗色优先 | 基于工程师偏好的黑色编码环境 |
| 自定义主题 | 70+ 开源主题 (linear.style) |
| 对比度变量 | 支持自动生成超高对比度无障碍主题 |

### 8.3 布局与信息密度

- **侧边栏**: 较前暗几个色调，让主内容区占据视觉优先级
- **标签栏**: 更紧凑，圆角 + 缩小图标和文字尺寸
- **显示选项**: 可切换显示 Issue ID、Priority、Status、Labels、Project 等属性
- **布局模式**: List, Board, Timeline, Split, Fullscreen
- **图标策略**: 减少使用量，缩小尺寸，移除彩色团队图标背景
- **边框处理**: 圆角化边缘 + 软化对比度，给结构但不杂乱

### 8.4 导航

- **侧边栏**: Projects, Issues, Initiatives, Statuses 用图标辅助识别
- **标签栏**: 图标 + 文字标签，紧凑布局
- **偏好设置**: 可调字号，可选指针光标，可选主题

### 8.5 设计哲学

> "不是界面的每个元素都应该有相同的视觉权重。用户任务核心的部分保持焦点，辅助定位和导航的部分应该退后。"

- **表面层级**: LCH 色彩空间处理不同海拔 (background → foreground → panels → dialogs → modals)
- **边框克制**: 发现边框在平台中悄然增殖，有意识地清理并软化
- **信息密度平衡**: 高密度但不杂乱 — 通过视觉层级而非留白来组织

### 8.6 高级感来源

1. **LCH 色彩系统** — 感知均匀的主题生成，3 个变量控制全局
2. **"更安静的界面"** — 有意识地降低导航噪音，让工作区成为焦点
3. **Inter 字体** — 专为 UI 设计的字体，大 x-height 保证可读性
4. **图标极简主义** — 减少、缩小、去色，只保留必要的视觉线索
5. **边框作为结构而非装饰** — 圆角化 + 软对比度

---

## 九、横向对比与共性总结

### 9.1 布局模式对比

| 产品 | 内容区宽度 | 侧边栏模式 | 特色布局 |
|------|-----------|-----------|---------|
| Perplexity | 42rem (672px) | 固定左侧栏 | 回答+来源双栏 |
| ChatGPT | 48rem (768px) | 浮动式 | 单列对话流 |
| Vercel Chat | shadcn 默认 | 侧边栏组件 | 并排输出+对话 |
| Dify | 全宽工作区 | 固定左导航 | 拖拽画布 |
| RAGFlow | Ant Design 默认 | 固定左导航 | 分块预览面板 |
| Coze | 全宽工作区 | 固定左导航 | 节点连线画布 |
| Cursor | 编辑器+面板 | VS Code 侧栏 | Agent 并行面板 |
| Linear | 自适应 | 可调暗度侧栏 | List/Board/Timeline |

### 9.2 字体选择对比

| 产品 | 字体 | 类型 |
|------|------|------|
| Perplexity | FK Grotesk | 商业字体，编辑式 |
| ChatGPT | Söhne / OpenAI Sans | 商业字体，几何精密 |
| Vercel | Geist Sans/Mono | 自研开源，Swiss 风格 |
| Dify | 系统字体 | 无自定义品牌字体 |
| RAGFlow | Ant Design 默认 | 系统字体 |
| Coze | 待定 | 正在建设设计系统 |
| Cursor | VS Code 默认 | 编辑器字体继承 |
| Linear | Inter | 开源，专为 UI 设计 |

### 9.3 暗色模式对比

| 产品 | 暗色主背景 | 方式 | 特色 |
|------|-----------|------|------|
| Perplexity | `#1a1a1a` | 强制暗色 | 青色高亮 |
| ChatGPT | `#212121` | 可选 | Token 变量系统 |
| Vercel | Zinc 色阶 | `.dark` 覆盖 | HSL CSS 变量 |
| Dify | 无 | 社区呼吁中 | — |
| RAGFlow | Ant Design | 内置 | 标准 antd 暗色 |
| Coze | 计划中 | 开发者需求 | — |
| Cursor | `#1e1e1e` | VS Code 主题 | 编辑器/侧栏分离 |
| Linear | LCH 生成 | 3 变量控制 | 感知均匀主题 |

### 9.4 微交互共性

| 模式 | 实现 | 时长 |
|------|------|------|
| Hover 状态 | 颜色变化/缩放 | 150-200ms |
| 流式打字 | 逐字出现 + 闪烁光标 | 实时 |
| 骨架屏加载 | Shimmer 渐变动画 | 1-2s 循环 |
| 按钮反馈 | 颜色/缩放变化 | 300-500ms |
| 页面转场 | Fade / Slide | 200-300ms |
| 光标闪烁 | CSS keyframes | 0.5s infinite |

---

## 十、对 MimirQ 的设计启示

### 10.1 必须做到的基础

1. **内容区限宽**: 42-48rem (672-768px)，保证最佳阅读行宽
2. **暗色模式**: 使用 `#1a1a1a` ~ `#212121` 的深灰（非纯黑），3-4 级表面层级
3. **语义化 CSS 变量**: 参考 shadcn/ui 的 `--background/--foreground` 对模式
4. **流式输出动画**: 打字机效果 + 闪烁光标是 AI 聊天的标配
5. **引用/来源展示**: RAG 产品必须有清晰的来源引用 UI — Perplexity 的行内脚注 + 右侧面板是最佳实践

### 10.2 差异化机会

1. **字体选择**: 使用 Geist (开源) 或 Inter 作为基础字体，考虑中文搭配
2. **LCH 色彩系统**: 参考 Linear 的 3 变量主题生成，实现高质量自定义主题
3. **信息密度控制**: 参考 Linear 的"不是每个元素都应等权重"原则
4. **编辑式排版**: 参考 Perplexity 的杂志式信息呈现
5. **引用卡片**: 设计可展开的来源预览卡片，带 favicon + 标题 + 摘要

### 10.3 推荐设计参数

```css
/* 字体 */
--font-sans: 'Geist', 'Inter', -apple-system, system-ui, sans-serif;
--font-mono: 'Geist Mono', 'SFMono-Regular', monospace;

/* 字号 */
--text-xs: 12px;    /* 辅助信息 */
--text-sm: 14px;    /* 次要内容、侧边栏 */
--text-base: 16px;  /* 正文 */
--text-lg: 18px;    /* 小标题 */
--text-xl: 24px;    /* 区域标题 */

/* 行高 */
--leading-tight: 1.2;    /* 标题 */
--leading-normal: 1.5;   /* 正文 */
--leading-relaxed: 1.625; /* 长文阅读 */

/* 字间距 */
--tracking-tight: -0.02em;  /* 标题 */
--tracking-normal: -0.01em; /* 正文 */

/* 暗色模式表面层级 */
--surface-0: #0a0a0a;  /* 最深背景 */
--surface-1: #141414;  /* 侧边栏 */
--surface-2: #1a1a1a;  /* 主内容区 */
--surface-3: #242424;  /* 卡片/浮层 */
--surface-4: #2a2a2a;  /* 悬浮态 */
--surface-5: #333333;  /* 活跃态 */

/* 布局 */
--content-max-width: 44rem;  /* 704px, Perplexity 和 ChatGPT 的折中 */
--sidebar-width: 260px;
--spacing-unit: 4px;         /* 4px 基础网格 */

/* 动画 */
--transition-fast: 150ms ease;
--transition-normal: 200ms ease;
--transition-slow: 300ms ease;
--cursor-blink: 0.5s infinite;

/* 圆角 */
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-xl: 16px;    /* 消息气泡 */
--radius-full: 9999px; /* 按钮/标签 */
```

### 10.4 高级感核心原则

1. **克制用色** — 不超过 1 个强调色 + 语义色 (成功/警告/错误/信息)
2. **表面层级** — 用背景色深浅替代边框来表达层级
3. **负字间距** — 标题使用 `-0.02em` ~ `-0.04em` 的紧凑排版
4. **一致的间距系统** — 4px 基础网格，8px 为主要间距单位
5. **细节动画** — hover 200ms, 流式打字机, 骨架屏 shimmer
6. **视觉权重分级** — 核心工作区最亮，导航退后，辅助信息最暗

---

## 参考来源

### Perplexity AI
- [Perplexity Brand Guidelines (2026)](https://live.standards.site/perplexity/color)
- [Perplexity Design Tokens - FontOfWeb](https://fontofweb.com/tokens/perplexity.ai)
- [Perplexity UI/UX - SaaSUI](https://www.saasui.design/application/perplexity-ai)
- [Perplexity Branding - Designhoops](https://designhoops.com/perplexity-branding/)
- [Jitter x Perplexity Motion](https://jitter.video/customers/perplexity/)
- [FK Grotesk - Florian Karsten](https://fonts.floriankarsten.com/fk-grotesk)

### ChatGPT
- [ChatGPT UI Width Fix - GitHub](https://gist.github.com/alexchexes/d2ff0b9137aa3ac9de8b0448138125ce)
- [ChatGPT Font Analysis - Subframe](https://www.subframe.com/tips/what-font-does-chatgpt-use)
- [OpenAI Apps SDK UI Guidelines](https://developers.openai.com/apps-sdk/concepts/ui-guidelines)
- [ChatGPT Font Details - PromptPerfect](https://daily.promptperfect.xyz/p/what-font-does-chatgpt-use)
- [ChatGPT Sidebar Redesign](https://www.ai-toolbox.co/chatgpt-management-and-productivity/chatgpt-sidebar-redesign-guide)
- [LibreChat ChatGPT Fonts](https://gist.github.com/danny-avila/e1d623e51b24cf0989865197bb788102)

### Vercel AI Chat
- [Geist Font](https://vercel.com/font)
- [Geist Design System](https://vercel.com/geist/introduction)
- [Vercel AI Chatbot Template](https://vercel.com/templates/next.js/nextjs-ai-chatbot)
- [shadcn/ui Theming](https://ui.shadcn.com/docs/theming)
- [Vercel AI Elements](https://vercel.com/changelog/introducing-ai-elements)
- [Vercel Design System Breakdown - SeedFlip](https://seedflip.co/blog/vercel-design-system)

### Dify.ai
- [Dify GitHub](https://github.com/langgenius/dify)
- [Dify Frontend Discussion](https://github.com/langgenius/dify/discussions/4014)
- [Dify Dark Mode Issue](https://github.com/langgenius/dify/issues/13508)

### RAGFlow
- [RAGFlow GitHub](https://github.com/infiniflow/ragflow)
- [RAGFlow Official](https://ragflow.io/)
- [RAGFlow Source Setup](https://ragflow.io/docs/dev/launch_ragflow_from_source)

### Coze
- [Coze Design System - Han Zhao](https://zhaohan.design/coze/)
- [Coze Studio GitHub](https://github.com/coze-dev/coze-studio)
- [Coze Official Docs](https://www.coze.com/open/docs/developer_guides/ui-builder-preview)

### Cursor
- [Cursor Features](https://cursor.com/features)
- [Cursor 2.0 Guide - Skywork](https://skywork.ai/blog/vibecoding/cursor-2-0-ultimate-guide-2025-ai-code-editing/)
- [Cursor Themes Docs](https://cursor.com/docs/configuration/themes)
- [Cursor Chat Font Size Forum](https://forum.cursor.com/t/changing-chat-panel-font-size-line-height-easily/375)

### Linear
- [Linear UI Redesign Part II](https://linear.app/now/how-we-redesigned-the-linear-ui)
- [Linear Design Refresh 2025](https://linear.app/now/behind-the-latest-design-refresh)
- [Linear Brand Guidelines](https://linear.app/brand)
- [Linear Design Trend - LogRocket](https://blog.logrocket.com/ux-design/linear-design/)
- [Linear Brand Colors - Mobbin](https://mobbin.com/colors/brand/linear)

### 通用设计系统参考
- [AI Chat UI Libraries 2026 - DEV.to](https://dev.to/alexander_lukashov/i-evaluated-every-ai-chat-ui-library-in-2026-heres-what-i-found-and-what-i-built-4p10)
- [Micro Animation Examples 2025 - BricxLabs](https://bricxlabs.com/blogs/micro-interactions-2025-examples)
- [Dark Mode Best Practices 2025 - UI Deploy](https://ui-deploy.com/blog/complete-dark-mode-design-guide-ui-patterns-and-implementation-best-practices-2025)
