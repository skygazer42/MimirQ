# POC → MVP 完整交付蓝图（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：第 12 份 RAG 专项。前 11 份分别覆盖业界对标、深度论文、评测集、KG、Agentic、解析切块、安全、POC 归因、Pre-POC 预检、IBM 冠军方案、上下文扩展重排；本文讲 **"POC 验证通过后，如何在 1–2 周内升级到生产级 MVP"** —— 从 Streamlit 原型到 FastAPI + Next.js + Supabase + MinIO 的完整栈升级。
> **案例来源**：工控软件厂商售后知识库项目，4 万客户 / 20+ 工程师 / 1600 份 Word 文档，**两周交付 POC + MVP 全链路**，现已部门试点。
> **核心增量**（与前 11 份正交）：**Parent-Child 连坐召回、LLM 元数据三字段、双重输出 Markdown+DOCX、Supabase 4 表+RLS 踩坑、Rerank 漏斗整形、图片双阶段进化**。

---

## 1. POC → MVP 的阶段边界（**先明确做什么 / 不做什么**）

### 1.1 两阶段定位

| 阶段 | 目标 | 前端 | 数据闭环 | 周期 |
|---|---|---|---|---|
| **POC** | 验证"**数据清洗 + 检索精度**"的可行性 | Streamlit 快速原型 | 基础反馈入库 | 1 周 |
| **MVP** | 从"能用"到"好用"，支撑部门级试点 | FastAPI + Next.js 前后端分离 | 完整数据闭环 + 运营 Dashboard | 1 周 |

**关键原则**：**RAG 引擎核心代码直接从 POC 复用**，MVP 阶段重点在**体验层 + 闭环层**。

```python
# FastAPI 复用 POC 算法
sys.path.append(os.path.abspath('../../POC'))
from rag_engine import IndustrialRAG
rag_engine = IndustrialRAG()
```

### 1.2 POC 阶段刻意不做的 5 件事（呼应 POC 归因专项 §1.2）

| 砍掉 | 原因 |
|---|---|
| 前后端分离 | Streamlit 验证算法足够 |
| 对象存储 | Base64 暂用 |
| SSE 流式 / SWR 缓存 | 等待几秒可接受 |
| 运营 Dashboard | 只需 5 字段埋点 |
| 多租户 / 外部系统集成 | 先跑通主路径 |

### 1.3 MVP 阶段必做的 7 件事（本文重点）

1. Parent-Child 连坐召回（检索核心）
2. LLM 元数据三字段（召回增强）
3. 双重输出 Markdown+DOCX（机器侧 / 用户侧分离）
4. 图片 MinIO 映射（解决 Base64 痛点）
5. Supabase 4 表数据闭环
6. Next.js + SSE + SWR 前端体验
7. 容器化 + 两种维护模式

---

## 2. 数据清洗的 LLM 辅助迭代法

### 2.1 多轮抽样工作流（**可直接套用**）

```
Round 1: 随机抽 10 份
  → python-docx 提取文本
  → 喂 LLM 识别噪音模式
  → 整理正则规则

Round 2: 随机抽 20 份（覆盖 Round 1 未涉及的目录 / 分类）
  → 发现新噪音
  → 扩展正则规则

Round 3-4: 全量跑 + 人工抽检
  → 规则收敛
```

### 2.2 工控场景典型噪音清单（**给其他行业参考**）

```python
NOISE_PATTERNS = [
    # 页面结构
    r'.* - 汇总信息$',            # 页尾
    r'^帖子列表$',
    r'^详细帖子内容$',
    r'^未知标题$',
    # 论坛交互
    r'^共找到 \d+ 个帖子$',
    r'^【主帖内容】$',
    r'^【回复 \d+ - .*】$',
    r'^回复时间：.*$',
    r'^暂无回复$',
    # 附件 / 下载
    r'^点击文件名下载附件$',
    r'^\([\d\.]+\s*(MB|KB),\s*下载次数:\s*\d+\)$',
    r'^.*\.zip$',
    # 多媒体 / 格式残留
    r'^您的浏览器不支持 video 或 audio 标签$',
    r'复制代码$',                  # 代码块按钮残留
    r'^-+$',
    r'^\d+$',
]
```

### 2.3 不同数据源的噪音类型（行业迁移提示）

| 源 | 典型噪音 |
|---|---|
| 内网 wiki | 页眉页脚 / 时间戳 / 下载统计 / 论坛元素 |
| PDF 转换 | 页码 / 表头重复 / 分栏错位 |
| 邮件归档 | 签名 / 转发链 / 自动回复 |
| 客服工单 | 工单模板字段 / 系统流程日志 |
| 爬虫结果 | 广告 / 导航 / JS 占位符 |

### 2.4 我方落地

- **P0** `app/parsing/preprocess/industry_noise_patterns/` 按行业分文件夹
  - `industrial_control.py`（本文工控栈）
  - `finance.py`（财报）
  - `legal.py`（合同）
- **P0** `preprocess/llm_noise_miner.py`：多轮抽样 + LLM 识别 + 正则生成 + 人工复核工作流
- **交叉引用**：POC 归因专项 §7（行业规则库术语映射）相呼应

---

## 3. 双重输出：Markdown + DOCX（**机器 / 用户职责分离**）

### 3.1 核心设计

| 输出 | 格式 | 用途 | 特点 |
|---|---|---|---|
| **机器侧** | Clean Markdown | 向量化入库 | 去格式、保语义 |
| **用户侧** | Clean DOCX | 引用卡片点击跳转 | 保格式、保表格、标题高亮 |

### 3.2 代码范式

```python
def process_file(file_path):
    doc = Document(file_path)
    clean_doc = Document()
    md_lines = []

    for element in doc.element.body.iter():
        if element.tag.endswith('blip'):
            save_image(...)  # 提取嵌入图片

    for para in doc.paragraphs:
        text = para.text.strip()
        if is_noise(text):
            continue
        if is_image_placeholder(text):
            md_lines.append(f"![img](images/{img_name})")
            clean_doc.add_picture(img_path)
        else:
            md_lines.append(text)
            clean_doc.add_paragraph(text)

    # 双重保存
    clean_doc.save(f"{title}_Clean.docx")
    save_markdown(md_lines, f"{title}.md")
```

### 3.3 与 Pre-POC Scanner "一键打开" 的协同

这是"**点击原文件可直接看**"的深化版——
- Pre-POC：点击打开**原始文件**（治理侧）
- MVP：点击打开**清洗后的 Clean DOCX**（用户侧，无噪音干扰）

### 3.4 我方落地

- **P0** `parsing/output/{markdown_writer,docx_writer}.py` 双写器
- **P0** 引用卡片的"查看原文"跳转指向 Clean DOCX（不指向原文件）
- **P1** DOCX 标题高亮用户提问关键词（定位体验）

---

## 4. LLM 元数据增强：三字段体系（**召回的语义放大器**）

### 4.1 三字段设计

| 字段 | 用途 | 配合检索策略 |
|---|---|---|
| **summary**（一句话摘要） | 结果页快速预览 + 富语义 chunk 头 | 缩短 LLM 判断时间 |
| **keywords**（5–8 个技术术语） | 辅助召回、弥补向量对专业术语的弱点 | 关键词匹配通道 |
| **questions**（3–5 个文档能回答的问题） | **HyDE 风格检索** | 用户问法 vs 文档问法更接近 |

### 4.2 生成策略

```python
def process_item(item):
    if item.get("summary"):
        return   # 断点续传
    result = llm.generate(prompt, content[:5000])
    item["summary"]   = result["summary"]
    item["keywords"]  = result["keywords"]
    item["questions"] = result["questions"]
```

- 每 10 条保存一次进度（防中断）
- 云端 API 并发跑（几百份文档 ~30 分钟）

### 4.3 最终元数据结构

```json
{
  "id": "a1b2c3d4-...",
  "filename": "数据采集通讯配置.docx",
  "title": "数据采集通讯配置",
  "category": "通讯协议/MQTT",
  "summary": "介绍了组态软件中配置 MQTT 通讯的完整步骤...",
  "keywords": ["MQTT", "Broker", "Topic", "QoS", "通讯配置"],
  "questions": [
    "如何配置 MQTT 连接？",
    "Topic 格式怎么填写？",
    "QoS 级别有什么区别？"
  ]
}
```

### 4.4 富语义 chunk（切片头附元数据）

```python
enriched_content = f"""
Title: {metadata['title']}
Summary: {metadata['summary']}
Keywords: {', '.join(metadata['keywords'])}
Content Chunk: {chunk_text}
"""
```

**为什么这么做**：检索到的是文档第 N 个切片时，LLM 仍能通过切片头 metadata **理解整篇的背景**。与解析切块专项 §5 的 Anthropic Contextual Retrieval **同源不同形**——后者让 LLM 生成每 chunk 上下文，本文直接附 metadata，成本低得多。

### 4.5 我方落地

- **P0** `preprocessing/metadata_enrichment.py`：按 three-field schema 生成 + 断点续传
- **P0** `chunking/factory.py` 注入"富语义 chunk"模式（每 chunk 头附 metadata）
- **P1** `retriever.py` 增加 **questions 字段 HyDE 检索通道**（用户查询 × 文档预设问题语义匹配）
- **交叉引用**：解析切块专项 §6 Data-centric 合成 QA、IBM 冠军方案 §2.6 Prompt-as-Code

---

## 5. Parent-Child 连坐召回（**检索核心创新**）

### 5.1 背景：为什么需要连坐？

**问题**：每 chunk 头附了 summary → 用户问宏观问题时，Chunk 0（含简介 + summary）**相似度霸榜 Top-K**，真正包含参数表格的正文 chunk 被挤出 → LLM 回答"未找到相关信息"。

### 5.2 算法

```
Step 1: 向量检索 Top-K 候选切片
Step 2: Rerank 筛选 Top-N 切片
Step 3: 提取这些切片所属的文档名（去重）
Step 4: 按文档名二次查询：拉取每份文档的"所有切片"
Step 5: 同一文档切片按 chunk_index 排序，拼接为完整文档喂 LLM
```

### 5.3 代码

```python
def retrieve(self, query, top_k=3):
    initial_docs = self.vector_store.similarity_search(query, k=SEARCH_K)
    selected_docs = self._rerank(query, initial_docs, top_n=top_k)

    unique_filenames = set(doc.metadata.get('filename') for doc in selected_docs)

    expanded_results = collection.get(
        where={"filename": {"$in": list(unique_filenames)}},
        include=["documents", "metadatas"]
    )
    # 按 chunk_index 排序 → 重构完整上下文
```

### 5.4 与上下文扩展专项的对比（**两种扩展维度**）

| 维度 | 连坐召回（本文） | Neighbor Expand（第 11 份） |
|---|---|---|
| 粒度 | **文档级**全量 | Chunk 级**邻近** ±N |
| 触发 | 切片 → 整文档 | 分数阈值 → 邻近块 |
| 适用 | 切得较细 + 文档不太长 | 切得适中 + 文档较长 |
| 副作用 | 长文档会爆 context | 扩展范围可控 |
| 成本 | 低 | 中（需二次 rerank） |

**工程结论**：**两种策略互补**——
- 短文档（< 6k tokens）：用**连坐召回**（简单有效）
- 长文档（> 6k tokens）：用**Neighbor Expand + 二次 rerank**（精准可控）
- **可按文档长度自动切换**（profile 驱动）

### 5.5 我方落地

- **P0** `retrieval/sibling_expand.py`（连坐召回，文档级全量）
- **P0** `retrieval/orchestrator.py` 按文档长度路由：短文档 → sibling_expand / 长文档 → neighbor_expand
- **P1** 与 `hierarchy_expand.py`（365 行，结构树扩展）三者融合成统一 expansion 框架
- **交叉引用**：
  - 上下文扩展专项（第 11 份）neighbor_expand
  - 解析切块专项 §11 parent-child / small-to-big
  - IBM 冠军方案 §2.3 小块检索大块喂食（同源思路）

---

## 6. Rerank "漏斗整形"的量化决策

### 6.1 评测设计（可复用到评测集专项 Stage 1）

- **30 个真实售后问题**
- 每问标注：正确答案来自哪份文档
- 指标：**Recall@K**

### 6.2 量化对比（**Pareto 前沿**）

| 方案 | Top-K | Recall@5 | 平均延迟 | 成本 |
|---|---|---|---|---|
| Baseline（无 rerank） | 5 | 96.7% | ~0.1s | 0 |
| Rerank API（云端） | 50 | **100%** | ~7s（不稳定） | 按 token 计 |
| Rerank 本地 | 50 | **100%** | **~12.6s** | 0 |
| **Rerank 本地**（甜点） | **20** | **100%** | **~2.8s** | 0 |

### 6.3 "漏斗整形"的本质

**表面看**：Baseline 96.7% 已经不错，加 rerank 收益边际只有 3.3pp

**实际看**：
- Baseline 为了 96.7%，**漏斗口只开 5**（Top-5 向量），但 **Top-5 里可能有陪跑文档**（进入 LLM 会干扰）
- Rerank 的作用不是"找回漏的"，而是"**先把漏斗口放大到 20**，再精排筛掉陪跑"
- **让 LLM 看到更干净的 context**（只 Top-3）

**结论**：Rerank 优化的是 **Precision in top N**，不只是 Recall。

### 6.4 本地 Rerank 部署要点

```python
SEARCH_K = 20  # 粗排候选（由 30 问评测数据支撑）

def _rerank(self, query, initial_docs, top_n=3):
    pairs = [[query, doc.page_content] for doc in initial_docs]
    with torch.no_grad():
        inputs = self.rerank_tokenizer(pairs, padding=True,
                                        truncation=True, return_tensors='pt')
        inputs = inputs.to(self.device)  # Mac MPS 加速
        scores = self.rerank_model(inputs).logits.view(-1,).float()
    return [doc for doc, _ in sorted(zip(initial_docs, scores),
                                      key=lambda x: x[1], reverse=True)[:top_n]]
```

- 模型：`bge-reranker-v2-m3`（~300MB）
- 加速：Mac MPS / CUDA（MPS 实测 Mac Mini M2 ~140ms/batch）

### 6.5 我方落地

- **P0** `evaluation/recall_at_k_runner.py`（30 问 POC 评测集 runner）
- **P0** `reranker/local_bge_v2_m3.py`（MPS + CUDA 双后端）
- **P0** `config/rerank_profile.py`：`SEARCH_K=20` 甜点配置
- **交叉引用**：上下文扩展专项（长上下文 rerank，整体评估模式）互补；IBM 冠军方案 §2.5（0.7/0.3 加权融合）

---

## 7. 图片处理双阶段进化（Base64 → MinIO 解耦）

### 7.1 POC 阶段（Base64 暴力内嵌）

- 读本地图片 → Base64 → 嵌入 HTML
- 简单粗暴，POC 可用
- 缺点：体积大 / 加载慢 / 无缓存 / 无 CDN

### 7.2 MVP 阶段（MinIO + 映射解耦）

**设计原则**：**离线迁移 + 在线替换 + 映射文件解耦**

**Step 1：离线上传 + 生成映射**
```python
image_mapping = {}
for file_path in images_dir.glob("*"):
    client.fput_object(bucket_name, file_path.name, str(file_path))
    url = f"http://{minio_endpoint}/{bucket_name}/{file_path.name}"
    image_mapping[f"images/{file_path.name}"] = url

with open("image_url_mapping.json", "w") as f:
    json.dump(image_mapping, f)
```

**Step 2：在线替换**
```python
def process_markdown_images(self, text):
    with open("image_url_mapping.json") as f:
        image_mapping = json.load(f)

    pattern = r'!\[(.*?)\]\(images/(.*?)\)'
    def replace_with_url(match):
        key = f"images/{match.group(2)}"
        if key in image_mapping:
            url = image_mapping[key].replace(" ", "%20")  # URL 编码
            return f'![{match.group(1)}]({url})'
        return match.group(0)

    return re.sub(pattern, replace_with_url, text)
```

### 7.3 解耦的工程价值

- 数据层：只负责上传 + 生成映射
- 业务层：只负责查表 + 替换
- 换存储（MinIO → 阿里云 OSS → AWS S3）：只需**重跑离线迁移脚本**，业务代码零改动

### 7.4 我方落地

- **P0** `storage/object/image_mapping.py`（离线迁移 + 映射管理）
- **P0** `middleware/image_url_rewriter.py`（在线替换中间件）
- **P1** `storage/object/` 支持多后端（MinIO / OSS / S3 / Tencent COS）通过 factory 路由
- **交叉引用**：`app/storage/object/minio.py` 已有，本文增量是**映射管理 + 在线替换模式**

---

## 8. 数据闭环：Supabase 4 表 + RLS 踩坑

### 8.1 表结构

| 表 | 作用 |
|---|---|
| `profiles` | 用户（对接 Supabase Auth，含 admin / user 角色） |
| `chat_sessions` | 当前实现表名；承载一次交互 / 请求上下文 |
| `chat_messages` | 当前实现表名；**核心请求轨迹埋点**：rewritten_query / retrieved_docs / latency_stats |
| `feedback` | 反馈标注 + 具体原因 |

### 8.2 关键埋点字段

```sql
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES chat_sessions(id),
    role TEXT,
    content TEXT,
    metadata JSONB  -- rewritten_query / retrieved_docs / latency_stats
);

CREATE TABLE feedback (
    id UUID PRIMARY KEY,
    message_id UUID REFERENCES chat_messages(id),
    score INT,        -- 1=Like, -1=Dislike
    comment TEXT,     -- 点踩时填的具体原因
    created_at TIMESTAMPTZ
);
```

### 8.3 RLS 踩坑（**Supabase 用户必看**）

**错误做法**：
```sql
CREATE POLICY "Admin can see all" ON chat_messages
FOR SELECT USING (
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
    -- ⚠️ 查询 profiles 本身又触发 profiles 的 RLS → 无限递归
);
```

**正确做法**：用 `SECURITY DEFINER` 函数封装
```sql
CREATE OR REPLACE FUNCTION is_admin() RETURNS boolean
LANGUAGE sql SECURITY DEFINER AS $$
    SELECT EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
$$;

CREATE POLICY "Admin can see all" ON chat_messages
FOR SELECT USING (is_admin());
```

### 8.4 Streamlit 的 session_state 陷阱

每次交互 Streamlit 重跑脚本 → 若每次新建匿名 Client → RLS 校验失败。

**正确做法**：
```python
if 'supabase_client' not in st.session_state:
    st.session_state.supabase_client = create_client(
        supabase_url, token=user_jwt_token  # token 持久化
    )
```

### 8.5 我方落地（与安全合规专项的交互）

- **P0** `services/feedback_service.py`：对接 PostgreSQL（我方已有）+ 埋点规范
- **P0** 当前实现 `models/chat_message.py` / `app/models/chat.py` 承载请求轨迹 metadata JSONB：`rewritten_query` / `retrieved_docs` / `latency_stats`
- **P1** RLS 风格的 tenant 隔离函数封装（若走 Supabase 或自建 row-level security）
- **交叉引用**：
  - POC 归因专项 §2（5 字段极简埋点）
  - 安全合规专项 §8 审计日志

---

## 9. Query Rewrite：上下文指代消解 + 检索词透出

### 9.1 上下文相关 query 的指代问题

用户：
- 请求 1：Wireshark 怎么抓包？
- 请求 2：**它**能过滤 IP 吗？ ← 独立去检索找不到

### 9.2 轻量 LLM 改写

```python
rewritten = lightweight_llm.rewrite(
    history=[...],
    current_query="它能过滤 IP 吗"
)
# 输出："Wireshark 能否按 IP 地址过滤抓包数据"
```

- 耗时 < 1s
- 成本可忽略

### 9.3 调用侧信任展示（**关键交互细节**）

调用侧可显示：**🔄 优化检索词：Wireshark IP 过滤**

让用户**感知系统"听懂"了**，信任感显著提升。

### 9.4 我方落地

- **P0** `workflows/query_rewrite.py`（若已有，升级以支持调用侧透出）
- **P0** SSE 流式中**先透出 rewritten_query**，再流式答案
- **P1** 记录 `rewritten_query` 到 `chat_messages.metadata`（当前实现表名），供复盘 rewrite 质量
- **交叉引用**：综合报告 §5 查询理解；Agentic 专项 §5 A-RAG hierarchical tools

---

## 10. 调用侧交互：Streamlit → Next.js 重构

### 10.1 Streamlit 的 4 个天花板

| 问题 | 根因 |
|---|---|
| 交互体验差 | 渲染机制是**全量刷新** |
| 图片显示困难 | Base64 内嵌 |
| 交互状态复杂 | session_state 代码冗长 |
| 扩展性差 | 加 Dashboard 绕弯多 |

### 10.2 MVP 调用侧核心功能

| 功能 | 实现 |
|---|---|
| **SSE 逐段展示** | 后端完整响应 → 前端 setInterval 逐字渲染 / 长短文本不同速度 |
| **引用证据卡片** | hover 高亮 / 点击跳转 Clean DOCX |
| **反馈采样入口** | 悬停浮现 / 点踩弹输入框 |
| **SWR 缓存** | Stale-While-Revalidate（近期请求记录秒开） |
| **运营 Dashboard** | 管理员可视化 |

### 10.3 SSE 逐段展示代码范式

```javascript
const interval = setInterval(() => {
    setMessages(prev => prev.map(m =>
        m.id === aiMsgId
            ? { ...m, content: fullResponse.slice(0, i + 1) }
            : m
    ));
    i += (fullResponse.length > 500 ? 5 : 1);  // 长文本加速
    if (i >= fullResponse.length) clearInterval(interval);
}, speed);
```

### 10.4 SWR 请求记录秒开

```javascript
const { data: messages = [] } = useSWR(
    selectedSessionId ? `/history/${selectedSessionId}` : null,
    fetcher,
    { revalidateOnFocus: false }
);
```

### 10.5 我方落地

- 主要是前端工程，我方无直接对应（`web/` 前端已有 Next.js 架构）
- **P1** 参考 Dashboard 模式补运营看板（若未有）
- **交叉引用**：POC 归因专项 §6 双写陷阱 / 单一数据源

---

## 11. 企业级交付：容器化 + 维护模式

### 11.1 Docker Compose 一键启动

| 组件 | 作用 |
|---|---|
| 前端 | Next.js |
| 后端 | FastAPI |
| 向量 DB | Milvus / Chroma / Qdrant |
| 关系 DB | PostgreSQL（Supabase / 自建） |
| 对象存储 | MinIO |
| Rerank 模型 | Volume 挂载（不打包镜像） |

### 11.2 两种维护模式（企业合规二选一）

| 模式 | 方式 | 更新速度 | 适用 |
|---|---|---|---|
| **纯内网隔离** | 现场导诊断包 + 工程师上门带回分析 | 周期长 | 军工 / 金融核心 |
| **远程 OTA** | 安全连接远程更新 Prompt / 参数 / 阈值 | 分钟级 | 一般企业 |

### 11.3 配置即数据原则

- RAG 参数（Prompt / 检索 / 阈值）**存 DB 配置表**
- 后台可改，无需发版
- 模型文件**Volume 挂载**，替换即生效

### 11.4 我方落地

- 我方已有容器化基础；**P1** `services/config_hot_reload.py`（配置热加载）
- **P1** 诊断包导出工具：`scripts/export_diagnostics.py`（脱敏后导出 metrics / feedback 分布）
- **交叉引用**：安全合规专项 §9 PII Lifecycle

---

## 12. 产品化演进 3 阶段（长期路线图）

### 12.1 阶段一：可信度建设

| 方向 | 说明 |
|---|---|
| **知识源权重体系** | 官方手册 > 论坛帖子 / 新版 > 旧版 / 已废弃版降权 |
| **可解释召回** | 引用来源 + 相关度分数 + 匹配片段高亮 |
| **置信度评分** | 低置信时"**建议人工核实**"提示 |

### 12.2 阶段二：运营闭环

| 指标升级 | 从 | 到 |
|---|---|---|
| 调用量 | 次数 | **问题解决率**（点赞数 / 总提问） |
| 反馈率 | % | **转人工率**（无法回答 / 总提问） |
| 预警 | 人工投诉 | **Bad Case 自动告警**（单日点踩超阈值 / 同一问题连续无结果） |

### 12.3 阶段三：生态集成（以可嵌入 RAG 能力为主）

> RAG 能力不应该绑定在单一聊天入口，而应该通过标准接口嵌入已有工作流。

| 集成 | 优先级 |
|---|---|
| **标准 API / SDK** | 最高（下游系统只接 RAG 也成立） |
| **MCP Server** / LangChain Tool | 高 |
| 浏览器插件 / 侧边栏 | 次 |
| ~~企微 / 钉钉 / 飞书机器人~~ | 当前分支不做 |

### 12.4 大型企业额外需求

- 审计日志
- 细粒度权限管理（部门分库）
- 多租户隔离

### 12.5 我方落地

- **P2** MCP Server 暴露能力（对齐 Agentic 专项 §2 A-RAG hierarchical tools）
- ~~**P2** 企微机器人适配器（Webhook + 回调）~~（当前分支不做）
- **交叉引用**：安全合规专项 §20 / KG 专项 §6.7 网络分析 API

---

## 13. 为什么不一上来就微调？（**关键工程次序**）

### 13.1 正确次序

```
Step 1: 跑通反馈收集基础设施   ← 最重要，业务专家日常使用中完成标注
Step 2: 优化检索策略（元数据 / 分块 / rerank）
Step 3: 优化 Prompt（按反馈 bad case 调）
Step 4: ← 才考虑微调（数据量 + 效果瓶颈满足才做）
```

### 13.2 为什么不一开始微调？

- **高质量数据** = 业务专家时间 × 长期积累
- 一开始人工整理几百条 QA 对 → **标注质量低 + 覆盖不全 + 不持续**
- 日常使用中的**点赞点踩嵌入工作流本身就是标注**
- 反馈数据积累到一定量级后再微调，**ROI 最高**

### 13.3 我方落地

- **P0** 反馈收集基础设施（本文 §8）是**一切的前置**
- **P1** 反馈数据 → Prompt 迭代（每月分析 top bad case）
- **P2** 达到 N 条 feedback 后触发微调评估（自动化 A/B）

---

## 14. 企业 AI 市场观察（可用于客户沟通）

### 14.1 客户心态周期

| 阶段 | 时间 | 特征 |
|---|---|---|
| **恐慌** | 2025 初 DeepSeek R1 开源 | "AI 要颠覆一切" |
| **祛魅** | 2025 中 | 内部浅尝辄止，发现没那么神奇 |
| **观望** | 2025 下 - 2026 | "到底值不值得投？" |

### 14.2 理想客户画像

- **2023H2 / 2024H1 开始试错**的企业（已交过学费）
- 愿意买付费 POC（不白嫖）
- **自上而下立项**（老板直接拍板，非副手代理）

### 14.3 劝退信号

- 领导"**大模型网页端直接丢文档就行**"
- **不是技术判断的问题，是优先级问题**
- 高级别领导不重视 → 项目难推动
- **自证不如研究清楚**（给咨询者的建议）

### 14.4 核心洞察

> **现阶段企业 AI 应用的核心不在于技术多先进，而在于能不能找到一个足够具体的场景、解决一个足够真实的问题。**
>
> 技术成熟度从来不是障碍（开源模型对大多数企业够用）。
>
> **真正的障碍是数据质量、业务理解、能否嵌入日常工作流。**

---

## 15. 关键踩坑清单（可独立复用）

| 坑 | 症状 | 正确做法 |
|---|---|---|
| Ollama 本地 Embedding 崩溃 | 文档 > 2000-5000 字时 Ollama 进程频繁挂 | 切云端 API（OpenRouter / DashScope） |
| Embedding 切换不重入库 | 向量空间不兼容导致召回爆 | 切换必重入库 |
| 切片头附 summary → Chunk 0 霸榜 | 宏观问题命中摘要切片，正文被挤出 | **Parent-Child 连坐召回** |
| Rerank Top-50 太慢（12s） | 线性计算成本 | 缩到 Top-20（3s），Recall 保持 100% |
| Base64 图片体验差 | 响应体积大 / 无缓存 | MinIO + 映射解耦 |
| Supabase RLS 无限递归 | profiles 查询又触发 RLS | SECURITY DEFINER 函数封装 |
| Streamlit session_state 新建匿名 Client | RLS 校验失败 | session_state 持久化 token |
| 一开始就想微调 | 数据量不够、质量低 | 先建反馈基础设施 |
| 把 RAG 绑定在自有聊天壳 | 下游系统难复用 | **标准 API / SDK / MCP 可嵌入** |

---

## 16. 优先级矩阵（本文增量 × 与其他 plan 联动）

### 🥇 P0（2–4 周）

| # | 建议 | 依据 |
|---|---|---|
| 1 | `retrieval/sibling_expand.py`（连坐召回文档级全量） | §5 |
| 2 | `preprocessing/metadata_enrichment.py`（summary/keywords/questions 三字段 + 富语义 chunk） | §4 |
| 3 | `parsing/output/{markdown_writer,docx_writer}.py` 双写器 | §3 |
| 4 | `storage/object/image_mapping.py` + `middleware/image_url_rewriter.py` | §7 |
| 5 | `evaluation/recall_at_k_runner.py` + 30 问 POC 评测集 | §6 |
| 6 | Rerank 本地 `SEARCH_K=20` 甜点 + MPS/CUDA 双后端 | §6 |
| 7 | `models/chat_message.py` metadata JSONB 埋点规范（rewritten_query / retrieved_docs / latency_stats） | §8 |
| 8 | 反馈收集基础设施（点赞 / 点踩 / 具体原因） | §8, §13 |

### 🥈 P1（1–2 月）

| # | 建议 | 理由 |
|---|---|---|
| 9 | 按文档长度路由 `sibling_expand` vs `neighbor_expand`（两扩展策略互补） | §5.4 |
| 10 | Questions 字段 HyDE 检索通道 | §4 |
| 11 | `workflows/query_rewrite.py` + SSE 前端透出"🔄 优化检索词" | §9 |
| 12 | `services/config_hot_reload.py`（配置热加载） | §11 |
| 13 | 反馈 → bad case 月度分析 → Prompt 迭代 | §13 |
| 14 | 知识源权重体系（官方 > 论坛 / 新版 > 旧版） | §12.1 |

### 🥉 P2（2–6 月）

| # | 建议 |
|---|---|
| 15 | 微调评估（feedback 达到 N 条触发） |
| 16 | ~~企微 / 钉钉 / 飞书机器人适配器~~（当前分支不做） |
| 17 | MCP Server 能力暴露 |
| 18 | 诊断包导出工具（脱敏） |
| 19 | Bad Case 自动告警（单日点踩超阈值） |

---

## 17. 与前 11 份 plan 的交叉引用

| 本文章节 | 关联 plan |
|---|---|
| §1 阶段边界 | POC 归因专项 §1（POC 5 条减法原则） |
| §2 数据清洗多轮抽样 | Pre-POC Scanner（入库前预检） |
| §3 双重输出 | Pre-POC Scanner §8 一键打开 |
| §4 三字段元数据 | 解析切块专项 §6 / IBM 冠军方案 §2.6 Prompt-as-Code |
| §5 连坐召回 | **上下文扩展专项（第 11 份）**neighbor_expand 互补；解析切块专项 §11 parent-child |
| §6 Rerank 漏斗整形 | IBM 冠军方案 §2.5 加权融合；上下文扩展专项整体评估 |
| §7 图片 MinIO | 安全合规专项（对象存储安全）；解析切块专项 §4 图表 enrichment |
| §8 Supabase + RLS | 安全合规专项 §6 Presidio / §8 RTBF / §9 Lineage；POC 归因专项 §2 5 字段埋点 |
| §9 Query Rewrite | Agentic 专项 §5 A-RAG / 综合报告 §5 查询理解 |
| §12 产品化三阶段 | 综合报告 §16 / KG 专项 §6.7 网络分析 API |
| §13 不一开始微调 | 评测集专项 §4 Stage 1–4 先松后紧 |
| §14 市场观察 | POC 归因专项 §11 垂直 SaaS |

---

## 18. 参考资料

### 技术栈
- FastAPI / Next.js / TailwindCSS
- Supabase (PostgreSQL + Auth + RLS)
- MinIO / ChromaDB / LangChain
- OpenRouter Qwen3-Embedding-8b / bge-reranker-v2-m3
- SWR (Stale-While-Revalidate)

### 本项目相关 plan（全量交叉引用）
- 第 1 份 `rag-capability-gap-2026-q2.md`
- 第 2 份 `rag-deep-research-2026-q2.md`
- 第 3 份 `rag-eval-dataset-deep-dive-2026-q2.md`
- 第 4 份 `rag-kg-deep-research-2026-q2.md`
- 第 5 份 `rag-agentic-reasoning-deep-dive-2026-q2.md`
- 第 6 份 `rag-parsing-chunking-deep-dive-2026-q2.md`
- 第 7 份 `rag-safety-compliance-deep-dive-2026-q2.md`
- 第 8 份 `rag-poc-attribution-framework-2026-q2.md`
- 第 9 份 `rag-pre-poc-scanner-2026-q2.md`
- 第 10 份 `rag-ibm-champion-blueprint-2026-q2.md`
- 第 11 份 `rag-context-expansion-rerank-2026-q2.md`

---

## 19. 结论

1. **POC → MVP 升级的核心不是重写，是补齐闭环**：RAG 引擎直接复用，重点补体验层（Next.js / SSE / SWR）+ 闭环层（Supabase 4 表 / 反馈收集）
2. **连坐召回 vs 邻近扩展是两种扩展维度**，应按文档长度自动路由：
   - 短文档 → 连坐召回（文档级全量）
   - 长文档 → 邻近扩展（chunk 级 ±N）
3. **LLM 元数据三字段 + 富语义 chunk** 是低成本高收益的"**入库阶段语义放大器**"（比 Anthropic Contextual Retrieval 便宜）
4. **Rerank 漏斗整形**（96.7% baseline → 100% + Top-N 精排）的工程决策依据是"**让 LLM 看到更干净的 context**"，而非"找回漏的"
5. **不一开始就微调** 是 RAG 项目最关键的工程次序——先建反馈基础设施，业务专家日常使用即标注
6. **知识库能力应以标准接口嵌入工作流，而不是绑定聊天入口**——API / SDK / MCP Server 才是当前分支的落地重点
7. **数据质量 > 业务理解 > 嵌入工作流** 决定企业 AI 成败，技术从来不是障碍

**落地建议**：
- **本周**：Parent-Child 连坐召回 + 三字段元数据增强 + 30 问评测集（3 项 P0 可并行）
- **2 周**：Rerank Top-20 甜点 + 图片 MinIO 映射 + 反馈埋点
- **1 月**：SSE / SWR / 运营 Dashboard + Query Rewrite 透出
- **2–3 月**：产品化阶段一（可信度）+ 阶段二（运营闭环）

---

> **RAG 专项体系至此共 12 份 plan，合计 ~7200 行**：
> - 第 1–4 份：综合对标 + 深度调研 + 评测集 + KG
> - 第 5–7 份：Agentic / 解析切块 / 安全合规
> - 第 8 份：POC 归因框架
> - 第 9 份：Pre-POC Scanner
> - 第 10 份：IBM 冠军方案工程蓝图
> - 第 11 份：上下文扩展与二次重排
> - 第 12 份：**POC → MVP 完整交付蓝图（本文）**
>
> **全链路覆盖**：Pre-POC → POC 一周 → MVP 两周 → 生产演进；理论对标 + benchmark + 方法论 + 工程范式 + 运营手册全覆盖。

---

## 20. 可独立拆的子 plan

- `plans/sibling-expand-retrieval.md`（文档级连坐）
- `plans/metadata-enrichment-three-fields.md`（summary/keywords/questions）
- `plans/dual-output-markdown-docx.md`（双写器）
- `plans/image-mapping-minio.md`（MinIO 映射管理）
- `plans/recall-at-k-poc-benchmark.md`（30 问 POC 评测）
- `plans/rerank-local-bge-v2-m3.md`（本地 rerank 甜点）
- `plans/supabase-feedback-schema.md`（4 表 + RLS）
- `plans/query-rewrite-sse-display.md`（Query Rewrite 信任展示）
- `plans/enterprise-ota-maintenance.md`（OTA 维护模式）
- `plans/product-stage1-trust-building.md`（可信度建设）
- ~~`plans/product-stage3-enterprise-im.md`~~（当前分支不做企微 / 钉钉 / 飞书入口）

---

## 15. 2026-05-01 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地:
- 从 POC 到 MVP 的主链路已覆盖:precheck scanner、dataset profile、parsing、ingestion monitor、quarantine、feedback、evaluation、POC attribution、RAG trace、KG diagnostics.
- 检索可信度能力已吸收到 sibling expand、metadata/tagging、rerank profiles、query/context diagnostics、feedback 与 trace 可视化.
- 企业化基础已具备 cost/quota、semantic cache、RTBF、lineage、SCIM/SAML、audit/redteam 等可上线能力.

暂缓:
- 暂缓 Supabase 专用反馈 schema、Streamlit 迁移、DOCX 双写器、MinIO 图片映射专项和企业 IM 入口.
- 暂缓 OTA 维护模式产品化,除非明确进入离线私有化交付场景.

Directive: 本文后续不再作为交付清单;MVP 只围绕当前主产品页面和真实部署缺口继续收敛.
