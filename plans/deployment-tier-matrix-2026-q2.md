# MimirQ 部署档位矩阵 Plan(2026-05-19)

## Context

**为什么写**:用户指出"各种部署方式需要更新 —— 通算时 Docker 怎么部署,有算力时怎么部署,**区别就是有没有解析多模态模型**"。Explore 审计后发现:

- **现状骨架已经有**:3 套 compose(`docker/docker-compose.yml` 主栈 / `docker-compose.lite.yml` 精简 / `docker-compose.parsers.yml` 7 个 GPU 解析器),Makefile target `up/up-lite/up-mineru/up-paddlevl/up-marker/up-olmocr/up-qianfanocr`,Helm chart 也在 `deploy/helm/mimirq/`
- **但缺统一矩阵**:客户拿到 repo 不知道"我这 CPU only 主机该跑哪些"/"我有一张 4090 该开哪些"/"我有 A100 集群该全启什么";配置散在 `docker/.env.example` 注释里,无场景化模板
- **关键 bug 隐患**:`app/rag/reranker/colbert.py:134` 无 GPU **直接 raise RuntimeError**(不 fallback);`app/deepdoc/vision/ocr.py` 也无检测;**通算客户启了 ColBERT 就崩**
- **磁盘炸弹隐患**:全启 4 个 parser ~25-35GB 模型缓存(MinerU ~10-15GB / olmOCR ~8-10GB),客户不知情容易写满
- **已有 commit 趋势**:`b23b2ebd Prefer repo-local MagicPDF model cache` + `2cdd4a35 Expose parser credential gaps in Docker diagnostics` —— 团队已在补部署体验,本 plan 把这条线收尾

**目标**:把"无 GPU / 单卡入门 / 多卡企业"三种部署场景产品化为 **Tier1/Tier2/Tier3** 标准档位,每档有 ①明确硬件门槛 ②对应 `.env.tier{N}.example` ③对应 `make up-tier{N}` ④对应文档章节 ⑤运行时自检脚本。

**核心论断**:**部署形态本质是"哪些多模态模型在本地跑、哪些走云 API"的二选一组合**,不是无穷参数空间。三档已能覆盖 95% 客户。

---

## 三档部署矩阵

### Tier 1:通算部署(纯 CPU)

**适用客户**:POC 演示 / 小型企业 / 政务专网无 GPU / 等保二级 / 客户初评估
**硬件门槛**:
- CPU:4 核(推荐 8 核)
- 内存:16GB(推荐 32GB)
- 磁盘:50GB(模型缓存 ~5GB + 数据 ~30GB + 日志 ~15GB)
- GPU:**无要求**

**组件矩阵**:

| 组件 | Tier 1 配置 | 备注 |
|---|---|---|
| 解析器 | MagicPDF(CPU 模式)+ Marker + Docling | MAGIC_PDF_DEVICE_MODE=cpu;无 MinerU / PaddleOCR-VL / olmOCR |
| Embedding | `openai_compatible`(云 API) **或** `ollama` + 小模型(bge-m3-quant) | 默认推荐云 API |
| Reranker | `llm_based`(云 API)**或** `mmr`(零依赖) | **禁用 ColBERT / cross_encoder**(无 GPU 会崩) |
| LLM | 云 API(DashScope / OpenAI / DeepSeek) | 无本地 vLLM |
| KG | 全功能(KG 抽取走云 LLM) | extraction LLM 调云,quality/community 都走云 |
| OCR | Mathpix API / 百度 OCR / 阿里云 OCR | 无本地 PaddleOCR |
| 向量库 | Chroma(`docker-compose.lite.yml`)或 Milvus | 推荐 Chroma |

**启动**:`make up-tier1`(本 plan 新增,= `up-lite` + 强制环境变量)
**端到端能力**:支持 PDF/Word/Excel/Markdown 解析、Hybrid retrieval、KG、Agentic RAG;**不支持**:扫描件高精度 OCR(走云 OCR 即可)、本地多模态模型推理

### Tier 2:入门 GPU 部署(单卡消费级)

**适用客户**:中型企业私有化 / 一个团队的知识库 / 实验室环境
**硬件门槛**:
- CPU:8 核(推荐 16 核)
- 内存:32GB(推荐 64GB)
- 磁盘:200GB(模型缓存 ~30GB + 数据 ~100GB + 日志 ~50GB)
- GPU:**1× 消费级**(4090 / 3090 / A6000,16-24GB VRAM)

**组件矩阵**:

| 组件 | Tier 2 配置 | 备注 |
|---|---|---|
| 解析器 | MagicPDF(GPU)+ MinerU(vLLM,~10GB VRAM)+ Marker + Docling | 启用 `up-mineru` |
| Embedding | `local`(BAAI/bge-m3 GPU 推理) | GPU 占 ~3GB VRAM |
| Reranker | `colbert` **或** `cross_encoder`(本地 GPU) | GPU 占 ~3GB VRAM |
| LLM | 云 API **或** ollama(7B-14B 模型) | 不在 GPU 跑大 LLM,留给解析器 |
| KG | 全功能(LLM 走云) | 同 Tier 1 |
| OCR | DeepDoc vision OCR(本地 GPU)+ MinerU OCR | 替代云 OCR |
| 向量库 | Milvus(标准 `docker-compose.yml`) | |

**启动**:`make up-tier2`(本 plan 新增,= `up` + `up-mineru` + 环境变量)
**端到端能力**:全部 Tier 1 + 本地多模态 PDF 高精度解析 + 本地 ColBERT rerank;**不支持**:本地大 LLM、表格/公式专精模型(olmOCR / PaddleOCR-VL)

### Tier 3:完整 GPU 部署(多卡企业级)

**适用客户**:大型企业 / 等保三级 / 政务专有云 / 央企集团 / 数据完全不出本地
**硬件门槛**:
- CPU:32 核+
- 内存:128GB+
- 磁盘:1TB+ NVMe(模型缓存 ~80GB + 数据 ~500GB + 日志 ~200GB + 索引 ~200GB)
- GPU:**2-4× 数据中心级**(A100 80G / H100 80G / 国产 910B / 4090 多卡)

**组件矩阵**:

| 组件 | Tier 3 配置 | 备注 |
|---|---|---|
| 解析器 | **全启**:MagicPDF + MinerU + PaddleOCR-VL + olmOCR + Marker + Docling | `up-mineru + up-paddlevl + up-olmocr` |
| Embedding | `local`(BGE-M3 + 中英文双模型)| GPU 多卡分配 |
| Reranker | 三层:`colbert` + `cross_encoder` + `llm_based` | 三层 cascade |
| LLM | **本地 vLLM**(Qwen2.5-72B / DeepSeek-V3 / 国产 LLM)| 占 1-2 张卡 |
| KG | 全功能 + 本地 LLM(数据不出域)| extraction/community 都走本地 |
| OCR | DeepDoc + MinerU + PaddleOCR-VL 三层(自动选优) | |
| 向量库 | Milvus 集群(3 节点) | sharding + replica |

**启动**:`make up-tier3`(本 plan 新增,组合启动 + 等待健康检查)
**端到端能力**:完全离线 + 全多模态 + 本地 LLM,**满足等保三级 / 数据出境合规 / 信通院备案**

### 三档对比速查表

| 维度 | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|
| GPU | 无 | 1× 消费级 | 2-4× 数据中心 |
| 内存 | 16-32GB | 32-64GB | 128GB+ |
| 磁盘 | 50GB | 200GB | 1TB+ |
| 本地多模态解析 | ❌ | ✅(MinerU) | ✅✅(全栈) |
| 本地 Embedding | ❌(用云) | ✅ | ✅✅(双模型) |
| 本地 LLM | ❌(用云) | ❌(用云) | ✅(vLLM) |
| 数据出境 | 部分(LLM/Embedding API)| 部分(LLM API)| **零**(完全离线)|
| 适合客户 | POC / 小企业 | 中企 / 团队 | 大企 / 政务 / 等保三级 |
| 价格档位(参考)| ¥0(开源)/ ¥10-30 万 SaaS | ¥80-150 万私有化 | ¥200-500 万私有化 |
| 启动命令 | `make up-tier1` | `make up-tier2` | `make up-tier3` |

---

## 落地任务

### P0(本周可启动)

**P0.1 写《部署档位选择指南》(0.5 day)**
- 新建 `docs/deployment/tier-selection.md`(单文件 HTML 也行,沿用 FILE_A023 三原则)
- 内容:
  - 三档矩阵速查表(上文)
  - "我该选哪档"决策流程图(GPU 有无 / 数据出境政策 / 客户类型)
  - 每档详细组件清单 + 内存/磁盘估算公式
- 在 `README.md` 顶部加跳转链接

**P0.2 三档 `.env` 模板(0.5 day)**
- 新建 `docker/.env.tier1.example`(纯 CPU,默认云 API):
  ```bash
  EMBEDDING_PROVIDER=openai_compatible
  RERANKER_PROVIDER=llm
  MAGIC_PDF_DEVICE_MODE=cpu
  MINERU_ENABLED=false
  PADDLEVL_ENABLED=false
  ```
- 新建 `docker/.env.tier2.example`(单卡 GPU,本地解析+rerank+云 LLM)
- 新建 `docker/.env.tier3.example`(多卡 GPU,全本地)
- 在 `.env.example` 顶部加注释:"按场景选 tier{N},不要混搭"

**P0.3 修 ColBERT / DeepDoc 无 GPU fallback bug(0.5 day)**
- `app/rag/reranker/colbert.py:131-136` —— `raise RuntimeError` 改为:
  - 若 `RERANKER_FORCE_DEVICE=cuda` 配置则仍 raise(显式要求)
  - 否则 fallback 到 `cross_encoder`(若也无 GPU)→ fallback 到 `mmr`(零依赖)
  - 日志 warning + 上报 OTel metric `reranker.gpu_unavailable_fallback`
- `app/deepdoc/vision/ocr.py` —— 加 `torch.cuda.is_available()` 检测,无 GPU 时:
  - 默认 fallback 到 CPU 推理(慢但能跑)
  - 或抛 *友好* 异常 `RuntimeError("DeepDoc OCR requires GPU. Set DEEPDOC_OCR_PROVIDER=cloud to use cloud OCR.")`
- 添加 pytest 用例 mock `torch.cuda.is_available() = False` 验证 fallback 路径

**P0.4 Makefile 三档 target(0.5 day)**
- 在 `Makefile` 加:
  ```makefile
  up-tier1: ## 通算部署(纯 CPU,默认云 API)
      cp docker/.env.tier1.example docker/.env
      docker compose -f docker/docker-compose.lite.yml up -d

  up-tier2: ## 入门 GPU 部署(单卡 + MinerU + 本地 rerank)
      cp docker/.env.tier2.example docker/.env
      docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile mineru up -d

  up-tier3: ## 完整 GPU 部署(全多模态 + 本地 LLM)
      cp docker/.env.tier3.example docker/.env
      docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml \
        --profile mineru --profile paddlevl --profile olmocr up -d
  ```
- 加 `make tier-check`:跑 `scripts/check_deployment_tier.py` 自检脚本(P1.1)

### P1(2-4 周)

**P1.1 启动自检脚本 `scripts/check_deployment_tier.py`(1 day)**
- 检测当前环境:GPU 数量 / VRAM / 内存 / 磁盘
- 推荐档位(并提示"你声明的是 Tier 2 但实际只有 Tier 1 硬件")
- 验证 `.env` 配置与硬件一致(比如 `EMBEDDING_PROVIDER=local` 但无 GPU → warn)
- 输出 HTML 单文件报告(沿用 FILE_A023 三原则)
- 集成到 `make tier-check` 和 docker compose `healthcheck`

**P1.2 客户可视化"硬件配置生成器"(2 day)**
- 单文件 HTML `docs/deployment/configurator.html`(无后端)
- 表单:GPU 类型 / 内存 / 数据出境 / 客户类型 / 解析文档量(文档/月)
- 输出:推荐档位 + 生成 `.env` 内容(可下载)+ 启动命令
- 嵌入 README + 客户演示

**P1.3 Helm chart 三档 values 文件(2 day)**
- `deploy/helm/mimirq/values-tier1.yaml`(CPU only)
- `deploy/helm/mimirq/values-tier2.yaml`(单卡 + NodeSelector)
- `deploy/helm/mimirq/values-tier3.yaml`(多卡 + GPU Operator 依赖)
- 每个 yaml 包含 resources / nodeSelector / tolerations

**P1.4 模型缓存预下载脚本(1 day)**
- `scripts/preload_models.sh --tier 2`:按档位下载模型到 `models/`
- 支持镜像源(HuggingFace mirror / ModelScope)
- 离线环境包(对接 P2-2 边缘部署 plan)— `scripts/build_offline_bundle.sh`

**P1.5 docs/deployment 重组(1 day)**
- 现有 `docs/deployment/docker_compose.md` 内容拆分:
  - `tier-selection.md`(P0.1)
  - `tier1-cpu-only.md`
  - `tier2-single-gpu.md`
  - `tier3-multi-gpu.md`
  - `troubleshooting.md`(集中现有 troubleshooting)
  - `helm.md`(K8s 单独章节)
- 移除老 `docker_compose.md` 改为 stub 跳转

### P2(2-3 月)

**P2.1 GPU 利用率监控 dashboard(1 周)**
- 接 OTel + nvidia-smi exporter
- Grafana dashboard:解析器 GPU 占用 / Embedding GPU 占用 / LLM GPU 占用
- 异常告警(VRAM 满 / 卡掉线 / 温度过高)

**P2.2 多卡自动负载均衡(1-2 周)**
- 多 MinerU 实例 + nginx load balancer(对照 `docker-compose.parsers.yml` 现有结构)
- 解析任务排队 → GPU 卡级别 round-robin
- 失败 retry + 卡级别熔断

**P2.3 混合云部署(2 周)**
- 本地优先 + 云 API 兜底(本地超时 / OOM / 报错时切云)
- 配置:`PARSER_FALLBACK_MODE=local_first|cloud_first|local_only|cloud_only`
- 成本可视化(本地 GPU 折旧 vs 云 API 调用 ¥)

**P2.4 国产 GPU 适配(3 周,客户驱动)**
- 华为昇腾 910B(CANN + MindIE)
- 寒武纪 MLU / 海光 DCU
- 与 `plans/rag-edge-deployment-2026-q3.md` P2-2 合并

---

## 关键文件清单

### 已有(可复用)
- `docker/docker-compose.yml`(222 行,主栈)
- `docker/docker-compose.lite.yml`(精简栈)
- `docker/docker-compose.parsers.yml`(194 行,7 个 GPU 解析器 profile)
- `docker/Dockerfile`(builder + runtime,CPU torch)
- `docker/mineru/Dockerfile`(`FROM vllm/vllm-openai:v0.10.1.1`)
- `docker/paddlevl/Dockerfile`(`FROM paddlepaddle/paddleocr-vl:latest-nvidia-gpu`)
- `docker/.env.example`(环境变量模板)
- `docs/deployment/docker_compose.md`(待重组)
- `Makefile`(`up/up-lite/up-mineru/up-paddlevl/up-marker/up-olmocr/up-qianfanocr`)
- `deploy/helm/mimirq/`(K8s chart)

### 待修(bug + 改进)
- `app/rag/reranker/colbert.py:131-136`(无 GPU fallback)
- `app/deepdoc/vision/ocr.py`(无 GPU 检测)
- `app/parsing/parsers/magic_pdf_parser.py:177`(已有 fallback,可参考)

### 待新增(本 plan 产出)
- `docs/deployment/tier-selection.md`
- `docs/deployment/tier1-cpu-only.md`
- `docs/deployment/tier2-single-gpu.md`
- `docs/deployment/tier3-multi-gpu.md`
- `docs/deployment/troubleshooting.md`
- `docs/deployment/configurator.html`
- `docker/.env.tier1.example`
- `docker/.env.tier2.example`
- `docker/.env.tier3.example`
- `scripts/check_deployment_tier.py`
- `scripts/preload_models.sh`
- `scripts/build_offline_bundle.sh`
- `deploy/helm/mimirq/values-tier1.yaml`
- `deploy/helm/mimirq/values-tier2.yaml`
- `deploy/helm/mimirq/values-tier3.yaml`
- Makefile target `up-tier1` / `up-tier2` / `up-tier3` / `tier-check`

---

## 验证(每档完工的客观信号)

### Tier 1 验证
```bash
# 在纯 CPU 主机(无 nvidia-smi)
git clone <repo> && cd <repo>
make up-tier1
# 等 60s 健康检查
curl http://localhost:8000/health  # 200 OK
# 端到端测试
curl -F "file=@test.pdf" http://localhost:8000/api/v1/upload
curl http://localhost:8000/api/v1/query?q=测试
# 验证:无 cuda 报错 / 解析成功 / 检索成功
make tier-check  # 输出:Tier 1 健康 / 推荐档位 Tier 1
```

### Tier 2 验证
```bash
# 在单卡 4090 主机
make up-tier2
nvidia-smi  # 验证 MinerU vLLM 占用 ~10GB VRAM
# 端到端:上传扫描件 PDF
curl -F "file=@scanned.pdf" http://localhost:8000/api/v1/upload?parser=mineru
# 验证:MinerU 解析成功 + ColBERT rerank 在 GPU 跑
```

### Tier 3 验证
```bash
# 在多卡 A100 主机
make up-tier3
nvidia-smi  # 验证 4 张卡分配(解析 1 张 / Embedding 1 张 / LLM 2 张)
# 完全断网测试
sudo iptables -A OUTPUT -j DROP  # 断外网
curl http://localhost:8000/api/v1/query?q=测试  # 仍能成功 → 验证零外联
```

### Fallback 验证(P0.3)
```bash
# 模拟无 GPU 启用 ColBERT
RERANKER_PROVIDER=colbert make up-tier1  # 不应该崩
# 日志应有:WARNING reranker.gpu_unavailable_fallback → cross_encoder → mmr
pytest tests/test_reranker_gpu_fallback.py  # 新增测试
```

---

## 与既有 plan 的关系

| 既有 plan | 关系 |
|---|---|
| `plans/rag-edge-deployment-2026-q3.md` | **本 plan 是其 Tier 1/2/3 前置**:边缘部署 = Tier 1/2 + 国密 + 等保;本 plan 收敛三档,边缘 plan 加合规层 |
| `plans/deepdoc-api-productization-2026-q3.md` | **正交**:DeepDoc API 化是把解析能力 SaaS 化,本 plan 是私有化部署矩阵;两条独立商业线 |
| `plans/code-health-audit-2026-q2.md` | **正交**:健康度是代码内部,本 plan 是部署外壳;但 B-P0.1(async sleep)+ A-P0.3(error handler)与本 P0.3 fallback 修复可一并完成 |
| `plans/kb-feature-parity-2026-q2.md` C-4 | **正交**:SLA / 计费是 SaaS 商业层,本 plan 是部署形态;两者合并即"私有化 + SaaS 双形态产品" |

---

## 决策门槛

| 任务 | 启动门槛 | 砍掉条件 |
|---|---|---|
| P0(全部)| 无 — 立即启动 | — |
| P1.1 自检脚本 | 客户反馈"装错档" | 0 客户反馈 |
| P1.2 configurator.html | 销售要求 | 销售用 Markdown 就够 |
| P1.3 Helm 三档 | 客户用 K8s | 客户都用 docker compose |
| P1.4 离线包 | 政务客户付费意向 | 无政务客户 |
| P2.1 GPU 监控 | 多卡客户上线 | 仅 Tier 1/2 客户 |
| P2.2 负载均衡 | 单实例不够 | 客户文档量小 |
| P2.3 混合云 | 客户主动询问 | 客户都全私有 / 全云 |
| P2.4 国产 GPU | 政务客户明确指定 | 客户用 NVIDIA |

---

## 不在本 plan 范围

- **算法层优化**(已在 27 份调研 plan)
- **代码健康度**(已在 `plans/code-health-audit-2026-q2.md`)
- **新增功能**(已在 `plans/kb-feature-parity-2026-q2.md`)
- **特定客户定制部署**(本 plan 是标准档位,定制由销售单独 spec)

---

## 一句话总结

**部署本质 = "哪些多模态模型本地跑、哪些走云 API" 的三档配置(Tier 1 全云 / Tier 2 单卡解析 / Tier 3 全本地)。P0 一周:写指南 + 三档 .env + 修 fallback bug + Makefile target,客户首次安装时间从"翻文档 1 小时"降到"一行命令 5 分钟"。**
