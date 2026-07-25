# Data Governance Profiles (治理预设 / 脚本)

MimirQ 支持用“治理预设（Profiles）”来统一管理数据治理策略（尤其适用于 HTML->MD、PDF->MD 的常见问题）。

本质上，Profile 是一个 **声明式 JSON 脚本**，用于：

- 批量套用一组 PipelineOptions（`pipeline_patch`）
- 附加一组 Regex 清洗规则（`regex_rules`）
- 可选启用内置规则包（rule packs）：`pipeline_patch.governance_rule_packs`

重要：Profile **不会**、也 **不允许** 上传/执行任意 Python/JS 代码（避免 RCE 风险）。

---

## 1) Profile JSON Schema（单个）

导入/导出文件是一个 JSON 对象，最简单是单个 profile：

```json
{
  "name": "PDF 文本版（修复断行/页眉页脚/表格）",
  "description": "适用于可复制文本的 PDF：合并软换行、去重页眉页脚、表格规范化。",
  "key": "pdf_text",
  "payload": {
    "version": "1",
    "input_formats": ["markdown"],
    "pipeline_patch": {
      "governance_enabled": true,
      "governance_rule_packs": ["pdf_watermark", "pdf_header_footer_cn"],
      "governance_unwrap_lines": true,
      "governance_remove_common_lines": true,
      "governance_normalize_tables": true
    },
    "regex_rules": [
      { "pattern": "(?m)^\\\\s*CONFIDENTIAL\\\\s*$", "repl": "", "flags": 2 }
    ]
  }
}
```

也支持批量导入（多个 profiles）：

```json
{
  "profiles": [
    { "...": "..." },
    { "...": "..." }
  ]
}
```

---

## 2) 字段说明

### 顶层
- `name`：展示名称（必填）
- `description`：说明（可选）
- `key`：可选的稳定 key（建议填写；tenant 内唯一）
- `payload`：核心内容

### payload
- `version`：schema 版本（当前为 `"1"`）
- `input_formats`：建议的预览输入格式（`markdown` / `html`）
- `pipeline_patch`：将被合并到 PipelineOptions（前端/后端都支持）
- `pipeline_patch.governance_rule_packs`：可选，启用内置 rule packs（见 `docs/governance-rule-packs.md`）
- `regex_rules`：附加的清洗规则（与默认规则叠加）

### regex_rules
每条规则结构：
- `pattern`：正则（必填）
- `repl`：替换文本（默认 `""`）
- `flags`：Python `re` flags（仅允许组合：`IGNORECASE(2)` / `MULTILINE(8)` / `DOTALL(16)`）

---

## 3) 安全限制（服务端强校验）

为避免 ReDoS 等风险，服务端会对上传脚本做强校验/裁剪：

- 文件大小：<= 256KB
- 规则数量：<= 60
- `pattern` 最大长度：<= 600
- `flags` 仅允许：`IGNORECASE | MULTILINE | DOTALL`
- 拒绝常见灾难性回溯形态（例如嵌套量词）：`(.*)+` / `(.+)+` / `([a-z]+)*` 等
- 规则会尝试 `re.compile`，无法编译的将被拒绝/丢弃

---

## 4) 推荐 Profiles（典型场景）

> 内置预设共 26 个（`builtin:*`，覆盖通用/网页/PDF/结构化/SaaS 源/行业/质量合规），完整清单见 [ingestion-policy.md §4.1](./ingestion-policy.md)；下面挑典型场景说明组合思路。

### HTML -> Markdown（网页抓取/复制）
常见问题：
- 面包屑/导航/版权声明/分享按钮等样板信息混入
- 追踪 URL（utm_*/gclid/fbclid…）

建议组合：
- `governance_remove_boilerplate = true`
- `governance_normalize_urls = true` + `governance_normalize_urls_strip_tracking = true`
- 可选：`governance_remove_images = "decorative"`

### PDF -> Markdown（可复制文本）
常见问题：
- 段落被硬换行切碎（每行 60~90 字）
- 页眉/页脚跨页重复
- 表格对齐混乱

建议组合：
- `governance_unwrap_lines = true`
- `governance_remove_common_lines = true`
- `governance_normalize_tables = true`

### 制度/手册类 PDF（条款结构友好）
常见问题：
- 目录/页眉页脚/水印等噪声混入正文，影响检索召回
- 同一段落在多页反复出现（页脚免责声明/适用范围等），导致向量与 BM25 噪声变大
- 软换行导致 “第 X 条/第 X 章” 等结构被拆散

推荐：
- 直接使用内置治理预设：`builtin:policy_manual_pdf`
- 或者确保启用以下组合（保守）：
- `governance_remove_toc_lines = true`
- `governance_remove_noise_lines = true`
- `governance_unwrap_lines = true`
- `governance_remove_common_lines = true`
- `governance_drop_duplicate_paragraphs = true`
- `governance_normalize_tables = true`

---

## 5) 使用方式（UI）

目前 UI 已在以下位置提供 Profile：

- **数据治理工作台** -> “智能清洗配置” -> “治理预设（Profiles/脚本）”
- **数据集** -> “数据集默认管线” -> “治理预设（Profiles/脚本）”

支持：
- 选择内置/自定义 Profile
- 导入脚本（JSON）
- 导出脚本（JSON）
- 一键应用到当前配置（会覆盖对应字段）
