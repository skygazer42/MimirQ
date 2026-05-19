# MinerU 集成文档

MimirQ 现已集成 **MinerU 在线文档解析服务**，支持高级 PDF 解析功能。

## 功能特性

- ✅ **高级 PDF 解析**：表格识别、图片理解、公式识别、复杂排版
- ✅ **批量文件上传**：支持一次性上传最多 200 个文件
- ✅ **自动解析**：文件上传后自动提交解析任务
- ✅ **无缝集成**：启用后自动替换 PyMuPDF 解析器

---

## 快速开始

### 1. 申请 API Token

访问 [https://mineru.net](https://mineru.net) 官网申请 API Token。

### 2. 配置环境变量

编辑 `.env` 文件：

```bash
# MinerU Online API
MINERU_API_TOKEN=your-api-token-here
MINERU_API_BASE=https://mineru.net/api/v4
MINERU_MODEL_VERSION=vlm
MINERU_ENABLED=true
```

**参数说明**：
- `MINERU_API_TOKEN`：从官网申请的 API Token（**必填**）
- `MINERU_API_BASE`：API 端点（默认：https://mineru.net/api/v4）
- `MINERU_MODEL_VERSION`：模型版本
  - `vlm`：视觉语言模型（支持图片、表格、公式）
  - `txt`：纯文本模型（仅提取文本）
- `MINERU_ENABLED`：是否启用 MinerU（设置为 `true` 启用）

### 3. 重启后端服务

```bash
make backend
```

如果宿主机文件监听额度较低、热重载失败，可改用：

```bash
make backend-no-reload
```

启动时如果看到以下日志，说明 MinerU 已启用：

```
🚀 Using MinerU parser for PDF (advanced parsing)
```

---

## API 接口

### 1. 标准文档上传（自动使用 MinerU）

**POST** `/api/v1/documents/upload`

启用 MinerU 后，上传 PDF 文件会自动使用 MinerU 解析。

```bash
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -F "file=@document.pdf"
```

---

### 2. 批量申请上传 URL

**POST** `/api/v1/documents/batch-upload/apply-urls`

申请一批文件的上传 URL（最多 200 个）。

**请求示例**：

```bash
curl -X POST "http://localhost:8000/api/v1/documents/batch-upload/apply-urls" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      {"name": "file1.pdf", "data_id": "doc1"},
      {"name": "file2.pdf", "data_id": "doc2"}
    ]
  }'
```

**响应示例**：

```json
{
  "batch_id": "batch_abc123",
  "file_urls": [
    "https://upload-url-1...",
    "https://upload-url-2..."
  ],
  "files": [
    {"name": "file1.pdf", "data_id": "doc1"},
    {"name": "file2.pdf", "data_id": "doc2"}
  ],
  "message": "Upload URLs generated. Please upload files within 24 hours."
}
```

---

### 3. 上传文件到 MinerU

使用返回的 `file_urls` 上传文件（**PUT 请求，无需设置 Content-Type**）。

**Python 示例**：

```python
import requests

# Step 1: 申请上传 URL
response = requests.post(
    "http://localhost:8000/api/v1/documents/batch-upload/apply-urls",
    json={
        "files": [
            {"name": "file1.pdf", "data_id": "doc1"}
        ]
    }
)

result = response.json()
batch_id = result["batch_id"]
upload_url = result["file_urls"][0]

# Step 2: 上传文件
with open("file1.pdf", "rb") as f:
    upload_response = requests.put(upload_url, data=f)
    if upload_response.status_code == 200:
        print("✅ Upload success")
```

**CURL 示例**：

```bash
curl -X PUT -T /path/to/file.pdf 'https://upload-url...'
```

---

### 4. 查询解析任务状态

**GET** `/api/v1/documents/batch-upload/status/{batch_id}`

查询批量解析任务的进度和状态。

**请求示例**：

```bash
curl "http://localhost:8000/api/v1/documents/batch-upload/status/batch_abc123"
```

**响应示例**：

```json
{
  "batch_id": "batch_abc123",
  "status": "completed",
  "total_files": 2,
  "completed_files": 2,
  "failed_files": 0,
  "progress": 100,
  "result_url": "https://result-url..."
}
```

**状态说明**：
- `pending`：等待处理
- `processing`：解析中
- `completed`：解析完成
- `failed`：解析失败

---

## 完整使用示例

### Python 批量上传示例

```python
import requests
import time

API_BASE = "http://localhost:8000/api/v1/documents"

# 文件列表
files_to_upload = [
    {"name": "report1.pdf", "data_id": "report_001"},
    {"name": "report2.pdf", "data_id": "report_002"},
]

# Step 1: 申请上传 URL
print("📤 Applying upload URLs...")
response = requests.post(
    f"{API_BASE}/batch-upload/apply-urls",
    json={"files": files_to_upload}
)

if response.status_code != 200:
    print(f"❌ Failed to apply URLs: {response.text}")
    exit(1)

result = response.json()
batch_id = result["batch_id"]
upload_urls = result["file_urls"]

print(f"✅ Batch ID: {batch_id}")

# Step 2: 上传文件
print("⬆️  Uploading files...")
for i, url in enumerate(upload_urls):
    file_path = files_to_upload[i]["name"]
    with open(file_path, "rb") as f:
        upload_resp = requests.put(url, data=f)
        if upload_resp.status_code == 200:
            print(f"✅ {file_path} uploaded")
        else:
            print(f"❌ {file_path} upload failed")

# Step 3: 等待解析完成
print("⏳ Waiting for parsing...")
while True:
    status_resp = requests.get(f"{API_BASE}/batch-upload/status/{batch_id}")
    status = status_resp.json()

    print(f"📊 Progress: {status['progress']}% "
          f"({status['completed_files']}/{status['total_files']})")

    if status["status"] == "completed":
        print("✅ All files parsed successfully!")
        break
    elif status["status"] == "failed":
        print(f"❌ Parsing failed: {status.get('error')}")
        break

    time.sleep(5)
```

---

## 对比：PyMuPDF vs MinerU

| 特性 | PyMuPDF（基础） | MinerU（高级） |
|------|----------------|---------------|
| 文本提取 | ✅ | ✅ |
| 表格识别 | ❌ | ✅ |
| 图片理解 | ❌ | ✅ |
| 公式识别 | ❌ | ✅ |
| 复杂排版 | ⚠️ 部分支持 | ✅ |
| 处理速度 | 快（本地） | 慢（在线） |
| 成本 | 免费 | 需要 API Token |

---

## 注意事项

### 1. 上传链接有效期

申请的上传 URL **有效期为 24 小时**，请在有效期内完成上传。

### 2. 文件数量限制

单次批量上传最多支持 **200 个文件**。

### 3. Content-Type 设置

上传文件时**无需设置 Content-Type 请求头**，MinerU 会自动识别。

### 4. 自动任务提交

文件上传完成后，**无需手动调用提交接口**，系统会自动扫描并提交解析任务。

### 5. 解析时间

根据文件大小和复杂度，解析时间可能从几秒到几分钟不等。建议设置合理的超时时间（默认 10 分钟）。

---

## 故障排查

### 问题 1: MinerU 未启用

**现象**：上传 PDF 仍使用 PyMuPDF 解析

**解决方案**：
1. 检查 `.env` 文件中 `MINERU_ENABLED=true`
2. 检查 `MINERU_API_TOKEN` 是否配置
3. 重启后端服务

---

### 问题 2: API Token 无效

**现象**：返回 401 或认证失败错误

**解决方案**：
1. 确认 Token 从官网正确复制
2. 检查 Token 是否过期
3. 重新申请 Token

---

### 问题 3: 上传失败

**现象**：文件上传返回非 200 状态码

**解决方案**：
1. 检查上传 URL 是否过期（24 小时有效期）
2. 检查网络连接
3. 确认文件大小未超限（默认 50MB）

---

### 问题 4: 解析超时

**现象**：长时间停留在 `processing` 状态

**解决方案**：
1. 检查文件是否过大或过于复杂
2. 增加超时时间（默认 600 秒）
3. 查看 MinerU 服务状态

---

## 代码位置

相关代码文件：

- **服务类**: `app/services/mineru_service.py`
- **解析器**: `app/services/parsers/mineru_parser.py`
- **API 接口**: `app/api/v1/documents.py`
- **配置**: `app/config.py`
- **Schema**: `app/api/schemas/document.py`

---

## 进一步优化建议

1. **前端集成**：在前端添加批量上传 UI
2. **进度展示**：实时展示解析进度条
3. **错误处理**：更详细的错误信息和重试机制
4. **结果缓存**：缓存解析结果，避免重复解析
5. **WebSocket**：使用 WebSocket 推送解析状态，替代轮询

---

## 许可证

MinerU 是第三方服务，使用前请阅读其[服务条款](https://mineru.net/terms)。
