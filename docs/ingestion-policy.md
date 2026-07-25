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
- `GET /api/v1/datasets/{dataset_id}/ingestion-policy/versions`（版本历史）
- `POST /api/v1/datasets/{dataset_id}/ingestion-policy/rollback`（回滚到指定版本）

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
      { "id": "text.remove_zero_width", "params": {} },
      { "id": "text.remove_control_chars", "params": {} },
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

## 4. 预处理步骤（allowlist）

当前支持的 `preprocess.steps[].id`：
- `text.reencode_utf8`
- `text.strip_bom`
- `text.normalize_newlines`
- `text.collapse_blank_lines`（连续空行压缩到最多 2 行）
- `text.trim_trailing_whitespace`
- `text.remove_zero_width`（零宽字符/软连字符）
- `text.remove_control_chars`（\\x00 等控制字符；保留 TAB/LF/CR）
- `text.normalize_unicode_nfc`（更保守的 Unicode 规范化）
- `text.normalize_unicode_nfkc`（全角/半角归一；谨慎启用）
- `html.strip_scripts_styles`
- `html.strip_comments`
- `html.strip_boilerplate_tags`（移除 nav/header/footer/aside/noscript 等样板标签内容）

说明：
- v1 不支持 step params（统一要求 `{}`），以保证可控性与安全性。
- 非文本类文件（如 PDF/DOCX）会跳过预处理（后续可迭代加入更多安全步骤）。

---

## 4.1 内置治理预设（Governance Profiles）

治理预设用于"解析后 Markdown 清洗"，会注入 `pipeline_patch + regex_rules`。当前内置 26 个（`app/services/governance_profiles.py`），按场景分组：

**通用 / 网页**
- `builtin:kb_default`：通用保守清洗（去噪/去目录/断行修复/去重页眉页脚）
- `builtin:html_web`：网页抓取/复制（去样板/去追踪参/段落去重）
- `builtin:html_xpath_main`：网页 XPath 优先抽正文（默认 `//main`，未命中则回退）
- `builtin:wiki_longform`：长文/Wiki（去重 + 参考文献裁剪）

**PDF**
- `builtin:pdf_text`：文本 PDF（断行修复/页眉页脚/表格规范化）
- `builtin:pdf_scanned_ocr`：扫描/OCR PDF（更强容错 + parse fallback）
- `builtin:policy_manual_pdf`：制度/手册类 PDF（条款结构友好）

**结构化 / 代码**
- `builtin:structured_data`：CSV/JSON/日志型（保留行边界，轻量去噪）
- `builtin:code_repo`：代码仓库（保留格式 + secrets 脱敏）
- `builtin:chat_exports`：聊天记录导出

**SaaS 数据源**
- `builtin:notion_database` · `builtin:confluence_enterprise` · `builtin:sharepoint_o365` · `builtin:feishu_lark_doc`

**行业（金融 / 法律 / 政务 / 医疗 / 保险）**
- `builtin:cn_a_share_annual_report` · `builtin:cn_prospectus` · `builtin:bank_compliance_report`
- `builtin:china_law_regulation` · `builtin:court_judgment` · `builtin:government_redhead`
- `builtin:medical_emr` · `builtin:insurance_policy_pdf`

**元数据 / 质量与合规**
- `builtin:metadata_enrich`：抽取 frontmatter/语言/关键词（best-effort）
- `builtin:quality_gate_quarantine`：低质量/大纲-only/低密度 → 隔离队列
- `builtin:pii_secrets_quarantine`：PII/密钥命中 → 隔离队列
- `builtin:legal_compliance`：PII/密钥脱敏

前端页面的规则编辑器里可以直接选择这些预设，也可以额外叠加 `pipeline_patch` 做细粒度覆盖。

---

## 4.2 前端“入库策略模板”

数据集“入库策略”页提供“一键模板”，用于快速生成常见规则组合（HTML/PDF/OCR/结构化数据/代码仓库/法律合同等）。  
模板只是起点：最终仍建议你根据数据源特点 **调整规则顺序** 与 **微调预处理/治理选项**。

---

## 5. 安全与限制（关键）

- 策略为 **声明式 JSON**，不允许上传可执行代码。
- 规则数量/扩展名数量/正则长度均有上限。
- filename_regex 做了基础 ReDoS 风险形态拦截（例如 `(.*)+`）。
- pipeline_patch 字段严格白名单（DocumentPipelineOptions）。
- 预处理有最大文本字节上限（避免大文件导致 OOM）。
