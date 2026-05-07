# MimirQ RAG 系统全面调研（增量补充 2026 Q2）

> 在 27 份既有 deep-dive plan 已覆盖大量学术 / 工程细节的基础上，做 4 项 *增量补充*：①商业 RAG 系统 2026 Q2 横向矩阵 ②开源 RAG 最新动态 ③中文 RAG 生态专章 ④MimirQ 护城河地图。
>
> 创建日期：2026-05-07
> 截止日期：本调研结论 6 个月失效（2026-11 需重做）
> **核心一句话**：MimirQ 在工程深度（KG / 解析 / 评测 / Agentic）已超越大多数开源平台，差距在 *商业化包装*（行业规则库产品化）与 *中文 vertical 沉淀*；6 个真空白（联邦 / 视频 / 流式 / 合规 / Agent-RAG / 边缘）暂时不必追。

---

## 0 阅读路径

| 章节 | 用途 | 读者 |
|---|---|---|
| 第 1 章 | 27 份 plan 覆盖矩阵 + 4 个空白声明 | 架构 / PM |
| 第 2-3 章 | 商业 + 开源系统 2026 Q2 横向矩阵 | PM / 销售 / 竞品分析 |
| 第 4 章 | 中文生态专章 + benchmark | 中国客户 PoC |
| 第 5 章 | **MimirQ 护城河地图（核心）** | 投融资 / 销售 / 战略 |
| 第 6 章 | 6 个真空白点 | 战略 / 产品规划 |
| 第 7-8 章 | 落地清单 + 风险附录 | 工程 / PM |

---

## 1 调研边界与 27 份既有 plan 覆盖矩阵

### 1.1 27 份既有 plan 主题速查表（按维度分组）

| 维度 | 既有 plan |
|---|---|
| **解析 / 切块** | rag-parsing-chunking / rag-parsing-frontend / rag-chunk-preview / rag-pre-poc-scanner |
| **预处理 / 治理** | rag-auto-tagging-services / rag-quarantine-frontend / rag-precheck-frontend |
| **入库 / 监控** | rag-ingestion-frontend |
| **查询 / 检索 / 重排** | rag-context-expansion-rerank / rag-pageindex-deep-dive |
| **Agentic / Workflow** | rag-agentic-reasoning |
| **KG** | rag-kg-deep-research / rag-kg-diagnostics / rag-kg-snapshot / rag-kg-visualization-self-built |
| **评测** | rag-evaluation / rag-eval-dataset / rag-ablation |
| **可视化** | rag-visualization |
| **安全合规** | rag-safety-compliance |
| **POC 运营** | rag-poc-attribution-framework / rag-poc-to-mvp-delivery |
| **反馈** | rag-feedback-frontend |
| **元层** | rag-deep-research / rag-capability-gap / rag-ibm-champion-blueprint |

### 1.2 覆盖矩阵（维度 × 深度）

| 维度 | 学术覆盖 | 工程覆盖 | 商业横向 | 中文聚焦 | 护城河视角 |
|---|---|---|---|---|---|
| 解析 / 切块 | ★★★★★ | ★★★★★ | ★★ | ★★ | ★★ |
| 检索 / 重排 | ★★★★★ | ★★★★ | ★★ | ★★ | ★★ |
| Agentic | ★★★★★ | ★★★★ | ★★ | ★ | ★ |
| KG | ★★★★★ | ★★★★★ | ★★ | ★ | ★★★ |
| 评测 | ★★★★★ | ★★★★ | ★ | ★★ | ★ |
| 安全 | ★★★ | ★★★ | ★ | ★ | ★ |
| 可视化 | ★★ | ★★★★★ | ★★ | — | ★★ |
| POC 运营 | — | ★★★★★ | — | ★★★★ | ★★★★★ |
| **商业横向** | — | — | **★★（散落）** | — | — |
| **中文专章** | — | — | — | **★★（零散）** | — |
| **护城河地图** | — | — | — | — | **★★（散落）** |

### 1.3 本调研填的 4 个空白

1. **商业 RAG 系统横向矩阵**（既有 plan 散落 21 处提及，无集中对比）
2. **开源 RAG 系统 2026-Q2 最新动态**（既有 plan 截止 2026-04-30）
3. **中文 RAG 生态专章**（CRUD-RAG 等仅在评测集 plan 中提及，缺集中）
4. **MimirQ 护城河地图**（27 份 plan 反复用"护城河"一词，从未集中绘制）

### 1.4 不做的事

- 不重复学术论文综述（已在 rag-deep-research / rag-kg-deep-research / rag-agentic-reasoning 等覆盖 50+ 篇）
- 不写新 deep-dive，只做综合 / 元分析
- 不评估 SaaS 厂商合规 / 采购建议

---

## 2 商业 RAG 系统 2026 Q2 横向矩阵

### 2.1 11 家对标（按定位分类）

| 类型 | 厂商 | 一句话定位 |
|---|---|---|
| 企业搜索 | **Glean** | 全员企业搜索 + Workspace AI（行业标杆） |
| 企业搜索 | **Vectara** | 自部 RAG-as-a-Service，强调 Hallucination Detection |
| 企业搜索 | **Microsoft Copilot for M365** | 微软生态绑定，全场景 |
| 企业搜索 | **Google Vertex AI Search** | GCP 平台型 RAG |
| LLM 厂自营 | **Cohere RAG / Compass** | Cohere 自家闭环 |
| 通用 SaaS | **Perplexity Enterprise** | 搜索 + RAG 一体化 |
| 平台蓝图 | **NVIDIA AI Blueprints** | NIM / NeMo Retriever 集成 |
| 老牌企业 | **IBM Watson Discovery / watsonx** | 行业垂直版 |
| 长文档 | **PageIndex (Vectify AI)** | Vectorless tree search |
| 解析 / OCR | **Reducto** | 文档解析 API（强表格） |
| 解析 / OCR | **Mistral OCR** | Mistral 推出的 OCR 服务 |

### 2.2 11 维对比矩阵

| 维度 | Glean | Vectara | Cohere | M365 Copilot | Vertex AI | Perplexity Ent | NVIDIA AI BP | Watson | PageIndex | Reducto | Mistral OCR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 解析 OCR | 中 | 中 | 中 | 中（Office 原生强） | 中 | 中 | 中 | 强 | 弱（PyPDF2） / 强（Cloud） | **强** | **强** |
| 切块算法 | 自家 | 自家 | 自家 | 黑盒 | 黑盒 | 黑盒 | NeMo | 自家 | TOC tree | — | — |
| 检索方式 | hybrid | hybrid + halu detect | hybrid + Compass | hybrid + Graph (M365) | hybrid + Vertex | search-first | hybrid (NIM) | hybrid | **vectorless** | — | — |
| 路由 / Adaptive | router | static | static | static | static | router | router | router | LLM tool agent | — | — |
| 多模态 | 文 + 图 | 文 + 图 | 文 + 图 | 文 + 图 + 视频 | 文 + 图 + 视频 | 文 + 图 | 文 + 图 + 视频 | 文 + 图 | 文 (vision RAG demo) | 文 + 图 | 文 + 图 |
| 评测 | 内部 | RAGAS + 自家 | 内部 | 内部 | 内部 | 内部 | 含示例 | 内部 | FinanceBench | — | — |
| 安全 | SOC2 + IL5 + GDPR | SOC2 | SOC2 | M365 全套 | GCP 全套 | SOC2 | NV 自托管 | IBM 全套 | SOC2 (Cloud) | SOC2 | EU 部署 |
| 部署 | SaaS | SaaS / VPC | SaaS / VPC | SaaS | SaaS / VPC | SaaS | 自托管 NIM | SaaS / on-prem | SaaS / 自部 | SaaS | API |
| 中文 | 中（多语言） | 中 | 中（aya 系列强） | 强（M365 中文） | 中 | 中 | 弱 | 中 | 弱（开源版） | 中 | 中 |
| 价格 | $20-30/seat/mo | $1.25/M-token | $X /M-token | M365 E5 含 | per query | $20-40/seat/mo | NIM license | 询价 | API 按调用 | $1-5/页 | API |
| 客户画像 | 企业全员 | 开发者 / B 端 | LLM 客户 | M365 客户 | GCP 客户 | 知识工作者 | 自托管 LLM | 行业客户 | 长文档客户 | 解析中间件 | 解析中间件 |

### 2.3 关键洞察 5 条

1. **解析层正在成为独立产品**：Reducto / Mistral OCR / PageIndex Cloud OCR 都在抢"解析即服务"市场。MimirQ 的 deepdoc 自有栈在工程深度上不输，但**没有 API 化对外销售**，是个商业机会
2. **路由 / Adaptive 是商业 SaaS 的差异点**：Glean / Perplexity / NVIDIA Blueprints 都把 router 作为卖点，MimirQ 已有 system_router / self_route 但**前端未透出 routing 决策**（参照 rag-visualization-deep-dive 已规划但未落地）
3. **Hallucination Detection 是 Vectara 的护城河营销词**：本质是 Citation + Atomic Fact（MimirQ rag-evaluation P0 已规划），需要把它包装成 *卖点术语*
4. **多模态视频 RAG 是 2026 Q2 后段的新战场**：M365 Copilot / Vertex AI / NVIDIA Blueprints 已支持视频；既有 27 份 plan **完全未涉及**（详见第 6 章空白 2）
5. **价格区间分化明显**：企业搜索 $20-40/seat/mo（Glean / Perplexity）、平台型按 token / API 计费（Vectara / Reducto）、垂直行业询价（Watson）。MimirQ 缺一个**可对外报价的 SKU 表**

### 2.4 2026 Q2 后段（4-5 月）值得关注的新动态

> 本节内容会在 2026-11 失效，届时需重做。
- **PageIndex File System**（2026-04-XX）从单文档 tree 扩到全 corpus 文件树
- **Mistral OCR API**（2026-Q2）公开 GA，价格压低
- **Cohere Compass**（2026-Q2）多模态 + 多语言文档检索
- **NVIDIA AgentIQ**（2026-Q1）整合 NeMo Retriever + AgentSDK
- **Vectara HHEM-2.0**（2026-Q1）开源 Hallucination Eval Model，已成 RAG 评测开源标准之一

---

## 3 开源 RAG 系统 2026 横向矩阵

### 3.1 12 个对标

| 类型 | 项目 | star (~2026-04) | 一句话定位 |
|---|---|---|---|
| 框架级 | **LangChain** | 90k+ | 链式编排始祖 |
| 框架级 | **LlamaIndex** | 35k+ | 数据接入 + 索引专精 |
| 框架级 | **Haystack** | 16k+ | deepset 出品，企业向 |
| 框架级 | **R2R (SciPhi)** | 5k+ | 全栈 RAG 工程 |
| 平台级 | **RAGFlow** (InfiniFlow) | 30k+ | 自家 deepdoc 解析（**MimirQ 同源**） |
| 平台级 | **Cognita** (TrueFoundry) | 4k+ | 企业部署友好 |
| 平台级 | **Verba** (Weaviate) | 6k+ | Weaviate 生态 demo |
| 平台级 | **Open WebUI** | 60k+ | LLM Chat UI 起家加 RAG |
| 平台级 | **Quivr** | 35k+ | 个人 second brain |
| 中国生态 | **Dify** (LangGenius) | 80k+ | LLM 应用平台 |
| 中国生态 | **FastGPT** (Tencent) | 25k+ | 企业知识库 |
| 长文档 | **PageIndex** | 28k+ | Vectorless tree search |

### 3.2 9 维对比矩阵

| 维度 | LangChain | LlamaIndex | Haystack | R2R | RAGFlow | Cognita | Dify | FastGPT | PageIndex |
|---|---|---|---|---|---|---|---|---|---|
| 维护活跃度 | ★★★★★ | ★★★★★ | ★★★★ | ★★★ | ★★★★★ | ★★★ | ★★★★★ | ★★★★ | ★★★★ |
| 中文友好度 | ★ | ★★ | ★ | ★ | **★★★★★** | ★ | **★★★★★** | **★★★★★** | ★ |
| 解析栈 | 第三方 | 自家 + 集成 | 自家 | 自家 | **★★★★ deepdoc** | 第三方 | 简单 | 中文优 | PyPDF2 |
| KG 支持 | LangGraph (有) | KG-RAG 模块 | 弱 | 有 | 有 | 弱 | 弱 | 弱 | 无 |
| Agentic 支持 | LangGraph | AgentEngine | Agents | Agents | Workflow | 弱 | Workflow ★★★★★ | Workflow | LLM tool |
| 评测内置 | LangSmith | LlamaTrace | 自家 | 弱 | 弱 | 弱 | 弱 | 弱 | FinanceBench |
| 部署易用 | docker | docker | docker | docker | docker | **★★★★★ k8s 友好** | **★★★★★ docker** | **★★★★★** | docker |
| 商业版 | LangSmith | LlamaCloud | deepset | enterprise | RAGFlow Cloud | TrueFoundry | LLMOps | Tencent | Vectify Cloud |
| 与 MimirQ 关系 | 库依赖 | 库依赖 | — | — | **同源 deepdoc** | 参考 | 中国客户对手 | 中国客户对手 | 借鉴对象 |

### 3.3 MimirQ 在开源生态中的定位（自评）

| 能力 | MimirQ vs 开源最佳 |
|---|---|
| **解析栈** | 与 RAGFlow deepdoc 同源 + 25 parser 数量领先；OCR 与 Reducto / Mistral 商业版有差距 |
| **KG 全栈** | extraction + community(LLM) + ontology + provenance + snapshot 比 LangChain / LlamaIndex KG 模块**完整一档** |
| **Agentic** | crag/flare/self_rag/self_route/system_router 与 LangGraph 同梯队 |
| **评测** | 已规划 LLM-Judge + Citation + Atomic Fact + 38 参数 ablation 比 LangSmith / RAGAS **更深** |
| **可视化** | /graph 9084 行已超越 Verba / Cognita |
| **POC 运营** | 行业规则库 + 三分类 + 5 字段埋点 **领先所有开源** |
| **国际化 / 文档** | 与 LangChain / LlamaIndex 有数量级差距（社区 / 文档 / 教程） |
| **生态集成** | 弱于 LangChain / LlamaIndex / Dify（插件 / 企业集成） |

**结论**：工程深度上 MimirQ 处于开源**第一梯队**（与 RAGFlow / LangChain 同档），但**社区运营 / 国际化 / 商业化包装**有明显短板。

### 3.4 2026 Q2 开源动态（4-5 月）

- **LangChain v1.0**（2026-04）正式 GA，破坏性变更已稳定
- **LlamaIndex Workflows v0.14**（2026-Q2）支持人在环
- **RAGFlow v0.18**（2026-Q2）DeepDoc 升级 + GraphRAG 集成
- **Dify v1.5**（2026-Q2）Plugin 生态扩张
- **PageIndex File System**（2026-04）跨文档 tree

---

## 4 中文 RAG 生态专章

### 4.1 中文商业云 SaaS 横向矩阵（7 家）

| 厂商 | 产品 | 解析 | 中文 embedding | 政务合规 | 行业版本 | 价格区间 |
|---|---|---|---|---|---|---|
| **阿里云** | 百炼 / 通义灵码 | OCR + 通义文档 | GTE-Qwen / Conan | 等保 2.0 / ICP | 金融 / 政务 / 医疗 | 调用计费 |
| **腾讯云** | 智能体平台 / 元宝 | 腾讯优图 OCR | TencentEmb | 等保 2.0 / ICP | 政务 / 金融 | 调用计费 |
| **百度云** | 千帆 / 文心 | 飞桨 OCR | ERNIE-Embedding | 等保 2.0 | 政务 / 教育 | 调用计费 |
| **华为云** | 盘古 RAG | 华为 OCR | 盘古 Embedding | 等保 2.0 / 政务专网 | 政务 / 制造 | 询价 |
| **火山引擎** | 知识库 / 飞书智能伙伴 | 火山 OCR | Doubao-Embedding | 等保 2.0 | 内部生态 + 教育 | 调用计费 |
| **字节** | Coze（开源版 + Pro） | 简单 | Doubao | — | 通用 | 免费 + Pro |
| **爱奇艺金融** | 词道 | 财报特化 | 自家 | 金融行业 | **金融 vertical** | 询价 |

**关键洞察**：
1. **中国云大厂全部进场**，但都是平台型，**缺垂直 vertical 深度**（除词道）
2. **政务合规是中国市场刚需**（等保 2.0 / 政务专网），开源 / 海外厂商无法直接进入
3. **价格战已开始**（百度 / 阿里推 0 元起），但企业版仍 ¥10-100/M-token
4. **MimirQ 优势**：vertical 行业沉淀（rag-poc-attribution 行业规则库）+ 中文 deepdoc + 政务合规可对接

### 4.2 中文专属 benchmark 速查表

| Benchmark | 来源 | 规模 | 评测维度 | 状态 |
|---|---|---|---|---|
| **CRUD-RAG** | NAACL'25 | 6.4K 中文 RAG QA | Create / Read / Update / Delete | ✅ MimirQ 已规划接入 |
| **C-MTEB** | 中文 embedding 排行榜 | 35 任务 | retrieval / classification 等 | ✅ 业界标准 |
| **CMRC2018** | 中文阅读理解 | 4.9K 题 | extractive QA | 经典 |
| **DuReader 1.0/2.0** | 百度中文 QA | 200K+ | open-domain QA | 经典 |
| **Chinese FinQA** | 哈工大 | 8K 题 | 中文金融 QA | ⚠️ 数据质量参差 |
| **LegalBench-CN** | 中文法律 | 待补 | 中文法律 RAG | ⚠️ 半公开 |
| **C-Eval / CMMLU** | 综合中文评测 | 13K+ | 通用 LLM 能力 | 非 RAG，常用作组件 |
| **CGTN-RAG-Eval** | 央视 | 内部 | 政务 RAG | 私有，参考 |
| **公司公告 / 招股书** | 自建 | — | 金融 vertical | **MimirQ 应自建** |

### 4.3 中文特有问题清单（既有 plan 零散提及，本次集中）

| 问题 | 工程难点 | 业界方案 | MimirQ 现状 |
|---|---|---|---|
| **简繁混排** | 古籍 / 港澳台文档 | OpenCC + 繁简映射 | jieba 已自动转 |
| **中文分词** | jieba / HanLP / pkuseg | 各有优劣，jieba 主流 | jieba（可加 HanLP fallback） |
| **中文 embedding** | BGE-M3 / GTE-Qwen / Conan | BGE-M3 中文榜首 | ✅ 已默认 BGE-M3 |
| **法规版本管理** | "自 X 日施行 / 修订" 时序 | 手动版本 + KG | 缺**法规专属 schema** |
| **政府公文格式** | 红头 / 章节编号严格 | 模板规则 + LLM | 缺**公文 parser** |
| **财报附表抽取** | 跨页表 / 合并单元格 | 表格 OCR + LLM | deepdoc 已支持 |
| **古今字 / 异体字** | 古籍 + 学术 | OpenCC 部分 | 未覆盖 |
| **混排公式 / 化学式** | LaTeX / SMILES | LLM 多模态 | 弱 |

### 4.4 中文 RAG 真正的工程难点（既有 plan 未集中盘点）

1. **表格密集**：中国财报 / 政务文件表格占 40-60%，表格抽取质量决定 RAG 上限
2. **公文格式**：中央 / 地方两级公文红头 / 章节编号 / 引用层级，需要专门 parser
3. **一表多义**：同一字段在不同公司年报口径不同（"研发投入" 含义可能不同）
4. **古今字混排**：古籍 + 学术文献场景，OpenCC 不够
5. **政务合规**：数据不出境、等保 2.0、政务专网部署
6. **方言 / 多语种**：粤语 / 闽南语 / 藏语 / 维语等少数民族语言（小众但重要）

---

## 5 MimirQ 差异化护城河地图

### 5.1 8 类护城河整合

| 护城河类型 | 具体内容 | 来源 plan | 强度 | 护得住性 |
|---|---|---|---|---|
| **数据 / 评测** | 行业规则库（术语 + 模式 + 意图）、PoC 三分类、超纲三级验证、5 字段埋点 | rag-poc-attribution-framework | ★★★★★ | **强**（数据资产） |
| **POC 运营** | 一周交付方法论、bad case 反哺、UMAP 客户沟通、HTML 单文件报告 | rag-poc-to-mvp / rag-poc-attribution | ★★★★ | **强**（know-how） |
| **解析栈** | deepdoc 25+ parser、双重输出（MD+DOCX）、Pre-POC scanner（7 项 + 5 标签） | rag-parsing-chunking / rag-pre-poc-scanner | ★★★★ | 中（同源 RAGFlow） |
| **KG 工程** | extraction + community(LLM) + ontology + provenance + snapshot + agentic + 影响分析 | rag-kg-deep-research / rag-kg-snapshot | ★★★★ | **强**（深度领先） |
| **可视化** | /graph 9084 行 + agentic 路径动画 + KG snapshot overlay | rag-kg-visualization | ★★★ | 中（可被复刻） |
| **评测严谨** | LLM-Judge + Citation + Atomic Fact + 38 参数 ablation + 统计显著性 | rag-evaluation / rag-ablation | ★★★ | 中（DeepEval 在追） |
| **中文 vertical** | 中文金融 / 中文法规 / 中文政务 know-how（散落） | 多份 plan | ★★ | **强**（数据 + 领域） |
| **生态集成** | 企微 / 钉钉 / 飞书 / MCP server | rag-poc-to-mvp | ★★ | 弱（开源能拷） |

### 5.2 真正不可拷贝的 3 条护城河

1. **行业规则库（术语 + 问题模式 + 意图分类）** ★★★★★
   - 来源：rag-poc-attribution-framework 第 7.4 节
   - **为什么不可拷贝**：每家企业的内部术语 / 问题模式不同，是数据资产 + 领域积累，**新进者要从零开始**
   - **当前状态**：各 PoC 项目散落，未产品化
   - **建议（详 7.1）**：P0 抽离为独立产品

2. **POC 运营 know-how（一周交付方法论 + 5 字段 + 三分类）** ★★★★★
   - 来源：rag-poc-attribution-framework / rag-poc-to-mvp-delivery
   - **为什么不可拷贝**：是销售-工程闭环的执行手册，开源代码买不到这套流程
   - **当前状态**：plan 文档有，落地工具半成品
   - **建议**：P1 沉淀为内部 SOP + 客户 onboarding 模板

3. **KG 影响分析（k-hop BFS + 网络分析）** ★★★★
   - 来源：rag-kg-snapshot-deep-dive 第 P1
   - **为什么不可拷贝**：金融反欺诈 / 供应链依赖 / KYC 这类客户场景的杀手级功能，开源 GraphRAG 都不做
   - **当前状态**：plan 已规划，未落地
   - **建议**：P0 落地

### 5.3 快被追平的 3 条护城河

1. **解析栈** ★★★★
   - 威胁：Reducto / Mistral OCR API 化、PageIndex Cloud OCR、商业系统都在追
   - **应对**：MimirQ 的 deepdoc 应当 API 化（独立 SKU），抢"解析即服务"市场（详 7.2）

2. **Agentic Workflow** ★★★
   - 威胁：OpenAI Agents SDK / LangGraph / NVIDIA AgentIQ 标准化
   - **应对**：MimirQ 的 12 个 workflow 应当**对外暴露**（API + UI），形成 *workflow marketplace*

3. **评测严谨性** ★★★
   - 威胁：DeepEval / TruLens / Phoenix / Vectara HHEM-2.0 商业化 + 开源化
   - **应对**：把 Citation / Atomic Fact 包装成"可信度评分"（rag-evaluation 已规划，但缺**面向客户的术语包装**）

### 5.4 护城河强度排序（投资 / 销售视角）

按"客户买单意愿"排序：
1. ★★★★★ 行业规则库（垂直 SaaS 真正护城河）
2. ★★★★★ POC 运营 know-how（销售确定性）
3. ★★★★ KG 影响分析（杀手级功能）
4. ★★★★ 解析栈（基础但易追平）
5. ★★★★ 中文 vertical（中国市场刚需）
6. ★★★ 可视化（差异化体验）
7. ★★★ 评测严谨（信任）
8. ★★ 生态集成（基础）

---

## 6 27 份既有 plan 未覆盖的 6 个真空白点

### 6.1 跨文档 / 联邦 RAG（Federated RAG）

- **业界**：Cohere Compass 跨企业检索 / AWS Clean Rooms ML
- **学术**：FedRAG (NeurIPS'25)、FedKG (ICLR'26)
- **MimirQ 现状**：单租户 + dataset 级隔离，**不支持联邦**
- **价值**：金融 / 医疗多机构联合分析（不出境数据）
- **判定**：**P1 调研 plan**，客户场景出现时启动；垂直行业刚需（如银行联合反欺诈）

### 6.2 多模态视频 RAG

- **业界**：Twelve Labs（视频检索专家）、M365 Copilot 已支持视频、Vertex AI 视频检索
- **学术**：Video-RAG (NeurIPS'25)、Vid2RAG (CVPR'26)
- **MimirQ 现状**：**完全无视频支持**（既有 plan 仅 ColPali 图像）
- **价值**：会议视频 / 培训视频 / 监控视频 / 直播带货
- **判定**：**P2 评估**，技术栈门槛高（视频 embedding + ASR + 帧采样），暂不优先

### 6.3 实时 / 流式 RAG

- **业界**：Confluent + Pinecone 集成、Materialize、Apache Pinot
- **学术**：StreamingRAG (KDD'25)、Online-RAG (SIGIR'26)
- **MimirQ 现状**：批量入库，无实时索引；rag-ingestion-frontend 提到增量但**非真流式**
- **价值**：新闻 / 金融行情 / IoT / 客服工单
- **判定**：**P3 评估**，Kafka 接入工程量大但价值场景有限（B 端文档场景为主）

### 6.4 法规 / 合规自动化 RAG

- **业界**：Harvey AI（法律）、CaseText、Spellbook、Robin AI
- **学术**：LegalBench、LawRAG (EMNLP'25)
- **MimirQ 现状**：散文 / 法规已支持，但**无合规自动化（条款比对 / 红线检测 / 合规报告生成）**
- **价值**：中国 vertical 刚需（信通院 / 等保 2.0 / 个保法 / 数安法 / 金融法规）
- **判定**：**P1 调研 plan**，与 4.3 中文法规版本管理 + 5.2 行业规则库**协同**，是中文市场护城河延伸

### 6.5 Agent + RAG 边界

- **业界**：Anthropic Computer Use、OpenAI Operator、Microsoft Magentic-One
- **学术**：AgentRAG 综述（arXiv 2026-Q1）
- **MimirQ 现状**：12 个 workflow 已 agentic，但**未与 GUI agent / browser agent 协同**
- **价值**：复杂任务（"查 X 公司 2024 年报告然后跨 Y 系统提交申请"）
- **判定**：**P3 评估**，技术栈不成熟（Computer Use 仍 beta），观察一年再判

### 6.6 小模型 / 边缘 RAG

- **业界**：Ollama + RAG、LocalGPT、Apple Intelligence
- **学术**：EdgeRAG (MLSys'26)
- **MimirQ 现状**：依赖云端 LLM，**无离线 / 边缘部署模式**
- **价值**：政务专网 / 制造 / 医院（数据不出网）
- **判定**：**P2 评估**，与 4.1 政务合规 + 5.4 中文 vertical 协同；可作为 *安全合规 SKU* 卖点

### 6.7 6 个空白汇总

| 空白 | 优先级 | 启动条件 |
|---|---|---|
| 联邦 RAG | P1 | 出现金融 / 医疗联合客户 |
| 视频 RAG | P2 | 客户主动询问 |
| 流式 RAG | P3 | 新闻 / 行情 / IoT 场景 |
| 合规自动化 | P1 | 中国 vertical 客户 |
| Agent + RAG | P3 | Computer Use 标准化后 |
| 边缘 RAG | P2 | 政务专网客户 |

---

## 7 落地清单

### 7.1 P0（立即做，1-2 周）

#### P0-1：行业规则库产品化

- **背景**：rag-poc-attribution-framework 第 7.4 节论述了"行业规则库是真正护城河"，但未产品化
- **做什么**：
  - [ ] 抽离 schema：`industry_rules/` 目录新增 `schema.py`，定义 `term_mapping / question_pattern / intent_classifier` 三表
  - [ ] 后端 API：`app/api/v1/industry_rules.py` 暴露 CRUD + import / export
  - [ ] 前端页面：`/governance/industry-rules` 三 Tab（术语 / 问题模式 / 意图）
  - [ ] 接入流程：query 进入 router 时优先匹配规则库（rag-poc-attribution Stage 0 已规划）
  - [ ] 客户 onboarding：把规则库填写作为 PoC 必须步骤，沉淀为模板
- **代码量**：~500 行 backend + ~700 行 frontend = ~1200 行，1 周
- **复用资产**：`rag-poc-attribution-framework-2026-q2.md` 第 7 章详细 schema 设计

#### P0-2：中文 benchmark 速查表上手

- **背景**：rag-eval-dataset-deep-dive 提到 CRUD-RAG，但未跑过基线
- **做什么**：
  - [ ] 拉 CRUD-RAG 数据集（GitHub 公开）
  - [ ] MimirQ 现状跑全量基线 → 输出报告
  - [ ] 自建中文金融评测集：5 篇 A 股年报 + 50 题（已在 rag-pageindex-deep-dive 附录 6.4 规划）
  - [ ] 接入 `evaluation/poc_runner/cn_finance_bench/`
- **代码量**：~200 行评测脚本，1 周
- **价值**：给销售 / PM 一个能 quote 的中文场景硬数据

### 7.2 P1（1 个月，2 件事）

#### P1-1：合规自动化 RAG 调研 plan

- 写一份 `plans/rag-compliance-automation-2026-q3.md`（与本调研同等粒度 ~600 行）
- 涵盖：等保 2.0 / 个保法 / 数安法 / 金融法规对接、条款比对、合规报告生成
- 与 5.2 KG 影响分析协同（合规变更影响哪些条款）

#### P1-2：解析栈 API 化

- **背景**：第 5.3 节"解析栈快被追平"威胁
- **做什么**：把 `deepdoc` 抽离为独立服务，对外提供 OCR + 解析 API（按页计费）
- **代码量**：~300 行 API 抽离 + ~200 行 SDK 客户端 + 文档
- **价值**：抢"解析即服务"市场（Reducto / Mistral OCR）

### 7.3 P2（3 个月）

- **P2-1**：视频 RAG 评估 plan（仅当客户询问时启动）
- **P2-2**：边缘 / 政务专网部署 plan（针对中国 vertical）
- **P2-3**：联邦 RAG 调研（金融 / 医疗客户出现时）

### 7.4 P3（按需）

- **P3-1**：流式 RAG（场景出现）
- **P3-2**：Agent + RAG 边界（Computer Use 标准化后）

---

## 8 风险与附录

### 8.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 调研结论 6 个月失效 | 业界变化快 | 2026-11 重做 |
| 商业系统对照失真 | 厂商 marketing 偏夸大 | 仅记录公开信息，不引用 marketing claims |
| 中文 benchmark 质量参差 | 评测结论可疑 | 多 benchmark 交叉验证 |
| 护城河评估主观度高 | 投资 / 销售可能误读 | 标注"主观评估"，需客户场景再校准 |
| **行业规则库产品化是最大变量** | 做不好则 P0 失败 | 先用 1-2 个 PoC 客户共建，再泛化 |

### 8.2 附录

#### A.1 27 份既有 plan 主题速查表

详见 1.1 节。

#### A.2 商业 RAG 系统价格速查（公开信息，2026-Q2）

| 厂商 | 价格区间 |
|---|---|
| Glean | $20-30/seat/mo（企业版） |
| Vectara | $1.25/M-token + 自部 license |
| Cohere | per token，企业询价 |
| M365 Copilot | E5 含 / $30/user/mo（独立） |
| Vertex AI | per query + 索引存储 |
| Perplexity Enterprise | $20-40/seat/mo |
| NVIDIA AI Blueprints | NIM license + 硬件 |
| IBM Watson | 全询价 |
| PageIndex Cloud | API 按调用 |
| Reducto | $1-5/页 |
| Mistral OCR | API 按页 |

#### A.3 中文 benchmark URL 速查

| Benchmark | URL / 来源 |
|---|---|
| CRUD-RAG | github.com/IAAR-Shanghai/CRUD_RAG |
| C-MTEB | github.com/FlagOpen/FlagEmbedding/tree/master/C_MTEB |
| CMRC2018 | hfl-rc.github.io/cmrc2018 |
| DuReader | aistudio.baidu.com/datasetdetail/103376 |
| Chinese FinQA | 哈工大 NLP 组（半公开） |
| LegalBench-CN | 部分中文法律组开源 |
| C-Eval | github.com/hkust-nlp/ceval |
| CMMLU | github.com/haonan-li/CMMLU |

#### A.4 2026 Q2 时间线

| 日期 | 事件 |
|---|---|
| 2026-04 | LangChain v1.0 GA、PageIndex File System 发布 |
| 2026-04 | Mistral OCR API GA |
| 2026-Q1 | NVIDIA AgentIQ 发布、Vectara HHEM-2.0 开源 |
| 2026-Q2 | Cohere Compass 多模态、RAGFlow v0.18、Dify v1.5 |

#### A.5 与本调研协同 / 互补的既有 plan

| 既有 plan | 与本调研关系 |
|---|---|
| `rag-deep-research-2026-q2.md` | **学术综述底盘**，本调研是其商业 / 中文 / 护城河补充 |
| `rag-capability-gap-2026-q2.md` | **横向 gap 起点**，本调研做集中矩阵 |
| `rag-poc-attribution-framework-2026-q2.md` | **护城河理论根**，本调研做产品化路径 |
| `rag-poc-to-mvp-delivery-2026-q2.md` | **POC 运营**，本调研把它列为护城河 #2 |
| `rag-eval-dataset-deep-dive-2026-q2.md` | **CRUD-RAG 出处**，本调研做中文专章 |
| `rag-pageindex-deep-dive-2026-q2.md` | **同期 PageIndex 单点调研**，本调研把它放入横向矩阵 |

### 8.3 关键洞察精选（5 条）

1. **MimirQ 工程深度已业界第一梯队**，与 RAGFlow / LangChain / LlamaIndex 同档；差距在**社区运营 + 商业化包装**
2. **真正不可拷贝的 3 条护城河**：行业规则库、POC 运营 know-how、KG 影响分析。其中**行业规则库未产品化是最大遗憾**（P0-1 推动）
3. **快被追平的 3 条护城河**：解析栈、Agentic、评测严谨。**解析栈应当 API 化**抢市场（P1-2）
4. **6 个真空白**：联邦 / 视频 / 流式 / 合规 / Agent-RAG / 边缘。**只有合规自动化和联邦 RAG 是中国市场刚需**（P1）
5. **中文生态价值远高于学术对标**：等保 2.0 + 政务合规 + vertical 沉淀是开源 / 海外厂商无法直接进入的。**中文不是限制，是护城河**

---
