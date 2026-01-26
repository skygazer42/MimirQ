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

## API 一览（调试用）

- 创建预检 run：`POST /api/v1/datasets/{dataset_id}/precheck/scan-runs`
- 列表：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs`
- 详情：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}`
- Summary：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/summary`
- Findings drill-down：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/findings/{finding_key}`
- 导出 JSON：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/export`
- 导出 HTML：`GET /api/v1/datasets/{dataset_id}/precheck/scan-runs/{run_id}/export-html?redact=true`

