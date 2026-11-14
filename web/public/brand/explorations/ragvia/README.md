# Ragvia 英文品牌与应用提案

2026-10-19。意图：在现有品牌方向上重新命名、升级字标并查看应用效果。用户已确认 Ragvia 品牌方向；居中登录卡片、字体与背景素材现已接入正式 `/auth` 页面。`login.html` 保留为独立设计预览，提供真实登录与注册入口，不提交账号信息。

用户要求：换掉原序 / YUANXU，品牌使用英文，图标不能是文字或字母。用户不喜欢上一轮 Lorefold / Siftmark / Tracegrove 的感觉，要求根据项目重新设计。本轮采用已选择的非文字「归点」方向和现有雾白、深墨、锈红配色。Ragvia 最初是 Agent 提出的名字；用户看过提案后回复“可以可以感觉这个好”，品牌方向已确认。

## 项目依据与设计决定

项目品类：开源企业 RAG 知识基础设施。`README.md` 和 `docs/guides/rag_platform_design_principles.md` 强调解析、治理、切块、索引、检索和引用的输入输出可检查，策略可替换，质量可回归。项目不局限于问答聊天页面。

北极星：让品牌直接指向 RAG 内核与清楚的知识处理路径。

名字为 Ragvia，字标使用小写 `ragvia`。RAG 对应项目内核；via 是英语介词「经由」。对步骤可检查与来源可追溯的联想来自本项目，而不是声称 via 本身包含这些意思。名字为本轮组合词提案，不是现成英语单词，也不附中文品牌名。

字标用 Manrope 680，收紧字距，调整图文间距；以全转曲 SVG 输出，不依赖用户安装字体。图形沿用归点的三道曲面与单一焦点，不把 r 或其他字母做成应用图标。图形与英文名并排，品牌在窄导航中保持一行。

颜色保留：雾白 `#F6F7F8`、深墨 `#20262E`、锈红 `#B84A2A`、深底强调 `#F09A77`。品牌色不改变产品的成功、警告与错误语义。

已有 RAGFlow 与 AnythingLLM 实际参考截图见 `artifacts/rebrand/converge-v5/references/`，本轮重新看过。沿用小图形与单行英文名字的组合方式；不复制其标志轮廓或冷色发光效果。

## 交付

- `web/public/brand/explorations/ragvia/index.html`：静态提案浏览页。
- `brand-overview.svg/png`：英文主组合、处理链路与品牌应用总览。
- `login.html`：白色居中登录与注册面板预览；底部直接切换“还没有账号？注册 / 已有账号？登录”。纸页与索引切片进入时归位，桌面有轻微指针视差。原生输入框可检查焦点、密码显隐、必填与确认密码校验，不接入认证。
- `auth-context.svg/png`、`auth-context-mobile.svg/png`：1280 × 800 与 390 × 844 登录页设计画面；表单内容来自现有产品，布局按最新反馈重新设计，不是实际产品截图。
- `auth-background.svg`、`auth-background-mobile.svg`、`auth-background-mobile-short.svg`、`auth-foreground.svg`：桌面、手机、短屏的独立背景和居中构图源素材。
- `dark-lockup.svg/png`、`size-proof.svg/png`：深底组合、小尺寸和单色校样。
- 标准、反白、纯黑与纯白 logo 和 mark，单独英文字标、应用图标、maskable 图标、16/32/48 favicon，以及源字体许可。
- `ragvia-concept-kit.zip`：提案素材包，包含本说明。

品牌本身是纯英文；应用稿中的表单与任务名称保留中文。用户否定悬浮动效按钮并要求重新设计背景后，换成资料页与索引切面：约 3.6 秒内归位，桌面指针移动时轻微视差；移除旧曲线、光点与悬浮播放控制。白色面板聚合表单，锈红贯穿主按钮与聚焦，减少散落资料碎片。本轮按用户要求删除“账号由管理员分配”“首次设置”和底部帮助分组，仅保留直接登录或注册；切换模式时清空密码、复位显隐和错误提示。交互预览用原生 HTML，静态素材仍为转曲 SVG/PNG；有效凭据不发送、不保存，不模拟认证成功。支持系统减少动态效果与 Escape 安定背景。本次只同步设计预览，正式认证页已由账号注册任务单独接入 `/auth/signup`。

这次将名称解释集中为 RAG + via；删除上一轮知识树林、折叠收拢等意象。展示保留真实处理步骤，不使用虚构客户、指标、徽章或背书。边框只出现在表单、浏览器标签和导航等需要表达应用场景的位置。

## 验证与限制

预览证据位于 `previews/`，是实际矢量作品经本地 Sharp 渲染的 PNG，非浏览器截图。检查了整体、1280 × 800 登录应用稿、深底和小尺寸；首轮自检修正了总览画布与登录应用稿相交、处理链路遗漏 Chunk，以及来源连接线没有完全连接的问题。

此前本地浏览器读取 `http://127.0.0.1:3000/auth` 被浏览器安全策略拒绝。没有绕过该拒绝；产品入口仍未访问。独立设计预览 `brand/explorations/ragvia/login.html` 可以正常查看，它不嵌入或请求产品认证页面；仅其画面、背景动效和本地表单状态接受浏览器检查，不把结果解释为真实登录、SSO 或首次设置已验证。未运行自动页面截图分析器，因此没有对应的默认做法提示。缩略总览主要用于判断品牌组合，登录页细节应看独立大图。最新设计决定、截图和检查范围见 `artifacts/rebrand/auth-focus-v10/`；此前基线与曲线方案记录分别保存在 `artifacts/rebrand/auth-index-v9/` 和 `artifacts/rebrand/auth-motion-v8/`。

公开搜索：先查询 `"Ragvia" OR "Ragline" OR "Citeon"`，Ragline 有同类 RAG 平台、Citeon 有 AI 工具，未选用；Ragvia 有不同行业的帐号结果。随后查询 `"Ragvia" RAG knowledge software`，本次可见页面未提供精确同名的软件普通结果。没有将搜索 AI 摘要中的猜测作为事实；这不构成唯一性、商标、域名或包名可用性结论。

原先左右分栏应用稿的独立复核见 `review/round-1.md` 与 `review/round-2.md`，按存量品牌适配评审执行，不打分；这些记录仅适用于当时的版式。该登录版式已根据用户最新反馈替换，答案卡片及其引用标注随左侧流程图一起移除。品牌标志的小尺寸校样覆盖浅底，深底小尺寸未验证。素材结构、引用和下载包离线检查见 `qa/assets.json`。

## 再生成

2026-10-19 字体与居中微调：取消中文标题负字距，标题调整为 26px/36px、550 字重，标签为 500 字重；使用项目现有 Noto Sans SC 可变字体生成约 63 KiB 的本地 UI 子集，保留系统字体回退。稳定两侧滚动条占位，修复登录切换到长注册表单时的 7.5px 横移。标志、背景、文案与表单行为保持一致。设计与证据见 `artifacts/rebrand/auth-typography-v13/`。

2026-10-19 文案微调：按用户确认的审核建议，登录副标题改为“登录 Ragvia”，注册副标题改为“使用邮箱注册”，应用区标题改为“登录与注册”；品牌介绍改为具体的解析、检索和引用结果。静态画面、HTML 与下载包从同一源头同步。正式登录页单独收短旧宣传语及“继续探索”的表达，保持原有结构与认证逻辑。记录见 `artifacts/rebrand/auth-copy-v12/`。

2026-10-19 注册入口修复（覆盖上文仅同步设计预览的交付状态）：用户在独立预览填写有效信息后没有反馈，因为该表单仅校验、不提交。正式 `/auth` 现已使用已确认的居中卡片、Ragvia 字标、本地字体和纸页背景，复用原有公开注册策略、普通 signup、错误处理、SSO 与会话保存。`/auth?mode=register` 可直接选择注册；注册是否开放仍由后端决定，新账号权限不变。独立预览始终不请求认证 API，不保存或转交凭据；有效提交后明确说明预览性质并提供对应的正式入口。

本轮通过 32 项相关前端测试、19 项隔离数据库的后端账号测试、TypeScript 检查和定向 ESLint。确认当前本地 API 及前端代理均公开注册。没有在浏览器访问此前被安全策略拒绝的 `/auth`，也未创建真实账号或重新验收正式页视觉；本轮认证结论限于接口策略读取和自动化测试。

2026-10-19 注册完成后的流程调整：按用户最新要求，普通注册成功后返回 `/auth` 登录表单，预填注册邮箱、清空密码并显示“注册成功，请登录”。注册响应不写入前端会话；单独登录成功后才进入产品。失败的注册保留原表单和错误提示。调整后 33 项相关前端回归测试通过；当前本地前端运行 `next dev --webpack`，无需生产构建即可使用。

使用项目现有 Python 环境和此前已有的 FontTools、Sharp，不增加项目依赖。源字体已保存在本任务 `source/fonts/`；仅首次缺少源字体时，生成器从 Google Fonts 的官方仓库下载 Manrope 与 OFL。

```powershell
$env:PYTHONPATH = 'E:\MimirQ\artifacts\rebrand\tooling'
& 'E:\MimirQ\.venv\Scripts\python.exe' -X utf8 'artifacts/rebrand/project-identity-v7/source/generate.py'
node 'artifacts/rebrand/project-identity-v7/source/render.mjs'
& 'E:\MimirQ\.venv\Scripts\python.exe' -X utf8 'artifacts/rebrand/project-identity-v7/source/package.py'
```

完整工作目录：`artifacts/rebrand/project-identity-v7/`。正式 `web/public/brand/yuanxu/` 和此前的探索资产保留。
