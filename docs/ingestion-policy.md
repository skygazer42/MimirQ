# 入库策略（解析前预处理）设计与使用

本系统的“数据治理”主要发生在 **文档解析后（Markdown）**：去噪/去目录/去样板、断行修复、页眉页脚去重、PII/Secrets 处理等。

但在真实知识库场景里，**解析之前** 也经常需要对“原始文件”做预处理，否则会出现：
- 编码异常导致解析器输出乱码（尤其是 txt/json/csv/html）
- HTML 页面包含大量 script/style/comment 噪声，影响 HTML→MD
- 行尾空格/CRLF 导致 diff 抖动、分段异常

因此新增：**数据集级 Ingestion Policy（入库策略）**  
支持按文件类型（扩展名/文件名规则）配置：
1) 解析前预处理（file preprocess）
2) 解析后端（parser backend）/ chunk 策略（可选覆盖）
3) 治理预设（Governance Profile）：注入 pipeline_patch + regex_rules
4) 高级 pipeline_patch（按 DocumentPipelineOptions 字段白名单校验）

---

## 1. 数据流（新增一段）

原流程：
`upload -> parse -> governance(clean markdown) -> chunk/index`

新增后：
`upload -> preprocess(file) -> parse(preprocessed file) -> governance(clean markdown) -> chunk/index`

预处理阶段只做“安全、确定性、可审计”的操作，不执行任何代码。

---

## 2. 后端接口

### 数据集入库策略 CRUD
- `GET /api/v1/datasets/{dataset_id}/ingestion-policy`
- `PUT /api/v1/datasets/{dataset_id}/ingestion-policy`
- `POST /api/v1/datasets/{dataset_id}/ingestion-policy/import`（JSON 脚本上传，默认 replace=true）
- `GET /api/v1/datasets/{dataset_id}/ingestion-policy/export`

### 一站式预览（用于页面“样例文件预览”）
- `POST /api/v1/pipeline/ingestion-preview`
  - 输入：`file` + `dataset_id`
  - 输出：命中规则、预处理日志、解析 Markdown、治理 clean+diff+issues

---

## 3. 策略脚本（JSON）结构

顶层：
```json
{
  "version": "1",
  "rules": []
}
```

规则示例（PDF）：
```json
{
  "id": "pdf-default",
  "name": "PDF 默认",
  "enabled": true,
  "match": { "extensions": [".pdf"] },
  "preprocess": { "enabled": false, "steps": [] },
  "parser_backend": "auto",
  "chunk_strategy": "",
  "governance_profile_ref": "builtin:pdf_text",
  "pipeline_patch": {}
}
```

规则示例（HTML 网页）：
```json
{
  "id": "html-web",
  "name": "HTML 网页（先预处理再解析）",
  "enabled": true,
  "match": { "extensions": [".html", ".htm"] },
  "preprocess": {
    "enabled": true,
    "steps": [
      { "id": "text.reencode_utf8", "params": {} },
      { "id": "text.strip_bom", "params": {} },
      { "id": "text.normalize_newlines", "params": {} },
      { "id": "html.strip_scripts_styles", "params": {} },
      { "id": "html.strip_comments", "params": {} }
    ]
  },
  "parser_backend": "pandoc",
  "governance_profile_ref": "builtin:html_web",
  "pipeline_patch": {
    "governance_enabled": true
  }
}
```

---

## 4. 预处理步骤（v1 allowlist）

当前支持的 `preprocess.steps[].id`：
- `text.reencode_utf8`
- `text.strip_bom`
- `text.normalize_newlines`
- `text.trim_trailing_whitespace`
- `html.strip_scripts_styles`
- `html.strip_comments`

说明：
- v1 不支持 step params（统一要求 `{}`），以保证可控性与安全性。
- 非文本类文件（如 PDF/DOCX）会跳过预处理（后续可迭代加入更多安全步骤）。

---

## 5. 安全与限制（关键）

- 策略为 **声明式 JSON**，不允许上传可执行代码。
- 规则数量/扩展名数量/正则长度均有上限。
- filename_regex 做了基础 ReDoS 风险形态拦截（例如 `(.*)+`）。
- pipeline_patch 字段严格白名单（DocumentPipelineOptions）。
- 预处理有最大文本字节上限（避免大文件导致 OOM）。

