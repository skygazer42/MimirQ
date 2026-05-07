# DeepDoc API 化（P1-2，2026 Q3）

> 把 MimirQ 自家 deepdoc 解析栈（~5300 行 vision + 269 行 parser）抽离为独立 *Parsing-as-a-Service* API，对标 Reducto（$1-5/页）/ Mistral OCR / PageIndex Cloud OCR，抢"解析即服务"市场。
>
> 创建日期：2026-05-07
> 来源：`rag-system-landscape-2026-q2-supplement.md` 第 5.3 节"快被追平的解析栈" + 第 7.2 P1-2
> 论据：解析层正在成为独立产品赛道；MimirQ 工程深度不输商业产品，但**未对外销售**
>
> **核心一句话**：deepdoc 内部代码不动，只在外围补 *独立 API + SDK + 计费 + SKU*；4 周可形成可销售产品，对标海外 Reducto / Mistral OCR 切中文 + 政务部署差异化。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 现状 + 为什么 API 化 |
| 第 2 章 | 业界对标（Reducto / Mistral OCR / Marker / Unstructured / Azure Document Intelligence） |
| 第 3 章 | 6 个落点（API + SDK + 计费 + 鉴权 + 文档 + 演示） |
| 第 4 章 | API 设计 |
| 第 5 章 | SKU + 价格 |
| 第 6 章 | 里程碑（4 周 MVP + 8 周 GA） |
| 第 7 章 | 验证 + 客户验证 |
| 第 8 章 | 风险 + 范围之外 |

---

## 1 现状 + 为什么 API 化

### 1.1 deepdoc 现有规模

| 模块 | 文件 | 行数 |
|---|---|---|
| Vision 主栈 | `app/deepdoc/vision/` | ~5300（含 layout / OCR / recognizer / operators / postprocess / table 6 大模块） |
| OCR 引擎 | `app/deepdoc/vision/ocr.py` + `_ocr.py` | 972 |
| Layout | `app/deepdoc/vision/layout_recognizer.py` | 254 |
| Table | `app/deepdoc/vision/table_structure_recognizer.py` | 597 |
| Parser 接入 | `app/parsing/parsers/deepdoc_parser.py` | 269 |
| 当前 API（绑文档） | `app/api/v1/parsing.py` | 1537 |

### 1.2 现有 API 只服务内部（不可外部购买）

现有 `/api/v1/parsing/documents/{id}/parse` 必须先创建 dataset / document 才能调用 —— **不适合外部 API 销售**。

### 1.3 为什么 API 化

| 理由 | 说明 |
|---|---|
| **解析层正在成为独立产品** | Reducto / Mistral OCR / Unstructured 都在抢，2024-2026 市场快速增长 |
| **MimirQ 工程深度不输商业** | 5300 行 vision + 中文 + 表格栈，已具备产品基础 |
| **抢中文 + 政务部署差异化** | Reducto / Mistral 中文不强、不能进政务专网 |
| **流量入口 + 销售线索** | 用 API 做开发者获客，导流到完整 RAG 产品 |
| **PoC-to-MVP 客户复用** | 客户买 API 即可用，不必接完整 RAG |

### 1.4 不动的部分

- 不动 `app/deepdoc/vision/` 任何代码（5300 行内部栈不变）
- 不动 `app/parsing/parsers/deepdoc_parser.py`
- 不破坏现有 `/api/v1/parsing/...` 文档绑定 endpoint
- 仅在外围加新 endpoint group + SDK + 计费

---

## 2 业界对标

### 2.1 6 家对标矩阵

| 厂商 | 价格 | 强项 | 弱项 | 中文 |
|---|---|---|---|---|
| **Reducto** | $1-5/页 | 表格强、SaaS 易用 | 英文为主 | 中 |
| **Mistral OCR** | API 按页 | EU 部署 + Mistral 生态 | 新产品 | 中 |
| **Marker** | 开源 | MIT、本地跑 | 学术质量 | 弱 |
| **Unstructured.io** | freemium + Enterprise | 兼容性广（多格式）| 表格弱 | 中 |
| **Azure Document Intelligence** | $1-5/页 | 微软生态 | 中文一般 | 中 |
| **Adobe Extract API** | Enterprise | PDF 原厂 | 价格高 | 中 |
| **PageIndex Cloud OCR** | API | 含 tree builder | 新 | 弱 |

### 2.2 MimirQ deepdoc 优势 / 劣势

**优势**：
- 中文 OCR 强（含简繁 / 横竖排）
- 表格识别（597 行 table_structure_recognizer）业界一线
- Layout 识别 + 公式 + 化学式
- 可私有化部署（等保 2.0 / 政务专网）—— 海外厂商**进不来**

**劣势**：
- 无对外 API
- 无 SDK
- 无计费 / 鉴权
- 无开发者文档
- 无 demo 站
- 无社区

### 2.3 差异化定位

> **"中文 + 政务可部署的 Reducto"**

- **价格策略**：略低于 Reducto（¥3-10/页 vs $1-5）
- **部署模式**：API + 私有化双轨
- **目标客户**：中国开发者 + 中国央企法务 / 金融

---

## 3 6 个落点

| # | 落点 | 文件路径 | 工作量 |
|---|---|---|---|
| 1 | 独立 OCR API endpoint | `app/api/v1/ocr_service.py` | ~250 行 |
| 2 | Python SDK | `sdk/python/mimirq_ocr/` | ~300 行 |
| 3 | Node SDK | `sdk/node/mimirq-ocr/` | ~250 行 |
| 4 | 计费 + 限流 + 鉴权 | `app/services/ocr_billing.py` | ~200 行 |
| 5 | 开发者文档 + demo 站 | `docs/ocr/` + `web/app/dev/ocr-playground/` | ~400 行 |
| 6 | 监控 / observability | `app/observability/ocr_metrics.py` | ~100 行 |
| **合计** | | | **~1500 行 / 4 周** |

---

## 4 API 设计

### 4.1 Endpoint group `/api/v1/ocr`

```
POST   /api/v1/ocr/parse              # 上传文件，同步解析
POST   /api/v1/ocr/parse-async        # 异步解析（大文件）
GET    /api/v1/ocr/jobs/{job_id}      # 查询异步状态
POST   /api/v1/ocr/parse-url          # 提供 URL，服务端拉取
GET    /api/v1/ocr/usage              # 查用量 / 配额
GET    /api/v1/ocr/limits             # 速率限制
```

### 4.2 核心 endpoint：`POST /parse`

**请求**：
```http
POST /api/v1/ocr/parse
Content-Type: multipart/form-data
Authorization: Bearer <api_key>

file: <PDF/PNG/JPG/DOCX/...>
mode: "fast" | "accurate" | "table-focused"  # 三档
output_format: "markdown" | "json" | "html"
options:
  ocr_lang: "zh+en"
  extract_tables: true
  extract_images: false
  preserve_layout: true
```

**响应**：
```json
{
  "schema": "mimirq.ocr_result.v1",
  "job_id": "ocr_xxx",
  "status": "completed",
  "pages": 12,
  "duration_ms": 4523,
  "credits_consumed": 12,
  "result": {
    "markdown": "# 标题\n\n...",
    "json": [
      { "page": 1, "type": "heading", "text": "...", "bbox": [10,20,300,50] },
      { "page": 1, "type": "table", "rows": [...], "bbox": [...] }
    ]
  },
  "metadata": {
    "deepdoc_version": "1.0.0",
    "ocr_engine": "deepdoc-zh-v2"
  }
}
```

### 4.3 三档解析模式

| 模式 | 算法 | 速度 | 价格 | 适用 |
|---|---|---|---|---|
| **fast** | 仅 OCR + 简单 layout | 1-2s/页 | ¥3/页 | 日常文档 |
| **accurate** | 完整 deepdoc 全栈 | 3-5s/页 | ¥6/页 | 财报 / 法规 |
| **table-focused** | accurate + 表格深度 | 4-7s/页 | ¥10/页 | 财报附表 / 政府表格 |

### 4.4 异步流程（大文件）

```
client → POST /parse-async → job_id (immediate)
client → GET /jobs/{job_id}  → status: processing
client → GET /jobs/{job_id}  → status: completed + result_url
client → download result
```

支持 webhook 回调（POST 到客户指定 URL）。

### 4.5 错误码

| Code | Meaning |
|---|---|
| 400 | 文件格式不支持 |
| 401 | API key 无效 |
| 402 | 余额不足 |
| 413 | 文件超限（默认 200MB） |
| 422 | 解析失败（如扫描质量太差） |
| 429 | 速率限制 |
| 500 | 服务端错误 |

---

## 5 SKU + 价格

### 5.1 三档套餐

| 套餐 | 月费 | 含页数 | 超出 | 限速 | 部署 |
|---|---|---|---|---|---|
| **Free** | ¥0 | 100 页 / 月 | — | 1 RPS | SaaS |
| **Developer** | ¥299/月 | 5,000 页 | ¥3/页 | 10 RPS | SaaS |
| **Pro** | ¥1,999/月 | 50,000 页 | ¥2/页 | 50 RPS | SaaS / VPC |
| **Enterprise** | 询价 | 无限 | 协商 | 协商 | 私有化 |

### 5.2 按量付费（替代订阅）

- ¥3/页（fast）
- ¥6/页（accurate）
- ¥10/页（table-focused）
- 私有化：¥30-100 万 / 年（按算力 + 文档量）

### 5.3 与海外对比

| 厂商 | 等价价格 |
|---|---|
| Reducto $1-5/页 | ¥7-35/页 |
| Mistral OCR ~$0.5/页 | ¥3.5/页 |
| Unstructured Enterprise | $$$ |
| **MimirQ ¥3-10/页** | **持平 / 略低** |

### 5.4 增值服务（提价点）

- 实时解析（pre-warming worker，<1s/页）+50%
- 自定义 schema 抽取（金融 / 医疗 / 法规）+100%
- 私有化部署 + ¥30-100 万 / 年
- 行业模板包（财报 / 招股书 / 法规）订阅 ¥2,000/月

---

## 6 里程碑（4 周 MVP + 8 周 GA）

### 6.1 P1-2 MVP（第 1-4 周）

#### 第 1 周 — 后端 API
- [ ] `app/api/v1/ocr_service.py` endpoint group 完成
- [ ] 同步 `POST /parse` 跑通（小文件）
- [ ] 三档模式实现（fast / accurate / table-focused）
- [ ] 异步 `/parse-async` + job 查询
- [ ] 鉴权（API key + 速率限制）

#### 第 2 周 — 计费 + 监控
- [ ] `app/services/ocr_billing.py` 计费引擎（按页 + 按模式）
- [ ] `app/observability/ocr_metrics.py` 监控（QPS / 成功率 / 延迟）
- [ ] 用量查询 endpoint
- [ ] 余额扣减 + 透支保护

#### 第 3 周 — SDK
- [ ] `sdk/python/mimirq_ocr/` Python SDK
- [ ] `sdk/node/mimirq-ocr/` Node SDK
- [ ] 单元测试 + 集成测试
- [ ] PyPI / npm 发布（beta）

#### 第 4 周 — 文档 + Demo + 内部 alpha
- [ ] `docs/ocr/` 开发者文档（Quickstart + API 参考）
- [ ] `web/app/dev/ocr-playground/` 在线试用页面
- [ ] 内部 alpha：3-5 个工程师试用
- [ ] 反馈 → 修复 → 准备 GA

### 6.2 GA（第 5-8 周）

- [ ] 5 个外部开发者邀请测试（free 套餐）
- [ ] 计费打通（支付 / 发票）
- [ ] 与 Reducto / Mistral OCR 对比测试报告
- [ ] 销售物料（一页纸 + 价格表 + 客户案例）
- [ ] 公开 launch（产品猎手 / 中文社区）

### 6.3 P3 半年后

- [ ] 中文 OCR benchmark 报告（OmniDocBench-CN 自建）
- [ ] 行业模板包（财报 / 招股书 / 法规）
- [ ] 客户 1 个付费签约
- [ ] ARR 目标：6 月内 ¥100 万

### 6.4 工作量

| 阶段 | 工时 |
|---|---|
| MVP 后端 + SDK | 3 周 / 2 工程师 |
| 文档 + Demo | 1 周 / 1 工程师 + 1 PM |
| GA 销售 / 计费 | 4 周 / 1 全栈 + 1 PM |
| **合计** | **8 周** |

---

## 7 验证 + 客户验证

### 7.1 技术验证

- [ ] **OmniDocBench**（业界标准）评测 deepdoc vs Reducto / Mistral OCR / Marker
  - 目标：accuracy ≥ 业界平均
- [ ] **OmniDocBench-CN 自建**（中文专项）
  - 目标：accuracy 高于 Mistral OCR / Reducto 中文 ≥ 5pt
- [ ] 表格识别：F1 ≥ 0.85（PubTables / 自建中文集）
- [ ] 速度：fast 模式 ≤ 2s/页 (P95)、accurate ≤ 5s/页

### 7.2 计费验证

- [ ] 1 万次调用计费正确
- [ ] 速率限制按套餐生效
- [ ] 透支保护正常

### 7.3 客户验证

- [ ] 5 个开发者 free 测试 → 转 ¥299 套餐 ≥ 1 个
- [ ] 1 个企业客户 PoC → ¥30 万签约
- [ ] 1 个律所 / 法务 → 拍合规报告解析 + ¥10 万签约

### 7.4 与 P1-1 协同

- 合规自动化（P1-1）的"条款级 parser" 直接用本 API，免重复开发
- 给合规客户卖 *合规版 OCR*（含法规 / 合同模板）

---

## 8 风险 + 范围之外

### 8.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 与现有 internal API 冲突 | 重复 / 矛盾 | endpoint group 隔离 + 复用 deepdoc 内部代码 |
| 计费 bug 导致超扣 | 客户投诉 | 透支保护 + 双重 audit |
| OCR 质量不及商业 | 客户流失 | OmniDocBench 跑通 + 持续优化 |
| 中文场景 bug | 中文客户失败 | 中文专项测试集 |
| 价格战 | 海外低价进入 | 私有化 + 中文 vertical 差异化 |
| API 滥用 / 爬虫 | 资源浪费 | 速率限制 + 鉴权 + 异常检测 |
| 大模型备案要求 | 含 LLM 输出环节需备案 | 仅纯 OCR 不涉及 LLM 输出，规避 |

### 8.2 范围之外（明确不做）

- 不动 `app/deepdoc/vision/` 内部代码
- 不做翻译功能（OCR 完即停）
- 不做内容理解 / 摘要（属于完整 RAG 产品）
- 不做表格 → 数据库（属于 Text-to-SQL 范畴）
- 不做语音 OCR / 视频 OCR（视频 RAG 范畴）
- 不开放 self-host 开源版（保留商业护城河）

### 8.3 不要的东西

- ❌ 不做"AI 增强"营销词，OCR 就是 OCR
- ❌ 不做免费无限套餐（成本压力）
- ❌ 不做按 token 计费（按页清晰）
- ❌ 不做 API 完全开源（保留商业护城河，仅 SDK 开源）

---

## 9 商业模式

### 9.1 收入模型

| 来源 | 占比预估 |
|---|---|
| SaaS 订阅 | 40% |
| 按量付费 | 30% |
| 私有化部署 | 20% |
| 增值服务（行业模板 / 自定义 schema） | 10% |

### 9.2 客户漏斗

```
开发者 free 试用 →  ¥299 / ¥1,999 套餐  →  企业 PoC  →  完整 RAG 产品
       (流量)              (变现)              (转化)        (复购)
```

### 9.3 销售渠道

- 中文开发者社区（V2EX / 掘金 / 少数派 / SegmentFault）
- 中文 dev meetup
- 阿里云 / 腾讯云 / 华为云市场（mp.aliyun.com）
- GitHub README + 中文教程

---

## 10 与既有 plan 协同

| 既有 plan | 协同点 |
|---|---|
| `rag-parsing-chunking-deep-dive-2026-q2.md` | 解析栈深化 |
| `rag-parsing-frontend-deep-dive-2026-q2.md` | 前端展示 |
| `rag-pre-poc-scanner-2026-q2.md` | Pre-POC scanner 复用本 API |
| `rag-compliance-automation-2026-q3.md`（P1-1） | 合规客户复用本 API |
| `rag-system-landscape-2026-q2-supplement.md` 第 5.3 节 | 本 plan 是其落地 |
| `rag-pageindex-deep-dive-2026-q2.md` | MimirQ deepdoc 优于 PageIndex 上游 PyPDF2 |
| `industry-rules-productization-2026-q2.md` | 行业 OCR 模板与规则库联动 |

---

## 11 决策门槛

### 11.1 启动 P1-2 的门槛

- [ ] P0-2 中文 benchmark 跑完，确认 deepdoc 在 OmniDocBench 等业界基准上 ≥ Reducto / Mistral
- [ ] 法务确认大模型备案不阻塞（纯 OCR 应当不涉及）
- [ ] 商务调研 5 个潜在客户中至少 3 个表达"愿意付费"

### 11.2 GA 后启动 P3（半年生态）的门槛

| 条件 | 决策 |
|---|---|
| 6 月内 ARR ≥ ¥100 万 | **加大投入**（增加销售 / 行业模板包） |
| ARR < ¥30 万 | **复盘**（产品 / 价格 / 销售哪里出问题） |
| 客户主要来自 RAG 产品交叉销售 | 保留 OCR 作为引流，主业仍是完整 RAG |
| 客户独立购买 OCR 占主导 | 把 OCR 升级为独立产品线 |

---

## 12 完成后输出

1. **代码**：~1500 行（API + SDK + 计费 + 文档 + demo）
2. **API 文档**：完整开发者文档站
3. **SDK**：Python + Node + 中文教程
4. **Demo 站**：在线试用 + 价格页
5. **第一批客户**：5 个 free + 至少 1 个付费
6. **MEMORY.md 索引项**：追加一条
