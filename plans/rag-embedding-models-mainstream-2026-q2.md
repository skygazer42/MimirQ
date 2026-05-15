# Embedding 模型扩容与对比主流方案调研 — 2026-Q2

> 用户选 #1 主题(MEMORY 记录 P0 Quick Win)。本份调研覆盖 ① 业界主流 embedding 模型对比(MTEB/C-MTEB 2026 leaderboard)② 中文 embedding 专项 ③ Matryoshka 多维度路线 ④ 量化(scalar/binary)降本 ⑤ 多模态 embedding ⑥ 微调路线 ⑦ MimirQ 现状差距 + 落地路径。

---

## 1. Context

### 1.1 起因

MEMORY 多份 plan 标"embedding 扩容是 P0 Quick Win",但截至 2026-05 实际状态:**8 个 provider 中只有 4 个真实现**(openai/ollama/dashscope/local),其余 4 个(voyage/cohere/jina/bedrock)各 **10 行壳子继承** `OpenAICompatibleEmbedding`,等同于"假装支持"。

### 1.2 调研问题

1. 2026 业界 MTEB/C-MTEB 排名前 10 是哪些?
2. 中文场景该选谁(Qwen3-Embedding-8B / Conan-v2 / BGE-M3 / Stella)?
3. Matryoshka 真能省多少存储 + 牺牲多少召回?
4. 量化(int8/binary)在 Milvus 上怎么用?
5. 多模态(ColPali/Voyage-multimodal-3/Cohere Embed v4)是否值得接?
6. 自家语料微调 BGE-M3 收益估算?

---

## 2. MimirQ 现状盘点

### 2.1 embedding 模块文件清单(实测行数)

| 文件 | 行数 | 状态 |
|---|---|---|
| `app/rag/embedding/adapter.py` | **337** | ✅ 适配器层 |
| `app/rag/embedding/base.py` | 213 | ✅ ABC + 三态接口 |
| `app/rag/embedding/factory.py` | 218 | ✅ 工厂 + 路由 |
| `app/rag/embedding/config.py` | 194 | ✅ 配置(EMBEDDING_LANGUAGE_ROUTING / SHADOW migration 等) |
| `app/rag/embedding/bge_m3_triplet.py` | 100 | ✅ dense+sparse+colbert 三态 |
| `app/rag/embedding/clip_embedder.py` | 168 | ✅ 图像 CLIP |
| `app/rag/embedding/utils.py` | 147 | ✅ |
| `app/rag/embedding/matryoshka.py` | **44** | △ **薄,需扩** |
| `app/rag/embedding/code_embedder.py` | **19** | ❌ 空壳 |

### 2.2 Provider 现状(关键!)

| Provider | 行数 | 状态 |
|---|---|---|
| `openai.py` | 308 | ✅ **OpenAICompatibleEmbedding 真实现**(其他三家其实复用此) |
| `ollama.py` | 313 | ✅ 真实现(本地模型) |
| `dashscope.py` | 111 | ✅ 阿里云真实现 |
| `local.py` | 93 | ✅ sentence-transformers 本地 |
| `voyage.py` | **10** | ❌ **空壳** `class VoyageEmbedding(OpenAICompatibleEmbedding): pass` |
| `cohere.py` | **10** | ❌ 空壳 |
| `jina.py` | **10** | ❌ 空壳 |
| `bedrock.py` | **10** | ❌ 空壳 |

### 2.3 重要观察

- 4 个"空壳" provider 实际能跑(继承了 OpenAI 兼容客户端),但**没用上原厂特性**(Voyage 32k context / Cohere v4 多模态 / Jina v3 multi-task instructions / Bedrock SigV4 鉴权)
- MEMORY 说"4 个 provider"是漏看了 4 个空壳,实际**真实现 4 个**判断是对的
- 默认 `text-embedding-3-small`,**不是 MEMORY 记录的 BGE-M3**(MEMORY 信息已过期)
- `EMBEDDING_LANGUAGE_ROUTING_ENABLED` 字段存在 → 已有 zh/en/mixed 三路由架子(配置层),但未默认开
- `EMBEDDING_SHADOW_*` 蓝绿迁移已设计(Gap5),代码已就位
- 默认 `text-embedding-3-small` MTEB 仅 62.3,**业界 SOTA(Qwen3-Embedding-8B / Gemini / Voyage-3-large)已 67-71**——客户拿到的召回是"业界第二梯队水平"

---

## 3. 业界主流 embedding 模型横向矩阵(2026-04 MTEB leaderboard)

### 3.1 商业 API

| 模型 | MTEB | 维度 | Context | Matryoshka | 价格 USD/M tokens | 多模态 | 中文 |
|---|---|---|---|---|---|---|---|
| **Gemini Embedding 001** | 68.3 / Retrieval 67.7 ★★ | 3072 | 8k | ✅ 256-3072 | $0.15 | ❌ | ✅ |
| **Voyage 3-large** | 67.1 ★ | 1024 | **32k** ★最长 | ✅ 256-1024 | $0.18 | △(另有 voyage-multimodal-3) | ✅ |
| **Voyage 3-lite** | 65.5 | 512 | 32k | ✅ | $0.06 | ❌ | ✅ |
| **Cohere Embed v4** | 65.2(纯文本) | 256-1536 | 128k | ✅ 256-1536 | $0.12 | ★ **唯一原生** text+image+table | ✅ 100+ 语种 |
| **OpenAI text-embedding-3-large** | 64.6 | 3072 | 8k | ✅ 256-3072 | $0.13 | ❌ | ✅ |
| **Jina v3** | 65.5 | 1024 | 8k | ✅ | $0.02 ★性价比 | ❌ | ✅ |
| **OpenAI text-embedding-3-small**(MimirQ 默认) | 62.3 | 1536 | 8k | ✅ | $0.02 | ❌ | ✅ |

### 3.2 开源模型(可本地部署)

| 模型 | MTEB | 参数 | 维度 | License | 中文 | 备注 |
|---|---|---|---|---|---|---|
| **Qwen3-Embedding-8B** | 70.58 ★★★ MTEB Multilingual #1(2025-06) | 8B | 32-4096 灵活 | Apache 2.0 | ✅ 强 | 100+ 语种,80.68 MTEB Code |
| Qwen3-Embedding-4B | 69+ | 4B | 32-2560 | Apache 2.0 | ✅ | 中等 |
| Qwen3-Embedding-0.6B | 65+ | 0.6B | 32-1024 | Apache 2.0 | ✅ | 轻量 |
| **NV-Embed-v2** | 72.31 总分 ★(retrieval 62.65 偏弱) | 7.85B | 4096 | Non-commercial | △ | 学术第一 |
| **Conan-Embedding-v2**(腾讯 BAC) | C-MTEB SOTA | 1.4B | 1792 | MIT | ★ 中文 SOTA | 中英跨语种 |
| **Jasper(Stella distill)** | 71.54 ★ | 2B | 2048 | MIT | ✅ | 蒸馏自 7B teachers |
| **Stella en 1.5B v5** | 71.19 | 1.5B | 1024 | MIT | △ | 无需 instruction |
| **BGE-en-ICL** | 71.24 | 7.1B | 4096 | Apache 2.0 | △ | in-context learning |
| **BGE-M3**(当前 MimirQ bge_m3_triplet) | 64-68 | 568M ★ 轻 | 1024 | MIT | ✅ | dense+sparse+colbert 三态 |
| **Nomic Embed v2** | 63 | 137M | 768 | Apache 2.0 | ✅ | 最轻 |
| **Snowflake Arctic-embed-l-v2** | 63 | 568M | 1024 | Apache 2.0 | ✅ | |

### 3.3 关键洞察

- **开源已反超商业 API**(Qwen3-8B 70.58 > Gemini 68.3 > Voyage 67.1)— 这是 2025 H2 的反转
- **MTEB 平均分骗人**:看 retrieval 子指标更准(Gemini retrieval 67.7 > NV-Embed-v2 62.65)
- **Matryoshka 已成标配**(OpenAI / Gemini / Voyage / Cohere / Nomic / GTE / Qwen3)— 不支持 MRL 的模型在 2026 没出路
- **MimirQ 默认 `text-embedding-3-small` 62.3 比 SOTA 低 8 分**,等于客户每次检索都比业界差一档

---

## 4. C-MTEB 中文专项

### 4.1 2025-2026 中文 SOTA 排名

| 模型 | C-MTEB | 备注 |
|---|---|---|
| **Conan-Embedding-v2**(腾讯) | **★ SOTA** | 中英跨语种,在线 inference 可压低成本 |
| **Qwen3-Embedding-8B** | 接近 Conan | MTEB Multilingual #1 自然中文也强 |
| Stella zh v2 | 强,但 v5 仅英 | 中文版本停更 |
| BGE-M3 | 强,baseline | 568M 适合本地部署 |
| GTE-Qwen2-7B-instruct | 强 | 阿里上一代 |
| Conan-Embedding-v1 | 上代 SOTA | v2 已发布 |
| DMeta-embedding-zh | 中等 | 商业封闭 |

### 4.2 中文 embedding 6 个特殊场景

| 场景 | 推荐 |
|---|---|
| 通用中文客户(99%) | **BGE-M3** 自部署免费 + Qwen3-0.6B 兜底 |
| 强中文场景 + 自部 SOTA | **Conan-Embedding-v2** |
| 强中文 + 跨语种 + 预算高 | **Qwen3-Embedding-8B** |
| 法律/金融垂类 | BGE-M3 + 自家微调(详见 §8) |
| 代码 / 技术文档 | Qwen3-Embedding(80.68 MTEB Code)|
| 多模态(中文 + 图表) | **Cohere Embed v4**(100+ 语种,含中文) |

---

## 5. Matryoshka 维度路线(MimirQ matryoshka.py 仅 44 行需扩容)

### 5.1 MRL 核心机制

> Matryoshka 嵌入是套娃式结构 —— 256 维 = 768 维的前 256 个值。截断+归一化即可,无需 PCA。

### 5.2 实测压缩 / 召回 trade-off

| 模型 | 原维度 | 截断到 | 召回降幅 | 存储省 |
|---|---|---|---|---|
| OpenAI text-embedding-3-large | 3072 | 256 | < 5% | **92%** |
| Gemini Embedding 2 | 3072 | 768 | < 10% | 75% |
| Cohere Embed v4 | 1536 | 256 | 2.8% | **83%** |
| Voyage 3-large | 1024 | 256 | < 5% | 75% |
| Qwen3-Embedding-8B | 4096 | 1024 | < 3% | 75% |

### 5.3 生产模式:Shortlist + Rescore

```
query → 256d embedding(快)→ ANN 取 top-200 候选(快、便宜)
   ↓
   候选 → full 1024d embedding → cosine rescore → top-K(准)
```

理论 FLOPs 速度 128×,实测 wall-clock 14×。

### 5.4 MimirQ matryoshka.py 升级清单

- 现状 44 行可能仅 truncate 工具,未集成到检索期 rescore 路径
- **P0**:扩到 ~200 行,加 shortlist + rescore 适配器,接入 `retriever.py`(HybridRetriever 5940 行)
- 维度采样(常用 4 档:256 / 512 / 768 / 1024 / full)写进配置

---

## 6. 量化路线(Milvus / Qdrant 2025-2026)

### 6.1 三档量化对比

| 方法 | 压缩 | 速度 | 召回降幅 | 适用 |
|---|---|---|---|---|
| **Scalar Int8** | 4× | 2× | < 1% ★★ | 默认开,无脑省 |
| Binary 2-bit(Qdrant 2025-15+) | 16× | 20× | 中 | 大语料,中维度 |
| **Binary 1-bit** | 32× | **40×** | ~5% | ≥ 1024 维模型(否则崩) |
| 1.5-bit / asymmetric(Qdrant 1.15.0+) | 8-16× | 中 | 折中 | 接近零值场景 |

### 6.2 真实成本对比(Hugging Face 41M embeddings)

- Float32 原生:**200GB 内存 + 200GB 磁盘**
- Scalar int8 + float32 rescore:**5.2GB 内存 + 52GB 磁盘**(**省 96%**)
- 50M vectors 全量 int8:云成本 \$1,200/月 → **\$450/月**(Qdrant 测试)

### 6.3 MimirQ Milvus 量化现状(需核验)

- `app/rag/embedding/config.py:1020` 已有 `COLBERT_RETRIEVAL_EMBED_DIM=64` / `COLBERT_RERANK_EMBED_DIM=64` 配置
- 但 dense vector 默认未量化(需查 `app/rag/retriever.py` Milvus index 类型)
- **P0**:Milvus index 改 `HNSW + SQ8`(scalar int8),配 `Search.params={"oversampling":2}` 取 2× candidates 再 float32 rescore

---

## 7. 多模态 embedding 路线

### 7.1 三大方案对比

| 模型 | text+image | text+table | text+chart | 中文 | 价格/月 |
|---|---|---|---|---|---|
| **Voyage-multimodal-3** | ✅ table/figure +6-45% over baselines | ✅ ★ | ✅ | ✅ | API only |
| **Cohere Embed v4** | ✅ 同一空间 | ✅ | ✅ | ✅ 100+ 语种 | ~$0.12/M tokens(可量化) |
| **ColPali / ColQwen2**(ICLR 2025) | ✅ late interaction | ✅ | ✅ | △ | 开源,**multi-vector 存储贵 10×** |
| MimirQ 现状 `clip_embedder.py` 168 行 | ✅ CLIP-ViT-B/32 弱(MTEB 50-) | ❌ | ❌ | △ | 自部 |

### 7.2 ColPali / late interaction 取舍

- 优点:文档级 retrieval **+6-45%** over CLIP/Titan/SigLIP
- 缺点:每文档产 N 个 token-level vectors,**存储/索引贵 10-30 倍**
- 适合:法律 / 财报 / 学术 PDF(图表密集)
- 不适合:通用文档(纯文本就足够)

### 7.3 MimirQ 多模态升级路径

- **P0**:把 `clip_embedder.py` 升 OpenCLIP-ViT-L/14 或接 Cohere Embed v4(text + image 同一空间)
- **P1**:实验 ColPali / ColQwen2,只用在"图表密集"标签的文档(对接 §7 业界识别)
- **P2**:Cohere Embed v4 商业接入(配合 deepdoc-api 销售)

---

## 8. 微调路线(2025 学术 + 工程实践)

### 8.1 三大主流方向

| 方法 | 数据需求 | 工程难度 | 实测收益 |
|---|---|---|---|
| **CustomIR**(Oct 2025,无监督) | 客户语料 + 合成 query | 中 | BGE-M3 +1.1 R@10 / Qwen3-Embed-Sm +2.1 R@10 |
| **REFINE**(Model fusion 防遗忘) | 合成 + LLM 标注 + 负样本 | 中 | 域内涨 + 通用不掉 |
| **SciNCL graph contrastive**(EMNLP 2025) | KG triples + 文档对 | 高 | mE5-large +9.8-14.3%(进程工业) |
| 轻量 projection adaptation(Feb 2025) | 少量 anchor pair | 低 | 中等收益,不改 backbone |

### 8.2 MimirQ 微调资产盘点

| 资产 | 现状 | 价值 |
|---|---|---|
| `app/rag/feedback_loop/` | ✅ 完整反馈收集 | 自带正负样本 |
| `app/rag/evaluation/hard_negative_mining.py` | ✅ 硬负样本挖掘 | 微调金矿 |
| `app/rag/kg/` 全栈 | ✅ KG triples | **可走 SciNCL graph contrastive 路线** |
| `bge_m3_triplet.py` | ✅ 三态接口 | 微调后无缝替换 |

### 8.3 推荐路线

- **P0 不动**:先把现状的"业界 SOTA 切换"做完(§3 商业 + §4 中文)
- **P1**:CustomIR 路线对工控 PoC 客户落地一次(BGE-M3 + 合成 query)
- **P2**:SciNCL graph contrastive 用 KG triples 微调(MimirQ 唯一独家)

---

## 9. 推荐 P0 / P1 / P2(2-3 周到 1-2 季度)

### 9.1 P0(2-3 周,Quick Win + 默认升级)

| 任务 | 落点 | 估算 |
|---|---|---|
| **填实 4 个 provider 空壳**(Voyage 走原生 SDK 拿 32k context;Cohere 走原生 SDK 拿 v4 多模态;Jina 走原生拿 task instructions;Bedrock 走 boto3 SigV4) | `providers/{voyage,cohere,jina,bedrock}.py` 4 × ~150 行 | 3 day |
| **默认模型升级**:`text-embedding-3-small` → **BGE-M3 自部署**(MTEB 65+,本地无 API 成本,中英都强) | `config.py:349` 改默认 + `local.py` 加载 BGE-M3 | 0.5 day |
| **加 Qwen3-Embedding-0.6B / 4B / 8B 三档 provider**(走 ollama 或 transformers,Apache 2.0) | `providers/qwen3.py`(new)+ `factory.py` | 1.5 day |
| **加 Conan-Embedding-v2 provider**(中文场景下推荐配置) | `providers/conan.py`(new) | 1 day |
| **Matryoshka shortlist + rescore 集成**:matryoshka.py 44 → ~200 行,接入 `retriever.py` 候选阶段 | `matryoshka.py` + `retriever.py` | 2 day |
| **Milvus index 改 SQ8**(scalar int8 + oversampling 2× + float32 rescore) | `retriever.py` Milvus collection schema | 1 day |
| **Embedding benchmark runner**:50 客户文档 + 200 query 跑 9 模型 × 4 维度档,出 HTML 报告(对齐 PoC 单文件原则) | `evaluation/embedding_bench/`(new) | 2 day |
| **EMBEDDING_LANGUAGE_ROUTING 默认开**:zh→Conan-v2 / en→Voyage-3-lite / mixed→BGE-M3 | `config.py:352`+`factory.py` | 0.5 day |

### 9.2 P1(1 个月,多模态 + 蓝绿迁移落地 + 微调准备)

1. **Cohere Embed v4 多模态接入**:text+image+table 同一空间;前端"图表密集"标签自动路由
2. **`clip_embedder.py` 升 OpenCLIP-ViT-L/14**:CLIP-B/32 → L/14 召回 +15-20%
3. **Shadow embedding 蓝绿迁移真跑一次**:`EMBEDDING_SHADOW_*` 配置已就位,跑 1k 文档双写 + 验证脚本(对照 MEMORY 中 Gap5)
4. **CustomIR 微调**:从工控客户 PoC 反馈数据(`feedback_loop`)+ 硬负样本(`hard_negative_mining`)走一次 BGE-M3 contrastive fine-tune,目标 R@10 +1-3pt
5. **Embedding eval 上 CI**:对照前份 `rag-prompts` plan 的 Promptfoo CI 模式,每次改 embedding 配置 PR 自动跑 50 query → 阻断回退

### 9.3 P2(独立调研型,1-2 季度)

| 项 | 内容 |
|---|---|
| ColPali / ColQwen2 late interaction | 图表密集文档专项,multi-vector 存储贵但召回 +6-45% |
| Binary 1-bit 量化(32× 压缩) | 客户超大语料(> 100M 文档)路径 |
| SciNCL graph contrastive | MimirQ KG triples 做训练数据,domain adaptation 利器 |
| Embedding fine-tune SaaS 化 | 给客户付费"私有 embedding"产品 |
| Voyage 3-large 32k context | 长文档客户专项,跳过 chunking 直接整页 embed |

### 9.4 不该做的事

- ❌ **不要直接换 Voyage-3-large 当默认**(\$0.18/M tokens 长尾客户不愿付)
- ❌ **不要把 Qwen3-Embedding-8B 当默认**(8B 自部署吃显存,客户私有部署贵)
- ❌ **不要无条件开 binary 量化**(< 1024 维模型崩,先量化先 benchmark)
- ❌ **不要跳过 benchmark runner 直接换模型**(MTEB 数字不一定代表客户语料表现)
- ❌ **不要忘记同时改 reranker**(对照 MEMORY 提到的 9 种 reranker plan,embedding 升级要配套 BGE-reranker-v2-m3 / Cohere Rerank 3 / Voyage-rerank-2 升级)

### 9.5 当前选择性落地状态(2026-05-13)

本轮只落地不依赖外部 API key、不改变默认线上行为、能直接验证的 P0 子集:

- [x] **Embedding benchmark runner skeleton**:新增 `app/rag/evaluation/embedding_bench/`,支持同一 golden set 下按模型汇总 `Recall@K / Hit@K / MRR / latency / cost`,并按召回优先选 best model。验证见 `tests/test_embedding_bench_runner.py`。
- [x] **Matryoshka shortlist + rescore 实验函数**:扩展 `app/rag/embedding/matryoshka.py`,提供低维 shortlist + full-dim rescore 的纯函数,暂不接入生产 retriever 默认链路。验证见 `tests/test_matryoshka_embedding.py`。
- [ ] **真实 provider 填实**:Voyage/Cohere/Jina/Bedrock 仍暂缓。原因:需要按官方 API contract / 鉴权 / 多模态输入格式逐一接入,不能在没有 API key 和 mock contract 的情况下假实现。
- [ ] **默认模型升级 / language routing 默认开**:暂缓。原因:必须先用 benchmark runner 跑现有客户 golden set,否则直接改默认可能导致召回回退。
- [ ] **Milvus SQ8 / binary 量化**:暂缓。原因:索引参数会影响线上召回和运维成本,需要真实向量规模和回归报告。

---

## 10. 关键文件清单(将动)

### 后端 P0
- `app/rag/embedding/providers/voyage.py:1`(10 → ~150 行真实 Voyage API + 32k context)
- `app/rag/embedding/providers/cohere.py:1`(10 → ~180 行真实 Cohere v4 + 多模态)
- `app/rag/embedding/providers/jina.py:1`(10 → ~150 行原生 v3 multi-task instructions)
- `app/rag/embedding/providers/bedrock.py:1`(10 → ~200 行 boto3 + SigV4)
- `app/rag/embedding/providers/qwen3.py`(new,Apache 2.0,0.6B/4B/8B 三档)
- `app/rag/embedding/providers/conan.py`(new,中文 SOTA)
- `app/rag/embedding/matryoshka.py:1`(44 → ~200 行,shortlist+rescore)
- `app/rag/embedding/config.py:349`(默认 small → BGE-M3 / Conan-v2 / Voyage-3-lite 三档)
- `app/rag/embedding/factory.py`(扩 language routing)
- `app/rag/retriever.py`(Milvus SQ8 + oversampling + matryoshka 集成)

### 评测(P0)
- `evaluation/embedding_bench/`(new)
  - `corpus/`(50 客户文档)
  - `golden/`(200 query+ground truth)
  - `runners/{bge_m3,qwen3_0_6b,qwen3_4b,qwen3_8b,conan_v2,voyage_3_large,cohere_v4,openai_3_small,openai_3_large}.py`
  - `reports/embedding_landscape_<date>.html`(单文件,对齐 PoC 三原则)

### 前端(P1)
- `web/components/embedding/embedding-selector.tsx`(new,数据集级选模型 + 维度档)
- `web/components/embedding/embedding-benchmark-results.tsx`(new,展示 §9 benchmark report)
- `web/components/embedding/shadow-migration-progress.tsx`(P1,蓝绿迁移可视化)

### 测试
- `tests/test_voyage_provider_real_api.py`(new,mock VCR)
- `tests/test_cohere_v4_multimodal.py`(new)
- `tests/test_qwen3_provider_local.py`(new)
- `tests/test_matryoshka_shortlist_rescore.py`(new)
- `tests/test_milvus_sq8_quantization.py`(new)

---

## 11. 验证

### 11.1 P0 验证(必达)

1. **9 个 provider 全部走得通**:`pytest tests/test_*_provider*` 全绿
2. **Embedding benchmark runner 跑通**:HTML 报告显示 Conan-v2 / Qwen3-8B / Voyage-3-large 中文 R@10 ≥ BGE-M3 baseline +5pt 以上(对齐 C-MTEB 排名)
3. **Matryoshka 实测**:256 维 shortlist + 1024 维 rescore vs 全 1024 维,**P50 延迟 -50%,召回降 < 3pt**
4. **Milvus SQ8**:50M vector 测试,内存占用 -75%,Recall@10 降幅 < 1%
5. **language routing 默认开**:中文 query → Conan-v2 / 英文 → Voyage-3-lite / 混合 → BGE-M3,trace SSE 显示 `embedding_provider=<选中>`
6. **新默认 BGE-M3** 在 50 题客户 Golden Set 上比 text-embedding-3-small **Recall@5 ≥ +3pt**

### 11.2 P1 验证

1. Cohere Embed v4 在图表密集 PDF 上 retrieval 实测 ≥ MimirQ CLIP 现状 +20pt
2. Shadow migration 跑 1k 文档双写,dual-index 一致性 = 100%
3. CustomIR 微调 BGE-M3 在工控客户 50 题上 R@10 +1-3pt

### 11.3 不变性(回归)

- 现有 4 个真实现 provider(openai/ollama/dashscope/local)行为不变
- `EMBEDDING_SHADOW_*` 蓝绿配置项不动语义
- BGE-M3 三态(dense+sparse+colbert)接口保持

---

## Sources

### MTEB / Benchmark
- [MTEB Leaderboard — Hugging Face](https://huggingface.co/spaces/mteb/leaderboard)
- [Embedding Model Leaderboard: MTEB Rankings March 2026 — Awesome Agents](https://awesomeagents.ai/leaderboards/embedding-model-leaderboard-mteb-march-2026/)
- [Best Embedding Model for RAG 2026 — Milvus Blog](https://milvus.io/blog/choose-embedding-model-rag-2026.md)
- [Best Embedding Models 2025: MTEB Scores & Leaderboard — Ailog RAG](https://app.ailog.fr/en/blog/guides/choosing-embedding-models)
- [Best Open-Source Embedding Models in 2026 — BentoML](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)
- [Which Embedding Model Should You Actually Use in 2026 — Cheney Zhang](https://zc277584121.github.io/rag/2026/03/20/embedding-models-benchmark-2026.html)
- [Maintaining MTEB: Towards Long Term Usability (arXiv 2506.21182, 2025)](https://arxiv.org/html/2506.21182v1)
- [Google takes #1 / Alibaba closes gap — VentureBeat](https://venturebeat.com/ai/new-embedding-model-leaderboard-shakeup-google-takes-1-while-alibabas-open-source-alternative-closes-gap)

### Qwen3-Embedding & Conan & Stella
- [Qwen3 Embedding (arXiv 2506.05176, 2025-06)](https://arxiv.org/html/2506.05176v1)
- [Qwen3-Embedding-8B — Hugging Face](https://huggingface.co/Qwen/Qwen3-Embedding-8B)
- [Qwen3-Embedding GitHub](https://github.com/QwenLM/Qwen3-Embedding)
- [Qwen3 Embedding Blog — Qwen LM](https://qwenlm.github.io/blog/qwen3-embedding/)
- [Conan-Embedding-v2 — TencentBAC HF](https://huggingface.co/TencentBAC/Conan-embedding-v2)
- [Conan-embedding: General Text Embedding (arXiv 2408.15710v2)](https://arxiv.org/html/2408.15710v2)
- [Jasper and Stella: distillation of SOTA embedding models (arXiv 2412.19048v2)](https://arxiv.org/html/2412.19048v2)
- [Stella en 1.5B v5 — NovaSearch HF](https://huggingface.co/NovaSearch/stella_en_1.5B_v5)
- [Comparative Analysis Qwen-3 vs BGE-M3 — Medium](https://medium.com/@mrAryanKumar/comparative-analysis-of-qwen-3-and-bge-m3-embedding-models-for-multilingual-information-retrieval-72c0e6895413)
- [C-MTEB · PyPI](https://pypi.org/project/C-MTEB/)
- [C-Pack: Packed Resources For General Chinese Embeddings (arXiv 2309.07597v3)](https://arxiv.org/html/2309.07597v3)
- [BGE-M3 — bge-model.com tutorial](https://bge-model.com/tutorial/4_Evaluation/4.2.3.html)

### Matryoshka
- [Matryoshka Representation Learning (arXiv 2205.13147, NeurIPS 2022)](https://arxiv.org/abs/2205.13147)
- [MRL Explained — Zilliz / Medium](https://medium.com/@zilliz_learn/matryoshka-representation-learning-explained-the-method-behind-openais-efficient-text-embeddings-a600dfe85ff8)
- [MRL Ultimate Guide — supermemory.ai](https://supermemory.ai/blog/matryoshka-representation-learning-the-ultimate-guide-how-we-use-it/)
- [Matryoshka Embeddings — Sentence Transformers Docs](https://sbert.net/examples/sentence_transformer/training/matryoshka/README.html)
- [MRL with CLIP for Multimodal Retrieval — Marqo](https://www.marqo.ai/blog/matryoshka-representation-learning-with-clip-for-multimodal-retrieval-and-ranking)
- [What Is MRL in Gemini Embedding 2 — MindStudio](https://www.mindstudio.ai/blog/matryoshka-representation-learning-gemini-embedding-2)
- [Scaling Vector Search: Quantization + MRL 80% Cost — TDS](https://towardsdatascience.com/649627-2/)
- [vLLM PR #16331 — Matryoshka support](https://github.com/vllm-project/vllm/pull/16331)

### Quantization
- [Binary & Scalar Embedding Quantization — Hugging Face Blog](https://huggingface.co/blog/embedding-quantization)
- [Binary Quantization — Qdrant](https://qdrant.tech/articles/binary-quantization/)
- [Scalar Quantization — Qdrant](https://qdrant.tech/articles/scalar-quantization/)
- [Vector Quantization Methods — Qdrant Course Day 4](https://qdrant.tech/course/essentials/day-4/what-is-quantization/)
- [What is Vector Quantization — Qdrant](https://qdrant.tech/articles/what-is-vector-quantization/)
- [Best Vector Databases 2025 — Firecrawl](https://www.firecrawl.dev/blog/best-vector-databases)

### Multimodal
- [Voyage-multimodal-3 announcement](https://blog.voyageai.com/2024/11/12/voyage-multimodal-3/)
- [Cohere Multimodal Embeddings Docs](https://docs.cohere.com/docs/multimodal-embeddings)
- [Cohere Embed v4 — Oracle Docs](https://docs.oracle.com/en-us/iaas/Content/generative-ai/cohere-embed-4.htm)
- [Cohere Embed v4 — Ailog RAG](https://app.ailog.fr/en/blog/news/cohere-embed-v4-multimodal)
- [Cohere Embed v4 on Bedrock — AWS](https://aws.amazon.com/about-aws/whats-new/2025/10/coheres-embed-v4-multimodal-embeddings-bedrock/)
- [Universal Embeddings for Multimodal Multilingual Retrieval — MRL 2025](https://aclanthology.org/2025.mrl-main.36.pdf)

### Fine-tuning
- [Why, When and How to Fine-Tune a Custom Embedding Model — Weaviate](https://weaviate.io/blog/fine-tune-embedding-model)
- [CustomIR: Unsupervised Fine-Tuning of Dense Embeddings (arXiv 2510.21729)](https://arxiv.org/html/2510.21729)
- [REFINE on Scarce Data: Retrieval Enhancement via Model Fusion (arXiv 2410.12890v1)](https://arxiv.org/html/2410.12890v1)
- [Contrastive Learning Using Graph Embeddings for Domain Adaptation (EMNLP 2025)](https://aclanthology.org/2025.emnlp-industry.103.pdf)
- [Efficient Domain Adaptation of Multimodal Embeddings (arXiv 2502.02048)](https://arxiv.org/abs/2502.02048)
- [Improving embedding with contrastive fine-tuning on small datasets (arXiv 2408.11868v1)](https://arxiv.org/html/2408.11868v1)
