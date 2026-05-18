# TextIn xParse（外部 API）解析器集成

MimirQ 支持把 **TextIn xParse** 作为可选文档解析后端，通过官方 API 直接把
PDF / Office / 图片等文件转成 Markdown 或结构化结果。

> 这是**外部 API parser**，不是本地模型推理服务；本地容器本身不承担模型显存压力。
>
> 官方快速启动文档：<https://docs.textin.com/xparse/parse-quickstart>

## 启用方式

在 `.env` 或 `docker/.env` 中配置：

```env
TEXTIN_ENABLED=true
TEXTIN_API_URL=https://api.textin.com/ai/service/v1/pdf_to_markdown
TEXTIN_APP_ID=your-app-id
TEXTIN_SECRET_CODE=your-secret-code
TEXTIN_TIMEOUT_SEC=180
TEXTIN_PARSE_MODE=auto
TEXTIN_TABLE_FLAVOR=html
TEXTIN_APPLY_DOCUMENT_TREE=true
TEXTIN_MARKDOWN_DETAILS=true
TEXTIN_GET_IMAGE=none
TEXTIN_DPI=144
TEXTIN_PAGE_COUNT=0
```

如果是 Docker Compose 部署，修改 `docker/.env` 后需要重建/重启后端容器让
API/worker 读取新配置：

```bash
docker compose -f docker/docker-compose.yml up -d --no-build --force-recreate mimirq-api mimirq-worker
```

含义：

- `TEXTIN_API_URL`：官方 quickstart API 地址
- `TEXTIN_APP_ID` / `TEXTIN_SECRET_CODE`：TextIn 凭证
- `TEXTIN_PARSE_MODE`：`auto` / `scan` / `parse` / `lite` / `vlm`
- `TEXTIN_TABLE_FLAVOR`：表格输出格式，推荐 `html`
- `TEXTIN_APPLY_DOCUMENT_TREE`：是否保留文档树结构
- `TEXTIN_MARKDOWN_DETAILS`：是否增强 Markdown 细节
- `TEXTIN_GET_IMAGE`：`none` / `objects` / `pages` / `both`
- `TEXTIN_DPI`：页面渲染 DPI
- `TEXTIN_PAGE_COUNT`：限制页数，`0` 表示全部

实现细节与官方 quickstart 保持一致：本地文件请求体使用二进制流
（`application/octet-stream`），认证头为 `x-ti-app-id` 与 `x-ti-secret-code`；
不是 multipart/form-data。

## 前端 / 后端接入点

- 前端设置页已提供 TextIn 开关与参数配置
- 解析器下拉中可直接选择 `textin`
- 后端通过 `parser_backend=textin` 走 TextIn xParse API

可用下面的命令确认运行时是否真正可用（不会打印凭证）：

```bash
docker compose -f docker/docker-compose.yml exec -T -w /app mimirq-api python scripts/check_parsers.py
curl -fsS -H 'X-User-ID: demo' -H 'X-Tenant-ID: 00000000-0000-0000-0000-000000000000' \
  http://localhost:8000/api/v1/settings/status
```

`scripts/check_parsers.py` 里 `textin` 只有在 `TEXTIN_ENABLED=true` 且
`TEXTIN_API_URL`、`TEXTIN_APP_ID`、`TEXTIN_SECRET_CODE` 都非空时才会显示
`configured`。如果只打开开关但未配置凭证，它会明确显示
`missing TEXTIN_APP_ID` 或 `missing TEXTIN_SECRET_CODE`；这时前端入口已接线，
但真实 TextIn 解析请求不会成功。

## 适用范围

当前这次接入主要面向：

- PDF
- DOC / DOCX
- PPT / PPTX
- XLS / XLSX / CSV
- HTML / JSON
- 常见图片格式

## 资源说明

- TextIn 本身是**外部 API**
- 本地后端只负责上传文件、接收结果、落盘 artifact
- 因此本地服务侧**不要求额外 GPU 显存**
- 真正的计算资源消耗在 TextIn 服务端

## 使用方式

- 解析预览：在解析工作台选择 `textin`
- 入库解析：上传文档时指定 `parser_backend=textin`

## 返回与落盘

- 后端会将本次 TextIn 响应 best-effort 落盘在：
  - `.textin/<run_id>/result.json`
  - `.textin/<run_id>/result.md`

方便排障与复现实验。
