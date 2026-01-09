  | 阶段名称 | 环节名称 | 环节处理内容 | 所用技术栈 | 当前使用模型 | 当前算力 | 当前执行速度 | 建议使用模型 | 建议算力要求 | 预测执行速度 |
  |---|---|---|---|---|---|---|---|---|---|
  | 文档入库 | 文档信息抽取 | 文档统一转 markdown | markitdown（部分格式会走 LibreOffice） | 无 | CPU 2–4C / 4–8GB | ~1–3s/10页 | 同 | CPU 4–8C / 8–16GB | ~0.5–2s/10页 |
  | 文档入库 | 文本切分 | 分段/切块 | llama_index | 无 | CPU 1–2C | <0.1s/1万字 | 同 | CPU 2–4C | <0.05s/1万字 |
  | 文档入库 | 文本向量化 | chunks 向量化入库 | llama_index + embeddings（本地或 OpenAI兼容 API） | .env 默认：bge-m3（API） | 本服务 CPU；推理侧需要 GPU | 取决推理侧 | bge-m3 | 推理侧 GPU 16GB+（L4/
  A10/3090/4090） | ~200–800 chunks/s（GPU） |
  | 查重引擎 | 召回候选 | SimHash TopK | SimHash | 无 | CPU | <10ms/查询（Top10~50） | 同 | CPU | 同 |
  | 查重引擎 | 语义疑似 | 向量召回 + 精排（可选） | faiss + reranker（可选） | .env 默认：bge-m3 + bge-reranker-large（API） | 推理侧 GPU 24GB 级更稳 | ~50–300ms/查询（随 topk） | bge-m3 + bge-reranker-large |
  推理侧 GPU 24GB（A10/L4/4090） | ~50–200ms/查询（中等 topk） |
  | 查重引擎 | faiss | TopK 检索 | faiss | 无 | CPU + 内存（索引常驻） | ~1–20ms/查询（随向量规模） | faiss CPU/GPU | CPU 8–16C + 32GB+；更大规模可加 GPU | ~1–10ms/查询 |
  | 文档审阅 | html文本并排比对 | 高亮显示/点击跳转 | JavaScript + DOM | 无 | 前端浏览器 | 即时 | 同 | 同 | 同 |
  | 文档审阅 | PDF 并排预览 | 原文保真 + 叠加高亮定位 | vue-pdf-embed（pdf.js） | 无 | 前端浏览器 | 即时（随页大小） | 同 | 同 | 同 |
