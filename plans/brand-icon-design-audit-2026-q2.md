# MimirQ 品牌与图标设计审核（2026 Q2）

> 项目内 34 个自有图标资产逐一盘点：哪些是**占位/临时**必须重做、哪些是**模板化/风格冲突**建议重做、哪些**保留即可**。为每个需要重做的图标给出可直接喂给 AI 出图工具（Midjourney / GPT-Image / Claude）或人工设计师的**双语提示词 + 输出规格**。
>
> 创建日期：2026-05-18
> 来源：`/knowledge/ingestion` 页面 UI 检查中发现 sidebar logo 是黑底字符 "M" 占位 → 触发全量品牌资产审核
> 关联：`plans/rag-ingestion-frontend-deep-dive-2026-q2.md`（页面级 UI 优化）
>
> **核心一句话**：品牌主 logo + 4 个 favicon 变体 + 29 个功能图标 = 34 个资产，其中 **4 个 P0 必须重做（logo + favicon 全套是字母 "M" 占位）**、**29 个 P1 建议矢量化 + 风格审查**（page-title-icons 现为统一蓝色 3D 卡通风但缺品牌识别度），其余保留。1-2 周可完成完整品牌视觉系统升级。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 资产盘点（34 个自有图标 + 第三方 logo 不动） |
| 第 2 章 | 现状问题分类（占位 / 模板化 / 风格冲突） |
| 第 3 章 | MimirQ 品牌世界观（设计原则与色彩世界） |
| 第 4 章 | P0 品牌核心：主 Logo + 4 个 Favicon（5 个资产 + 提示词） |
| 第 5 章 | P1 功能图标：page-title-icons 29 个（决策树 + 全量提示词清单） |
| 第 6 章 | P2 补充资产：OG image / Empty state / Loading（可选） |
| 第 7 章 | 输出规格清单（SVG/PNG/sizes/light-dark） |
| 第 8 章 | 落地里程碑（Day 1-10） |
| 第 9 章 | 决策门槛与陷阱清单 |
| 第 10 章 | 范围之外 |

---

## 1 资产盘点

### 1.1 自有图标（34 个）

| # | 资产 | 路径 | 当前形式 | 用途 | 优先级 |
|---|---|---|---|---|---|
| 1 | Sidebar Logo | `web/components/navbar.tsx:524-535`（DOM 内联） | 黑底圆角方块 + 大写字母 "M" | 侧栏品牌位 | **P0** |
| 2 | PWA 主图标 | `web/public/icon.svg` (512×512) | 蓝色渐变方块 + 半透明对话气泡 + 3 圆点 | PWA 安装、App 切换器 | **P0** |
| 3 | Favicon（彩色） | `web/public/favicon.svg` (32×32) | 蓝紫渐变方块 + 白色 "M" 字母 | 浏览器 tab、书签 | **P0** |
| 4 | Favicon Light | `web/public/favicon-light.svg` (64×64) | 浅底深色 "M" 字母 | 浅色系统/打印 | **P0** |
| 5 | Favicon Dark | `web/public/favicon-dark.svg` (64×64) | 深底浅色 "M" 字母 | 深色系统/夜间模式 | **P0** |
| 6-34 | page-title-icons | `web/public/page-title-icons/*.png` × 29 (256×256) | 蓝色 3D 卡通风（macOS Big Sur 风格） | 页面标题装饰 | **P1** |

### 1.2 不需要重做（保留）

- `web/public/logos/*.svg|png` — 第三方 LLM/embedding provider logo（anthropic / openai / dashscope / deepseek / qwen / moonshot / siliconflow / ollama / openrouterai / qianfan / lingyiwanwu / ark / lobehub/ 子集 等）→ **属于品牌方知识产权，不能改**
- `web/public/noise.svg` — 背景噪点纹理，纯装饰，保留
- `web/public/lottie/` — 空目录，占位
- `web/public/pdfjs/`、`pdfjs-compat/`、`monaco/` — 第三方库自带资源，不动

### 1.3 资产分布可视化

```
web/public/
├── icon.svg ........................ P0 [模板化 ChatGPT 风格，需重做]
├── favicon.svg ..................... P0 [字母 M 占位]
├── favicon-light.svg ............... P0 [字母 M 占位]
├── favicon-dark.svg ................ P0 [字母 M 占位]
├── noise.svg ....................... ✓ 保留
├── lottie/ ......................... ⌀ 空目录
├── page-title-icons/ × 29 .......... P1 [统一卡通风，缺品牌识别]
└── logos/ .......................... ✓ 第三方品牌，不改

web/components/navbar.tsx:527-528 ... P0 [黑底字符 "M" 占位 DOM]
```

---

## 2 现状问题分类

### 2.1 占位（Placeholder）——**必须重做**

- **navbar.tsx 内的 "M"**：直接用 `<span className="font-bold text-lg">M</span>`，连图都不是
- **favicon.svg / favicon-light.svg / favicon-dark.svg**：3 个都是矩形 + 字母 "M"，**没有任何独特视觉记忆点**

### 2.2 模板化（Template）——**建议重做**

- **icon.svg**：蓝色渐变方块 + 对话气泡 + 3 圆点 → **撞 ChatGPT / Claude / Gemini 视觉**，几乎所有 LLM 产品都用对话气泡，无差异化
- **page-title-icons 整套**：蓝色 3D 卡通 + 立体阴影 + 双色渐变 → **macOS Big Sur 风格批量出品**，看起来像 App Store 通用应用图标库，缺乏数据治理/RAG 工程的专业视觉语言

### 2.3 风格不一致

- **navbar 的 logo**（黑底+白字）与 **favicon**（蓝紫渐变）与 **icon.svg**（蓝色渐变+白气泡）**互不一致** → 用户在不同入口看到的"品牌"不是同一个东西

### 2.4 技术问题

- **page-title-icons 全部是 PNG 而非 SVG** → 缩放后糊、无法注入 CSS 变量、无法做 light/dark 双版本
- **PNG 平均 30-40KB × 29 = ~1MB 资产**，全部矢量化后可压到 ~200KB

---

## 3 MimirQ 品牌世界观

设计前先定方向。否则提示词会变成"现代、简洁、专业"——每个 AI 都会输出一样的结果。

### 3.1 产品定位

- **类别**：企业级 RAG 知识库与检索智能体平台
- **用户**：知识库运营、数据工程师、IT 与合规专员、行业 SaaS 客户的领域专家
- **使用场景**：日常工作台（不是消费 App），重密度、重信赖、重专业
- **竞品视觉对标**：Linear（克制理性）/ Vercel（极简精密）/ Notion（克制实用）/ Glean（企业稳重）；**避开** ChatGPT（对话气泡）/ Midjourney（艺术感）/ 大多数中国 SaaS（橙紫渐变 + 卡通插画）

### 3.2 品牌词源

- **MimirQ** = **Mimir**（北欧神话中守护知识泉源的智者，献出一只眼换取智慧）+ **Q**（Query / Question / Quest）
- 隐喻：**守护者 + 知识泉 + 凝视/洞察 + 提问**

### 3.3 视觉世界（不是 "warm" / "cool" 这种空话）

| 维度 | 选择 | 理由 |
|---|---|---|
| **氛围** | 沉静、密集、可信赖 | 工作台不是娱乐产品，操作者每天 8h 盯屏，不能花哨 |
| **形态语言** | 几何 + 略带北欧符文/书页质感的克制装饰 | 呼应 Mimir 词源；区别于纯几何（太冷）和纯插画（太花） |
| **核心色（建议）** | 主色：**深靛蓝 #1B2A4E**（夜空、知识泉水深处）<br/>辅色：**金箔黄 #C9A96E**（古籍烫金、Mimir 神话感）<br/>中性：**石板灰 #475569 / 羊皮纸 #F5F1E8** | 现有 `#3b82f6` 蓝太"互联网通用"，建议沉一档 |
| **形态符号** | 凝视的眼（Mimir 献眼意象） / 水波纹（知识泉） / 三角节点（图谱）/ 书页角 | 至少一个符号必须只属于 MimirQ |
| **拒绝默认** | ✗ 对话气泡（已被 ChatGPT 占领）<br/>✗ 闪电（速度感太消费）<br/>✗ 渐变方块 + 字母（最 templater 的做法）<br/>✗ 紫粉蓝渐变（AI 工具默认色）<br/>✗ 大眼睛卡通脸（消费产品） | — |

### 3.4 一句话设计纲领

> **"克制的智者徽章"**——一个能在 16×16 favicon 看清、又能在 512×512 PWA 图标承载叙事的几何符号。

---

## 4 P0 品牌核心：主 Logo + 4 个 Favicon

### 4.1 设计原则

1. **可识别性优先**：16×16 像素下还能认出 → 形状必须简单（≤3 个核心元素）
2. **单色可读**：先用纯黑/纯白画一遍，看是否成立；通过后再加色彩
3. **方形容器友好**：iOS app icon、Android adaptive icon、PWA、社媒头像 → 必须能在 1:1 圆角方块里完美居中
4. **深浅双模**：light 模式与 dark 模式都要好看，不能依赖渐变（渐变在 dark 模式常常糊）

### 4.2 资产 #1：主 Logo 符号（Logomark）

**当前状态**：navbar 内是 `<span>M</span>`（占位）

**设计提示词（中文）**：

> 为企业级 AI 知识库平台 "MimirQ" 设计一个 logomark（不含文字、纯符号），可读到 16×16 像素：
> - 灵感源自北欧神话守护知识之泉的智者 Mimir（献出一只眼换取智慧），结合 "Query/凝视/洞察" 意象
> - 风格：几何精密 + 略带北欧符文质感，参考 Linear / Vercel 的克制，**避开**对话气泡、闪电、渐变方块 + 字母 M 这些 LLM 工具通用 cliché
> - 核心元素 ≤3 个，建议组合：凝视的眼 + 水波纹 + 三角图谱节点（取其一二，不要全堆）
> - 形态：单色可读、纯黑或纯白画出来就成立；不依赖渐变
> - 输出 SVG 矢量、24×24 与 512×512 双尺寸预览
> - 容器：能完美居中在圆角方形（iOS 风格 squircle, r=0.225×size）
> - 调性词：沉静、密集、可信赖、智者徽章、克制

**English prompt**:

> Design a logomark (symbol only, no text) for "MimirQ", an enterprise AI knowledge base and retrieval platform. Must be legible at 16×16 px.
> - Inspired by Mimir, the Norse keeper of the well of wisdom (sacrificed an eye for knowledge); combine with the concept of "query / gaze / insight"
> - Style: geometric precision with a hint of Norse rune texture. Reference Linear / Vercel restraint. **Avoid** chat bubbles, lightning bolts, gradient squares with letter "M" — all LLM-tool clichés
> - ≤3 core elements. Possible combos: a single watching eye + ripple lines + a triangular graph node. Pick one or two, do not pile up
> - Monochrome legibility: must work in pure black or pure white before adding color
> - Output: SVG vector, render at 24×24 and 512×512
> - Container: centers in iOS squircle (r=0.225×size)
> - Tone: calm, dense, trustworthy, sage's seal, restrained

**输出规格**：
- 主文件：`web/public/brand/logomark.svg`（无背景、纯符号）
- 备份变体：`logomark-monochrome.svg`（单色版，用于水印/印刷）
- 接入位置：替换 `navbar.tsx:527-528` 的 `<span>M</span>`

---

### 4.3 资产 #2：PWA 主图标 `icon.svg`（512×512）

**当前状态**：蓝色渐变圆角方块 + 半透明对话气泡 + 3 圆点 → **模板化 ChatGPT 风**

**设计提示词（中文）**：

> 基于上述 logomark，扩展为 512×512 PWA 主图标：
> - 圆角方形容器（squircle，r=120），承载 logomark 居中
> - 容器底色不要用普通蓝色渐变（cliché）；建议：深靛蓝 #1B2A4E 实色 + 极轻 noise 纹理（呼应北欧古籍质感）
> - logomark 用金箔黄 #C9A96E 描线 + 内部留羊皮纸色高光（极微弱，约 8% 透明度）
> - 内边距：logomark 占容器 60-65%（不要顶满）
> - 阴影：极轻 inner shadow（drop shadow 容易被 OS 二次添加，反而模糊）
> - 输出 512×512 SVG，可放大到 1024 不糊

**输出规格**：
- 替换 `web/public/icon.svg`
- 同时生成 `apple-icon.png` 180×180、`icon-192.png`、`icon-512.png`（PWA manifest 需要 raster）

---

### 4.4 资产 #3-5：Favicon 三件套

**当前状态**：3 个 SVG 都是矩形 + 字母 "M"，**完全相同的结构**

**Favicon 设计的关键约束**：
1. **16×16 与 32×32 必须辨认** → 复杂图形会糊成一团
2. **浏览器 tab 通常浅灰底** → favicon 主色不能是浅灰
3. **macOS dark mode 会自动反色** → 提供 light/dark 两版

**设计提示词（中文，三个版本统一）**：

> 基于 logomark 简化版，为 favicon 出 3 个变体（同一符号 3 种配色）：
> - **`favicon.svg`（默认 / 彩色）**：深靛蓝 #1B2A4E 圆角方底（r=6） + 金箔黄 #C9A96E 符号
> - **`favicon-light.svg`（浅色系统）**：无底（透明）+ 深靛蓝 #1B2A4E 符号
> - **`favicon-dark.svg`（深色系统）**：无底（透明）+ 羊皮纸 #F5F1E8 符号
> - 16×16 / 32×32 / 64×64 三档预览必须都清晰
> - 如果原 logomark 在 16×16 糊了，必须做**简化符号**（去掉细节、保留主形）

**输出规格**：
- 替换 `web/public/favicon.svg`（viewBox 0 0 32 32）
- 替换 `web/public/favicon-light.svg`（viewBox 0 0 64 64）
- 替换 `web/public/favicon-dark.svg`（viewBox 0 0 64 64）

---

### 4.5 资产 #6：Wordmark（品牌字 "MimirQ"）

**当前状态**：navbar 用普通字体 + `font-semibold` 直接渲染

**设计提示词（中文）**：

> 为 "MimirQ" 字样设计 wordmark：
> - 不要用现成字体直接打字 → 至少做 3 个字符的微调（字距 / 边角）
> - 字形参考：Inter Display SemiBold / Söhne / Migra 这类几何 grotesque
> - 关键字母：**"Q" 是品牌核心字母**（Query/Quest），允许做一个独特处理（如尾巴延伸成水波纹、或眼睛圆点取代圆圈）
> - 提供单行 SVG 矢量与 PNG 透明背景两套
> - 颜色：黑色（#1B2A4E）+ 白色（#F5F1E8）两版

**输出规格**：
- `web/public/brand/wordmark.svg`
- `web/public/brand/wordmark-white.svg`
- 接入位置：navbar.tsx 530-531 行替换文字标题

---

## 5 P1 功能图标：page-title-icons 29 个

### 5.1 决策树：保留 / 矢量化 / 重做

```
当前 29 个 PNG（蓝色 3D 卡通风）
│
├── 决策 A：保留并矢量化（推荐）
│   ├── 风格不动，把 PNG 转为 SVG（用 vectorizer.ai 或人工 retrace）
│   ├── 同时输出 light/dark 两版（注入 CSS 变量）
│   └── 工作量：~2-3 天，成本最低
│
├── 决策 B：重做为统一品牌风（建议，但贵）
│   ├── 改为线性 + 扁平 + 金箔色描边的统一风格
│   ├── 全部矢量
│   └── 工作量：~5-7 天 + 29 张提示词
│
└── 决策 C：完全删除装饰图标，改用 lucide-react 图标
    ├── 直接用 `lucide-react` 中现成图标
    ├── 工作量：~半天，但失去差异化
    └── 缺点：所有 SaaS 都用 lucide，毫无品牌感
```

**推荐路径**：**先 A 后 B**——P1 阶段先矢量化保留风格统一（不让现状继续烂），P2 阶段再分批换 B 风格。

### 5.2 29 个图标语义清单 + 重做提示词模板

**通用提示词模板（适用于决策 B）**：

> 为 MimirQ 企业知识库平台设计一组功能页面装饰图标（共 29 张），每张表达一个具体功能语义：
> - **统一风格**：线性 stroke + 局部金箔色实心点缀（不是面铺），描边 1.5pt，stroke-linecap=round
> - **配色**：默认 stroke 用 #1B2A4E（深靛蓝），强调点用 #C9A96E（金箔黄），辅助色 #475569（石板灰）
> - **尺寸**：256×256 viewBox，主体占 70%
> - **形态**：几何精密 + 略带北欧符文质感；**避开** 卡通双色渐变、立体阴影、macOS Big Sur 风
> - **可识别**：每张图标必须不依赖 label 就能猜出语义
> - **light/dark 双版本**：通过 CSS 变量切换 stroke 颜色，不依赖图层翻转

**29 张图标语义 + 个性化提示词**：

| # | 文件名 | 中文功能 | 个性化提示词 |
|---|---|---|---|
| 1 | `chat.png` | 对话 / Chat | 两个错位对话节点（不是气泡）+ 一条凝视线连接，**避开**圆角气泡 cliché |
| 2 | `chunk-preview.png` | 切块预览 | 一份长文档被水平虚线分成 3 段，每段编号，金箔色高亮一段 |
| 3 | `parsing.png` | 文档解析 | 文档 + 解析后的结构化树形结构在右侧展开，箭头从左到右 |
| 4 | `dataset.png` | 数据集 | 多个文档堆叠 + 一个金箔色标签角章；不要用磁盘/数据库柱形 cliché |
| 5 | `knowledge-base.png` | 知识库 | 书脊侧视 + 顶部一个凝视的圆点（Mimir 眼），区别于 dataset |
| 6 | `knowledge-graph.png` | 知识图谱 | 5-7 个节点的力导向图缩略，金箔色突出中心节点 |
| 7 | `kg-snapshot.png` | KG 快照 | 知识图谱 + 右下角时钟刻度（表示快照时刻） |
| 8 | `kg-retrieval-evaluation.png` | KG 检索评测 | KG 节点 + 一根标尺/雷达评分 |
| 9 | `knowledge-management.png` | 知识管理 | 文件夹树 + 金箔色一根穿过的整理线 |
| 10 | `ingestion-monitor.png` | 入库监控 | 横向时间轴 + 3-4 个状态节点（运行/完成/失败用形状区分，不用颜色） |
| 11 | `ingestion-operation.png` | 入库操作 | 漏斗 + 文档进入；区别于 monitor 的"运行中"感 |
| 12 | `quarantine-queue.png` | 隔离队列 | 文档 + 一道边界虚线 + 一把简化的锁 |
| 13 | `feedback-quality.png` | 反馈质量 | 大拇指 + 一根质量曲线（非折线图） |
| 14 | `qa-history.png` | 问答历史 | 时间轴 + 多个 Q&A 配对点 |
| 15 | `prompts.png` | 提示词管理 | 卷轴/纸条 + 金箔色字符标记（不要键盘） |
| 16 | `diagnostics.png` | 诊断 | 听诊器太消费——改为：放大镜 + 内部一根波形脉冲线 |
| 17 | `ragas-evaluation.png` | RAGAS 评测 | 雷达图 4-5 维 + 中心点金箔 |
| 18 | `kg-retrieval-evaluation.png` | KG 检索评测 | （同 #8 合并）|
| 19 | `retrieval-ablation.png` | 检索消融 | 多组对比柱（横向）+ 一组金箔色高亮 |
| 20 | `rag-visualization.png` | RAG 可视化 | 三层架构 stack（检索/重排/生成）+ 金箔流向 |
| 21 | `profile-discovery.png` | 数据画像发现 | 直方图 + 一个发现的小放大镜 |
| 22 | `data-governance.png` | 数据治理 | 天平 + 文档；不要用盾牌 cliché |
| 23 | `governance-config.png` | 治理配置 | 滑动条 × 3 + 一根金箔指示 |
| 24 | `audit-log.png` | 审计日志 | 横线 stack（时间线） + 一个签章圆角戳 |
| 25 | `access-review.png` | 访问复核 | 钥匙 + 一双凝视的眼睛 |
| 26 | `members-rbac.png` | 成员 RBAC | 3 个抽象人形 + 角色边框区分 |
| 27 | `group-management.png` | 用户组管理 | 多个人形圈起的圆 + 一根金箔分组线 |
| 28 | `usage-quota.png` | 用量配额 | 容量条 + 刻度 + 金箔满标 |
| 29 | `report-export.png` | 报告导出 | 文档 + 向外的箭头；区别于 ingestion 的"入" |
| 30 | `settings.png` | 设置 | 不用齿轮 cliché——用 3 根滑动条 + 一个开关圆点 |

> 注：编号 17 与 18 重名 `kg-retrieval-evaluation`，应在重做时合并为同一张；总数实际是 29 张（与 `PAGE_TITLE_ICON_NAMES` 一致）。

### 5.3 PageTitleIcon 组件升级

**当前**：`page-title-icon.tsx` 用 `next/image` 加载 PNG。

**升级建议**：
- 把 29 个 SVG inline 进 `web/components/ui/page-title-icon.tsx` 或单独 `web/components/ui/page-title-icons/*.tsx`
- 通过 `currentColor` 与 CSS 变量驱动 light/dark 切换
- 移除 `next/image` 包装、移除 `priority` / `unoptimized` 属性
- 同时删除 `web/public/page-title-icons/*.png`（节省 ~1MB 静态资产）

---

## 6 P2 补充资产（可选 / 视产品需要）

| 资产 | 用途 | 是否当前缺失 | 提示词草稿 |
|---|---|---|---|
| OG image / social-share | 分享链接预览图（Twitter/Slack/Lark） | **缺失** | 1200×630，wordmark + tagline + 抽象 KG 节点背景 |
| Empty state illustration × 3-5 | 空数据集、空检索结果、空反馈、空隔离队列 | **缺失** | 线性 + 金箔点缀，与 page-title-icons 同语言但更大画幅 |
| Loading animation (Lottie) | 入库进度、检索中、生成中 | **缺失**（`lottie/` 是空目录） | 水波纹扩散 / 知识泉涌动，loop 2s |
| 404 / 500 插画 | 错误页 | **缺失** | Mimir 一只眼睛闭合，旁边一个问号 |
| 首页 hero illustration | 营销 / 着陆页 | 暂无登录页大图 | 与 OG image 同源 |

**P2 不在本 plan 强制范围内**，等品牌系统在 P0+P1 跑通后再分批补。

---

## 7 输出规格清单

### 7.1 文件输出表

| 路径 | 格式 | 尺寸 | 说明 |
|---|---|---|---|
| `web/public/brand/logomark.svg` | SVG | 24/512 双尺寸 viewBox | 主符号 |
| `web/public/brand/logomark-monochrome.svg` | SVG | 同上 | 单色备份 |
| `web/public/brand/wordmark.svg` | SVG | 单行 | 字 "MimirQ" |
| `web/public/brand/wordmark-white.svg` | SVG | 单行 | 白色版 |
| `web/public/icon.svg` | SVG | 512×512 | PWA 主图（替换） |
| `web/public/favicon.svg` | SVG | 32×32 | 浏览器 tab（替换） |
| `web/public/favicon-light.svg` | SVG | 64×64 | 浅色（替换） |
| `web/public/favicon-dark.svg` | SVG | 64×64 | 深色（替换） |
| `web/public/apple-icon.png` | PNG | 180×180 | iOS 添加到主屏 |
| `web/public/icon-192.png` | PNG | 192×192 | PWA manifest |
| `web/public/icon-512.png` | PNG | 512×512 | PWA manifest |
| `web/components/ui/page-title-icons/*.tsx` | TSX inline SVG | 256 viewBox | 29 张功能图标 |
| ~~`web/public/page-title-icons/*.png`~~ | — | — | 删除（迁移到 SVG） |

### 7.2 代码接入清单

| 文件 | 修改 |
|---|---|
| `web/components/navbar.tsx:524-535` | 替换 `<span>M</span>` 为 `<Logomark className="size-8" />` + Wordmark 组件 |
| `web/components/ui/page-title-icon.tsx` | 改为 inline SVG 渲染，移除 `next/image` |
| `web/app/manifest.ts:11-19` | 更新 icons 数组指向新文件 + 新增 192/512 PNG |
| `web/app/layout.tsx` | 检查 `<link rel="icon">` / `apple-touch-icon` metadata |
| `web/app/auth/page.tsx` | 登录页 logo 同步替换 |
| `web/i18n/messages/zh-CN/*.ts` | `brand.tagline` 是否需要重写 |

---

## 8 落地里程碑（Day 1-10）

### Phase 1：品牌定调（Day 1-2）

- **Day 1**：与 stakeholder 对齐品牌世界观（第 3 章），确认词源、调性、配色（**关键决策点**：是否接受"靛蓝 + 金箔"方向 or 换其他世界观）
- **Day 2**：基于确认方向生成 3-5 个 logomark 候选稿（用 Midjourney / GPT-Image / 人工设计）→ 内部投票选 1

### Phase 2：P0 品牌核心（Day 3-5）

- **Day 3**：精修选中的 logomark，输出 SVG（含 16×16 简化版）；同步出 wordmark
- **Day 4**：扩展为 icon.svg（PWA 512） + 3 个 favicon 变体；生成 apple-icon.png / icon-192/512.png
- **Day 5**：代码接入：navbar.tsx + manifest.ts + layout.tsx + 登录页 → `pnpm build` + 自测三端（chrome、移动 Safari 添加到主屏、PWA install）

### Phase 3：P1 功能图标（Day 6-10）

- **Day 6**：决策树第 1 步——选 A（矢量化保留）or B（重做为品牌风）→ 若 A 跳到 Day 7、若 B 走 Day 6-10 全程
- **Day 7-8**（B 路径）：分批生成 29 张 SVG（每天 ~15 张），用 5.2 表中的个性化提示词
- **Day 9**：升级 `page-title-icon.tsx` 为 inline SVG 渲染 + 删除 PNG 资产
- **Day 10**：全站浏览验证（每个页面看一遍图标是否符合语义） + 修补不达标的图标

---

## 9 决策门槛与陷阱清单

### 9.1 决策门槛

| 决策点 | 通过标准 | 不通过的处理 |
|---|---|---|
| 品牌世界观（第 3 章） | stakeholder 1 人否决即停 | 重新探索；不要硬上"靛蓝+金箔"如果客户/老板有强烈不同方向 |
| logomark 候选稿 | 至少 1 个在 16×16 仍可识别 | 全部不达标 → 重画（**不要为了交付而妥协**） |
| 是否 P1 全量重做（B 路径） | 团队有 5-7 天预算 | 没有 → 走 A 路径，先矢量化 |
| 上线前的全站验证 | 所有 29 个页面图标语义对得上 | 任何一张语义错（如 "report-export" 看起来像 "ingestion"）必须返工 |

### 9.2 陷阱清单（**已踩过的坑要在 plan 里写明**）

| # | 陷阱 | 后果 | 规避 |
|---|---|---|---|
| 1 | 直接生成"现代简洁的 logo" | AI 输出渐变方块 + 字母 M | 提示词必须含**禁用清单**（cliché 列表） |
| 2 | 只设计大尺寸不验证 16×16 | favicon 上线后糊成一团 | 必须 16×16 早期验证 |
| 3 | 渐变 logo 在 dark mode 失效 | 蓝紫渐变在深色背景几乎不可见 | 单色版优先，渐变只作可选 |
| 4 | 29 张图标统一风格但全部 PNG | 缩放后糊、不能注入主题色 | 强制全部 SVG inline |
| 5 | 用 lucide-react 现成图标替代 | 品牌识别度归零 | 决策 C 只在预算紧到不行才用 |
| 6 | 设计完不更新 manifest.ts | PWA 安装后图标错位/没换 | 第 7.2 节代码接入清单必须逐项打勾 |
| 7 | 不做 OG image | 分享到 Slack 显示 Next.js 默认图 | 至少做最低限度 OG，否则销售场景丢分 |
| 8 | 第三方 logo 误改 | 法律风险（Anthropic/OpenAI logo 是注册商标） | `web/public/logos/` 严格只读 |
| 9 | 把"凝视的眼"做成大眼睛卡通 | 变成消费产品感 | 提示词写明"几何抽象、不要拟人化" |
| 10 | wordmark 直接打字 | 撞所有 Inter/Söhne 用户 | 至少做 Q 字母的独特处理 |

---

## 10 范围之外

- **不做**完整 brand book / brand guideline 手册（30+ 页 PDF）——超出 1-2 周工程范围；P0+P1 完成后视需要再补
- **不做**第三方 LLM provider logo 改造（侵权）
- **不做** monaco/pdfjs/Lottie 库自带资产改造
- **不做**对外推广物料（小红书图、海报、PPT 模板）——属于市场素材，归 marketing
- **不做** UI 内 lucide-react 图标的全量替换（成本 vs 收益不成正比；只在 page-title-icons 这种"装饰图标"层做品牌化）

---

## 附录 A：可直接复用的"禁用清单"

在所有 logo / icon 提示词中复制粘贴：

> **DO NOT use**: chat bubble, speech balloon, lightning bolt, gradient rectangle with letter, purple-pink-blue gradient, abstract "AI brain" mesh, neural network with glowing nodes, cartoon eyes with face, gear/cog icon for settings, magnifying glass with hand, generic shield for security, file folder cliché, robot face, infinity loop, generic 3D macOS Big Sur skeuomorphism, Apple App Store icon template.

## 附录 B：参考竞品视觉

| 产品 | 学什么 | 不学什么 |
|---|---|---|
| Linear | 单色克制、字距精密 | 太冷（缺人情） |
| Vercel | 黑白几何、超大留白 | 太极简（缺叙事） |
| Notion | 实用图标系统、emoji-friendly | 卡通拟物风 |
| Glean | 企业稳重蓝 | 蓝色过于通用 |
| Anthropic | 暖色 + 文化感（Claude logo 是橙色花形） | 颜色温度（我们要冷一点） |
| Mistral | 字母 logo + 色块 | 字母占主导 |

**总结**：MimirQ 想站在 Linear/Vercel/Anthropic 之间——克制的几何 + 一点文化叙事（北欧 Mimir）+ 企业可信赖感。

---

## 附录 C：交付物清单（验收用）

- [ ] 4-5 个 logomark 候选稿（design review 记录）
- [ ] 选中的 logomark.svg + monochrome 变体
- [ ] wordmark.svg + 白色变体
- [ ] icon.svg（512）
- [ ] favicon.svg / favicon-light.svg / favicon-dark.svg
- [ ] apple-icon.png / icon-192.png / icon-512.png
- [ ] 29 个 page-title-icon SVG（若走 B 路径）or 29 个矢量化 SVG（若走 A 路径）
- [ ] 升级后的 `web/components/ui/page-title-icon.tsx`
- [ ] navbar.tsx logo 替换 PR
- [ ] manifest.ts / layout.tsx 元数据更新 PR
- [ ] 全站 29 页图标语义对齐验收截图
- [ ] 16×16 / 32×32 favicon 截图（实际浏览器渲染）
- [ ] light / dark mode 双模式品牌位截图
- [ ] PWA 安装到桌面图标截图（macOS / Windows / iOS / Android）
