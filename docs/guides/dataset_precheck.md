# 预检扫描（未入库）

预检扫描用于“入库前摸底”：对一批本地文件夹（递归）做结构/质量画像，输出客观统计与可操作清单（不做主观评分），并支持导出单文件 HTML 报告用于分享。

## 适用场景

- 售前/报价：客户不方便给原始文档，可在本地跑预检，发脱敏报告回来
- 交付前摸底：拿到全量文档后先看格式分布、扫描件占比、长度分布、PII/Secrets 线索
- 内部治理：盘点历史文档资产，决定哪些先入库、哪些需要 OCR/清洗

## 安全开关（重要）

预检扫描会读取后端进程可访问的本地文件路径，因此默认关闭。

需要在后端 `.env` 中显式开启：

```bash
LOCAL_SCAN_ENABLED=true

# 可选：限制允许扫描的根目录（CSV）。
# 为空时只允许扫描 UPLOAD_DIR（默认 ./uploads）下的路径。
LOCAL_SCAN_ROOTS=/data,/mnt/share
```

## 扫描限流参数（可选）

```bash
# 最多扫描文件数（默认 20000）
PRECHECK_SCAN_MAX_FILES=20000

# 最多扫描总字节数（默认 5GB）
PRECHECK_SCAN_MAX_TOTAL_BYTES=5000000000

# 单文件抽样读取上限（默认 2MB）
PRECHECK_TEXT_EXTRACT_MAX_BYTES=2000000

# PDF 抽样页数（默认 3）
PRECHECK_PDF_SAMPLE_PAGES=3
```

## 使用方式（Web）

1. 进入「数据集」列表
2. 点击某个数据集的「预检扫描」
3. 填写 `root_path`（后端可访问的文件夹路径；容器部署需提前挂载目录）
4. 点击「启动」
5. 扫描完成后可导出：
   - JSON：结构化数据，便于二次分析
   - HTML：单文件离线报告（默认脱敏）
6. 进阶能力（建议做售前/交付对齐）：
   - 「代表性样本（抽样）」：自动分层抽样 + 问题分桶样本，可直接下载 JSON 发给乙方/顾问用于估工估价
   - 「近重复候选」：SimHash 基于抽样文本识别版本冲突候选（只输出待确认列表，不做删留决策）
   - 「预检 → 入库策略」：把预检结果转成可导入的 ingestion policy（闭环：从“报告”走向“配置”）
   - 「对比（Diff）」：同一路径/同一批数据多次扫描后对比变化，用于验证治理成效
   - 支持「取消」与实时进度（SSE；Web 会自动回退到轮询）

## API 一览（调试用）

- 创建预检 run：`POST /api/v1/datasets/{dataset_id}/precheck/scan-runs`
- 列表：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs`
- 详情：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}`
- Summary：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/summary`
- Findings drill-down：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/findings/{finding_key}`
- 代表性样本（抽样）：默认按 `3/1000` 文件比例抽样，并保证已出现的每种文件类型至少 1 个；可用 `size` 显式提高上限，例如 `GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/samples?size=30`
- 近重复详情：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/near-dups`
- Diff：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/diff?base_scan_run_id={base_id}`
- 建议入库策略：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/suggest-ingestion-policy`
- 应用入库策略：`POST /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/apply-ingestion-policy?replace=false`
- 取消：`POST /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/cancel`
- 进度 SSE：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/events`
- 导出 JSON：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/export`
- 导出 HTML：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/export-html?redact=true`

## 重要说明（和入库策略的关系）

- 预检扫描的定位是“入库前摸底”，输出的是客观统计 + 可操作清单，不会给“健康分/风险分”这类主观评分。
- 最值钱的闭环是：预检 -> 生成 ingestion policy -> 直接应用到数据集（或导出 JSON 再 import）。
  这样下游入库就能按规则分流：比如 PDF 扫描件优先走 OCR、表格大文件提示走结构化方案、PII/Secrets 启用合规脱敏等。
- 表格规则默认启用 **TAG 自动分流**（大表→Table Store/SQL，小表→解析+切块入库），避免“一刀切只走 TAG”导致小表无法检索。
- 表格结构化方案（TAG / Table Store）说明见：[docs/guides/table_tag.md](./table_tag.md)。
