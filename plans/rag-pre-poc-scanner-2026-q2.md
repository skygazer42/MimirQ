# 入库前文档预检工具包（Pre-POC Scanner）深度设计（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：第 9 份 RAG 专项，覆盖**比 POC 更早一步**的 **Pre-POC 阶段**—— 在接触客户数据的第一时间，做格式分布 / 扫描件比例 / 敏感信息 / 长度分布 / 重复检测 / 文档标签化 六件事，产出**脱敏的客观离线报告**，用于售前报价、项目摸底、内部资产盘点。
> **核心洞察**：**报价偏差的根源是"基于样例报价"**——客户挑的样例 ≠ 全貌；唯一可靠的办法是让客户在本地跑工具，拿到**全量数据的脱敏报告**后再决定工作量 / 复杂度 / 付费 POC 是否启动。
> **灵感来源**：一线乙方做了十几个知识库项目后沉淀的预检工具包复盘；工具包已在三四个真实项目跑通，后端 ~2500 行 + 前端 ~3000 行。
> **与前 8 份 plan 的关系**：**时间线最前置**的一环。

```
[Pre-POC Scanner，本文] → POC 归因框架 → 评测集 Stage 1→4 → KG/Agentic/解析切块/安全 各专项
    Day 0–2                  Week 1       Week 2+          Month 2+
```

---

## 1. Context：为什么报价总是偏差？

### 1.1 痛点图谱

| 阶段 | 乙方痛 | 客户痛 |
|---|---|---|
| 远程咨询（无信任） | "几千份文档 = 多少钱？" 难答 | 被报贵嫌黑、报低又担心交付差 |
| 样例报价 | 客户挑的样例代表性差 | 样例来回发，进度慢 |
| 接触全量数据（线下 NDA） | 需谨慎处理原始数据 | NDA 流程本身耗时 |
| POC 启动后 | 清洗量远超预估，项目亏损 | 进度延期、沟通成本 |

**根本矛盾**：乙方**必须**看到数据全貌才能报价，但客户**无法**在报价前给全量数据。

### 1.2 解决范式：本地工具 + 脱敏离线报告

- **客户**：在本地运行工具（Docker 或 PyInstaller 单文件），扫描全量文档，生成**单文件 HTML 报告**
- **乙方**：收到报告（脱敏后客观数据） → 判断复杂度 → 给报价或建议 POC
- **双赢**：客户不泄密、乙方能决策

---

## 2. 三种使用场景

| 场景 | 使用者 | 产出 | 价值 |
|---|---|---|---|
| **售前咨询** | 潜在客户在本地跑 → 发报告给乙方 | 脱敏离线 HTML | 远程报价的信任基础 |
| **项目交付摸底** | 乙方拿到文档包首先跑 | 交互式仪表盘 + 可操作清单 | 一期边界 / 二期规划 |
| **企业内部 IT 盘点** | 客户自有 IT 团队 | 历史资产报告 | 哪些能入库 / 哪些要 OCR / 哪些敏感 |

**关键差异**：前两个场景输出面向"决策"，第三个场景输出面向"治理"。工具**一套流程三种输出模板**即可覆盖。

---

## 3. 最终保留的 7 项核心功能

> 本节给出"**功能 × 为什么这么设计 × 我方落地文件**"三元组。

### 3.1 递归扫描 + 格式分布

**做什么**：递归遍历目录，按扩展名统计格式分布（pdf / docx / doc / xlsx / pptx / md / txt / html / ...）

**为什么核心**：100% 客观准确、无歧义、唯一决定后续管线选择

**我方落地**：`app/rag/tools/pre_poc_scanner/format_distribution.py`（~150 行）

### 3.2 PDF 页面类型识别（**三档**，非二分类）

**做什么**：按页判断每页文字密度，总结出文件级 PDF 类型

**三档判定逻辑**：
```python
# 页面级
if page_chars < 50:
    page_type = "scan"         # 扫描页
elif page_chars > 200:
    page_type = "text"         # 文字页
else:
    page_type = "low_density"  # 封面 / 目录 / OCR 质量差

# 文件级
scan_ratio = scan_pages / page_count
if scan_ratio >= 0.7:
    pdf_type = "SCAN"
elif scan_ratio > 0.2:
    pdf_type = "MIXED"
else:
    pdf_type = "TEXT"
```

**为什么分三档**：纯文字 / 纯扫描之间有大量中间带：
- **双层 PDF**（Acrobat 加 OCR 文字层）：解析出的文字可能错字乱码
- **图文混排**（PPT 导出）：部分页全是图
- **低密度页**：封面 / 目录 / 第一页 logo

**关键工程原则**：**这是启发式分流，不保证严格正确**，因此：
1. 所有阈值可配置
2. 输出"待确认"列表（而非硬分类）
3. 分流结果用于估算工作量，不直接决定入库 pipeline

**我方落地**：`app/rag/tools/pre_poc_scanner/pdf_page_classifier.py`（~250 行）

### 3.3 文档长度分布（分位数 + 直方图）

**做什么**：字符数 P25/P50/P75/P90/P99 + 长度区间直方图

**为什么核心**：**直接决定分块策略**。若 P90 < 2000 字 → 不必切细；若 P90 > 20000 字 → 必须做层级切块或 RAPTOR。

**重要 caveat**：字符数只是**粗粒度 proxy**，真实切块需按 **embedding 模型的 tokenizer 与上下文窗口** 重新计算。预检阶段字符数即可。

**我方落地**：`app/rag/tools/pre_poc_scanner/length_distribution.py`（~100 行）

### 3.4 MD5 精确去重

**做什么**：文件级 MD5 hash，找完全相同的文件（重命名 / 多副本）

**结果处理**：自动推荐保留其一，其余标为"duplicate"

**我方落地**：`app/rag/tools/pre_poc_scanner/md5_dedup.py`（~80 行）

### 3.5 SimHash 高相似度检测（**"待确认的版本冲突"**，非自动删除）

**做什么**：文档 → 64 位 SimHash → 两两计算汉明距离

```python
def hamming_distance(hash1: int, hash2: int) -> int:
    x = hash1 ^ hash2
    count = 0
    while x:
        count += 1
        x &= x - 1   # 清除最低位的 1
    return count
```

**阈值映射**：

| 汉明距离 | 建议处理 |
|---|---|
| 0–3 | 高概率重复 → 人工确认 |
| 4–6 | 可能相似 → 可选确认 |
| > 6 | 不算相似 → 忽略 |

**默认阈值 ≤5**（约 90% 相似）。

**关键认知对齐**："**相似 ≠ 冲突**"：两份介绍同一产品的文档可能高度相似但**都有保留价值**；工具只能判定"相似"，**不能判定"该删哪个"**，必须留给人。

**我方落地**：`app/rag/tools/pre_poc_scanner/simhash_similarity.py`（~200 行）

### 3.6 敏感信息检测（**带上下文的待审核列表**）

**做什么**：正则匹配 手机号 / 邮箱 / 身份证（银行卡默认关闭）

**第一版的错误**：只展示统计数字 "银行卡: 53 个" → **不可操作**（不知真假、不知文件、不知下一步）

**改进后每条匹配记录包含**：
- 匹配类型（phone / email / id_card）
- **脱敏后的内容**（如 `1381234****`）
- **前后 50 字符上下文**（判断真假的关键）
- 文件路径 + 字节/行号位置

```python
context_start = max(0, match.start() - 50)
context_end   = min(len(text), match.end() + 50)
context       = text[context_start:context_end]
```

**银行卡默认关闭的原因**：16 位数字正则误报率极高（合同编号、发票号、订单号全中招）。客户若需银行卡检测，需显式开启 + 人工复核上下文。

**我方落地**：`app/rag/tools/pre_poc_scanner/sensitive_info.py`（~250 行）

### 3.7 大型 Excel 分流（> 5000 行走 Text-to-SQL）

**做什么**：统计每个 xlsx 的总行数，**超过 5000 行单独标记** "建议走 Text-to-SQL / 结构化索引，非 RAG"

**为什么这么设计**：表格数据 ≠ 文本语料
- 用户问"销售额 > 100 万的客户"本质是 SQL 操作
- 向量检索**不擅长数值比较和过滤**
- 大表扁平化转文本后 token 爆炸，检索效果还差

**建议走向**：
- 元数据 + 列名入向量索引
- 原表数据走 **Text-to-SQL**（与解析切块专项 §17 / NL2SQL 呼应）
- 查询时做 tool 路由

**我方落地**：`app/rag/tools/pre_poc_scanner/large_excel_detector.py`（~120 行）

---

## 4. 5 个文档分类标签体系（**核心产品资产**）

### 4.1 标签表

| 标签 | 判断依据 | 推荐处理 |
|---|---|---|
| **Clean_Markdown** | 结构清晰、可直接解析 | 直接切块入库 |
| **Scan_PDF** | PDF 三档判定为 SCAN（扫描比例 ≥ 70%） | OCR / VLM 后再切块 |
| **Table_Heavy** | 表格占比高 / 合并单元格多 | 表格专用转换（TableFormer / DePlot） |
| **Image_Heavy** | 图片密集（PPT / 设计稿） | 多模态 VLM 处理 |
| **Parse_Failed** | 解析异常（.doc 老格式 / 密码保护 / 文件损坏） | 人工检查 |

### 4.2 为什么这 5 个标签？

- 覆盖**所有可预见的下游管线差异**
- 每个标签**对应明确的处理路径**（不是抽象的"质量分数"）
- **MECE**（互斥且穷尽）：Clean_Markdown + Scan_PDF + Table_Heavy + Image_Heavy 对应四种主要数据形态，Parse_Failed 兜底

### 4.3 与综合报告 / 切块专项的对接

| 标签 | 下游 pipeline 推荐 |
|---|---|
| Clean_Markdown | `strategies/markdown_hierarchy` + `contextual_enrichment` |
| Scan_PDF | `parsing/parsers/mineru_parser` 或 `deepseek_ocr_parser` → `strategies/pdf_layout` |
| Table_Heavy | `parsing/parsers/excel_parser` + `enrich/table_markdown` + `strategies/spreadsheet_sheet` |
| Image_Heavy | `enrich/vlm_image_caption` + 可选 `colpali_parser`（若配 VLM LLM） |
| Parse_Failed | 人工复核 + `app/parsing/routing.py` 的 fallback 机制 |

### 4.4 关键工程原则：**"解析失败 ≠ 文件损坏"**

一线踩坑：`.doc` 老格式用 python-docx 解析失败 → 原本标为 "文件损坏" → 客户 Office 打开正常 → 尴尬

**正确做法**：
- 区分三种失败：
  - `.doc` 老格式（`textutil` / LibreOffice headless / antiword / Tika 回退）→ 轻度提示
  - 密码保护 → 标记需人工解锁
  - 文件损坏（`~$` 临时文件等）→ 标记损坏
- **解析失败只是轻微扣分 / 提示**，不等于数据质量差

**我方落地**：`app/rag/tools/pre_poc_scanner/document_tagger.py`（~400 行，集成前面 7 个模块 + .doc 回退逻辑）

---

## 5. 设计原则（6 条金律）

### 5.1 输出客观数据，不做主观评分

- **砍掉的**：0–100 分的 "风险评分"、红黄绿三档
- **原因**：主观评分没业界标准，不同业务完全不同；评分反而误导
- **替代**：按规则分类（扫描件 / 解析失败 / 含敏感信息等），每条可追溯

### 5.2 所有阈值可配置

```yaml
# settings.yaml
pdf_detection:
  min_text_chars_per_page: 50
  scan_page_ratio_threshold: 0.7
sensitive:
  context_chars: 50
  enable_bank_card: false
similarity:
  simhash_distance_threshold: 5
excel:
  large_file_row_threshold: 5000
```

默认值只是"**基于项目经验的推荐**"，实际使用按业务场景调整。

### 5.3 需要人工判断的，明确标记"待确认"

- SimHash 相似 → "待确认的版本冲突列表"
- 敏感信息 → "带上下文的待审核列表"
- 低密度 PDF → "待确认类型"

**决策权始终留给人**。

### 5.4 不做主观建议（否则定位越界）

| 砍掉的主观建议 | 原因 |
|---|---|
| "推荐 chunk size 300 字" | 分块策略由业务 + embedding + 场景共同决定 |
| "预计 chunk 数 / token 数" | 依赖假设太多，参考价值低 |
| "风险极高，建议立即处理" | 不同业务对风险定义不同 |

**只给客观数据，让人做决策**。

### 5.5 服务下游（不是静态质检报告）

输出不是 **"一份报告"**，而是 **"一份可操作的配置清单"**：告诉下游 pipeline 每个文档应走什么处理路径（§4 标签）。

### 5.6 单一数据源原则（呼应 POC 归因专项 §2.3）

- 不要双写 JSONL + SQLite
- 一次扫描结果落 **SQLite + 单文件 HTML**（HTML 是 SQLite 的离线快照，不是独立源）

---

## 6. 被砍掉的功能（决策逻辑即方法论）

### 6.1 文档截图预览（砍）

**原想法**：列表悬浮显示文档首页截图，不打开文件快速判断

**砍掉原因**：
- PDF 用 PyMuPDF 可做（简单）
- **Word / Excel 自动截图必须用 LibreOffice / Headless Browser**
- Docker 镜像从几百 MB 膨胀到几 GB
- 投入产出比严重失衡

**替代**：**"一键打开原文件"**（`subprocess.run(['open', file_path])`）—— 30 行代码，产品体验提升一个量级

### 6.2 智能聚类（砍）

**原想法**：K-Means 聚类自动发现文档分类（"合同" / "技术文档" ...）

**砍掉原因**：
1. **定位越界**：这是"语义分析"，属于下游 RAG 系统的事；预检工具应专注**结构化质检**
2. **环境负担**：Embedding 模型 + Torch → 依赖膨胀几百 MB
3. **K 值难自动选**：肘部法效果不稳（尤其小规模数据）
4. **工具性质改变**：一旦引入 embedding，整个工具的设计语义就变了

**保留想法**：若后续有需求，可作**独立插件**。

### 6.3 砍功能的决策框架（**可复用方法论**）

| 砍掉标准 | 典型案例 |
|---|---|
| **主观不可复现** | 风险评分 / 健康评分 |
| **画蛇添足**（本不该此工具做） | 推荐 chunk size / 预计 token 数 |
| **投入产出比低** | 截图预览 |
| **定位越界**（性质改变） | 智能聚类 / embedding |
| **依赖重**（部署门槛上升一个量级） | 基于 LibreOffice headless 的各类自动化 |

这个框架可以用于**所有工具包功能决策**——预检、POC、评测集 Stage 0、生产运维工具。

---

## 7. 离线报告"三原则"（售前决胜关键）

### 7.1 三原则

1. **彻底脱敏**
   - 文件名 → `FILE_A023`
   - 路径 → 移除（只保留相对层级 `level_1/level_2/...`）
   - 敏感信息 → **只保留聚合计数**（不留具体匹配记录）

2. **客观中立**
   - **移除所有主观评价**："建议优化" / "风险极高" / "不推荐入库" 全删
   - 只展示**客观事实**：格式分布 / 标签分布 / 长度分位数 / 相似度列表

3. **单文件 HTML**
   - 图表（ECharts）、样式、JS 全部**内联**
   - 客户**双击即可打开**（无需 Node 构建、无需服务端）
   - 可直接作为邮件附件发送

### 7.2 拿到报告后，乙方决策流程

```
收到 FILE_A023.html
  → 看总览：扫描型 PDF 占 %？表格密集占 %？P90 长度？
  → 若复杂度不高 → 直接报价，范围/周期/价格讲清楚
  → 若复杂度高或数据量大 → 建议先做付费 POC
       → POC 合同中明确 OCR 外部 API 等额外成本
  → 若数据本身就不适合 RAG → 直接打回，建议做数据治理前置
```

### 7.3 客户侧的报告反应（三档）

| 报告呈现 | 典型客户反应 |
|---|---|
| 扫描比例 < 10% + 敏感信息 < 5 条 + Clean_Markdown > 70% | "可以直接干" → 快速签单 |
| 扫描 30–50% + 敏感信息较多 + Table_Heavy 突出 | "需要 POC 看看" → 付费 POC |
| 扫描 > 60% + 大量 Parse_Failed | "先别做 RAG 了，让我们先整理数据" → 打回前置 |

---

## 8. 产品体验打磨："一键打开"闭环

### 8.1 从"看报告"到"做处理"

**错误的产品形态**：静态报告 → 客户看完不知下一步

**正确的产品形态**：报告中**每条异常都是可点击的**

```python
# 点击"需 OCR：4 份" → 展开文件列表 → 点列表项 → 直接打开原文件
subprocess.run(['open', file_path])       # macOS
subprocess.run(['xdg-open', file_path])   # Linux
subprocess.run(['start', file_path])      # Windows
```

**从仪表盘 → 控制台**的升级，是**产品体验最决定性的 5% 工作量**。

### 8.2 我方落地建议

- 交互式仪表盘（非离线脱敏报告）支持一键打开
- 离线脱敏报告**只显示聚合数据**，不支持打开（因为已脱敏文件名 / 路径）
- 两种报告同代码仓库 + 同前端模板 + **不同的数据过滤层**

---

## 9. 我方落地方案

### 9.1 目录骨架

```
app/rag/tools/pre_poc_scanner/
├── scanner.py                       # 入口 CLI + API
├── settings.py                      # 阈值配置
├── core/
│   ├── format_distribution.py       # §3.1
│   ├── pdf_page_classifier.py       # §3.2（三档）
│   ├── length_distribution.py       # §3.3
│   ├── md5_dedup.py                 # §3.4
│   ├── simhash_similarity.py        # §3.5
│   ├── sensitive_info.py            # §3.6
│   └── large_excel_detector.py      # §3.7
├── tagger/
│   └── document_tagger.py           # §4 5 标签体系
├── exporters/
│   ├── sqlite_store.py              # 单一数据源
│   ├── offline_html_report.py       # 离线脱敏报告（售前）
│   └── dashboard_server.py          # FastAPI + SSE + ECharts
├── adapters/                        # .doc 等格式兼容
│   ├── textutil_adapter.py          # macOS
│   ├── libreoffice_adapter.py       # 跨平台
│   └── fallback_chain.py
├── frontend/                        # 原生 HTML/CSS/JS + ECharts
│   ├── dashboard.html
│   ├── offline_report.html          # 单文件版（内联所有资源）
│   └── assets/
└── tests/
```

**预计规模**：后端 ~2500 行 + 前端 ~3000 行 = **~5500 行**，4–6 周交付。

### 9.2 与 RAG 主管线的集成

```
用户上传 dataset
  ↓
[dataset_precheck_service.py]（已有）
  ↓ 调用 pre_poc_scanner
[pre_poc_scanner 产出 JSON + 5 标签]
  ↓
[按标签分流到不同 parser / chunker]
  ├─ Clean_Markdown → markdown_hierarchy
  ├─ Scan_PDF      → mineru / deepseek_ocr + pdf_layout
  ├─ Table_Heavy   → excel / table_markdown + spreadsheet_sheet
  ├─ Image_Heavy   → vlm_image_caption + (optional ColPali)
  └─ Parse_Failed  → 人工队列 / fallback 链
```

### 9.3 与现有 plan 的交叉引用

| 本文 | 现有 plan | 关系 |
|---|---|---|
| §3.2 PDF 三档 | 解析切块专项 §2–3 | 分流结果驱动 parser 选择 |
| §3.3 长度分布 | 解析切块专项 §7 | P90 决定切块策略网格 |
| §3.5 SimHash | 综合报告 §4 预处理 | near-dedup 的前置筛选 |
| §3.6 敏感信息 | 安全合规专项 §6 Presidio | 预检发现 → Presidio 规则库扩展 |
| §3.7 大 Excel | 解析切块专项 §17 NL2SQL | 分流 NL2SQL |
| §4 5 标签 | POC 归因专项 §7 行业规则库 | 标签是意图分类前的结构标签 |
| §7 离线报告 | POC 归因专项 §1.2 减法原则 | 产品化延伸 |

### 9.4 作为售前 / 售后资产

| 场景 | 交付物 | 时间线 |
|---|---|---|
| 售前报价 | 离线脱敏 HTML 单文件 | 0.5 天 |
| 项目启动摸底 | 交互式仪表盘 + JSON 标签清单 | 1 天 |
| 一期 / 二期范围对齐 | 标签分布图 + 复杂度分析 | 1 天 |
| 企业内部 IT 资产盘点 | 定制化仪表盘 | 2 天 |

---

## 10. 优先级矩阵（与其他 plan 并列排序）

### 🥇 P0（立即启动）

| # | 建议 | 理由 |
|---|---|---|
| 1 | `core/` 7 个模块 + `document_tagger.py` | 工具包骨架，0→1 |
| 2 | `exporters/offline_html_report.py` | 售前决胜关键 |
| 3 | `.doc` 老格式 + 解析失败精细分类（§4.4） | 踩坑修正，必须做 |

### 🥈 P1（产品化打磨）

| # | 建议 | 理由 |
|---|---|---|
| 4 | `exporters/dashboard_server.py` + 一键打开 | 体验升级 |
| 5 | PyInstaller 单文件打包 | 客户零依赖使用（Docker 打包作为备选） |
| 6 | 与 `services/dataset_precheck_service.py` 集成 | 工具包反哺生产管线 |
| 7 | 可配置阈值 CMS | 业务人员自助调整 |

### 🥉 P2（扩展）

| # | 建议 |
|---|---|
| 8 | 多语言支持（中英日） |
| 9 | 企业内网私有模式（无公网、零 telemetry） |
| 10 | 定期扫描 + diff 报告（治理视角） |
| 11 | 加密 PDF / 权限保护 PDF 检测 |

### 观望 / 不做

- 智能聚类（定位越界，§6.2）
- 截图预览（投入产出比，§6.1）
- 主观评分 / 健康打分（§5.1）

---

## 11. 关键踩坑总结（给工程师的警告）

| 坑 | 表现 | 正确做法 |
|---|---|---|
| "解析失败 = 文件损坏" | `.doc` / 老格式被误判 | 区分三种失败；`.doc` 走 `textutil` / LibreOffice 回退 |
| 敏感信息只给数字 | "银行卡: 53 个" 不可操作 | 带上下文的待审核列表；银行卡默认关 |
| 风险评分 0-100 | 扫描 PDF 因"解析成功 + 无敏感"得 100 分 | 砍掉评分，改为规则标签 |
| 推荐 chunk size | 超出工具定位 | 砍掉；留给下游 |
| 双写 JSONL + SQLite | 反馈字段不同步 | 单一数据源 |
| PDF 二档判定 | 双层 PDF / 图文混排被误分 | 三档（scan / text / low_density）+ 70% 阈值 |
| 大 Excel 入向量库 | token 爆炸 + 检索差 | > 5000 行建议 Text-to-SQL |
| SimHash 结果直接删 | "相似 ≠ 冲突" | 输出"待确认的版本冲突列表"，人工决策 |
| 截图预览 | LibreOffice 膨胀镜像 | "一键打开"代替 |

---

## 12. 参考资料

### 技术栈（工具侧）
- FastAPI、SSE（Server-Sent Events）
- ECharts（图表）
- PyMuPDF（PDF 处理）
- python-docx、openpyxl、python-pptx
- SimHash（Charikar, 2002）
- textutil（macOS）、LibreOffice headless、antiword、Apache Tika

### 本项目相关 plan（交叉引用）
- `plans/rag-capability-gap-2026-q2.md` §4 预处理与数据质量
- `plans/rag-deep-research-2026-q2.md` §6 预处理与数据治理
- `plans/rag-parsing-chunking-deep-dive-2026-q2.md` §2–5（PDF 三档 / 长度分布 / 大 Excel）
- `plans/rag-safety-compliance-deep-dive-2026-q2.md` §6 Presidio PII（敏感信息下游）
- `plans/rag-poc-attribution-framework-2026-q2.md`（Pre-POC → POC 的衔接）
- `plans/rag-eval-dataset-deep-dive-2026-q2.md` §4 Stage 1 前置

### 产品定位参考
- 本工具包是**垂直 SaaS 的数据治理组件**（而非通用 RAG 框架）
- 相比 RAGFlow / Dify / FastGPT 等全功能框架，本工具**只解决入库前最窄的质检问题**，刻意保持轻量

---

## 13. 结论

1. **Pre-POC Scanner 是 RAG 项目的"数据体检机"**——在任何架构决策之前，让客户和乙方看见真实数据全貌
2. **设计的核心不是"功能多"，而是"砍的准"**：砍掉主观评分 / 画蛇添足 / 定位越界 / 投入产出比低的功能，让留下的每个都**具象且可操作**
3. **5 标签体系 + 三原则离线报告** 是本工具的产品化资产，可直接面向售前 / 售后 / 内部治理三场景
4. **与现有 8 份 RAG plan 完全正交**，但**时间线最前置**——是 POC 之前、评测集之前、任何架构讨论之前的第一步
5. **预计工程量 ~5500 行，4–6 周可交付**；客户反馈已实测打磨三四轮，产品形态相对成熟

**落地建议**：与 POC 归因框架（第 8 份 plan）并行启动 P0 项。两个工具合在一起，构成 **"Pre-POC Scanner → POC 一周运营工具 → 评测集 Stage 1–4"** 的完整运营闭环。

---

> **可独立拆的子 plan**：
> - `plans/scanner-core-7-modules.md`（§3 七个核心模块）
> - `plans/scanner-document-tagger.md`（§4 五标签 + .doc 兼容）
> - `plans/scanner-offline-report.md`（§7 离线脱敏 HTML）
> - `plans/scanner-dashboard-ui.md`（交互式仪表盘 + 一键打开）
> - `plans/scanner-pyinstaller-packaging.md`（单文件交付）
> - `plans/scanner-dataset-precheck-integration.md`（与生产管线集成）

> **至此 RAG 专项报告体系共 9 份，合计约 5600+ 行**：
> - 第 1–4 份：综合对标 + 深度调研 + 评测集 + KG
> - 第 5–7 份：Agentic / 解析切块 / 安全合规
> - 第 8 份：POC 归因框架（运营手册）
> - 第 9 份：**Pre-POC Scanner（本文，入库前预检）**
