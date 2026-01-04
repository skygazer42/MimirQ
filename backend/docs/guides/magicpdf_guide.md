# MagicPDF（magic-pdf）解析器集成

MimirQ 支持将 **MagicPDF（PyPI: `magic-pdf`）** 作为可选 PDF 高级解析后端，输出 Markdown（可含图片引用），适用于扫描件、复杂排版等场景。

> 注意：`magic-pdf` 依赖较重（通常包含 `torch/transformers` 等），建议按需安装，并在独立环境/容器中运行。

## 启用方式

1. 安装 `magic-pdf`（示例）

```bash
pip install -r requirements-magicpdf.txt
```

2. 配置后端环境变量（`backend/.env`）

```bash
MAGIC_PDF_ENABLED=true
MAGIC_PDF_CLI=magic-pdf
MAGIC_PDF_METHOD=auto   # auto / ocr / txt
MAGIC_PDF_LANG=         # 可选：例如中文 "ch"
MAGIC_PDF_TIMEOUT_SEC=600
MAGIC_PDF_KEEP_ARTIFACTS=false
```

3. 重启后端

```bash
cd backend
uvicorn app.main:app --reload
```

## 使用方式

- 解析预览：前端“解析工作台”选择解析器为 `magicpdf`（也兼容 `magic-pdf` / `magic_pdf`）。
- 入库解析：上传文档时指定 `parser_backend=magicpdf`，或在系统设置中将默认解析器切换为 `magicpdf`（并确保已启用）。

## 产物与清理

- MagicPDF 会在上传文件同级目录下生成解析产物目录：`.magicpdf/<document_id>/...`（用于临时读取解析出的图片等资源）。
- 默认会在入库流程完成后 best-effort 清理该目录；如需保留用于排查问题，设置 `MAGIC_PDF_KEEP_ARTIFACTS=true`。
