# 扩充 `/data-governance/profiles` 内置 profile 库(垂直行业)

## Context

上一轮已为 `/prompts` 页面扩充 28 条 LLM 提示词模板。本任务对等扩充 `/data-governance/profiles` 页面的 **内置治理 profile 库**(`app/services/governance_profiles.py::get_builtin_governance_profiles`),从当前 **15 条通用 profile** 扩到 **27 条**,新增 **12 条中文垂直行业 profile**,覆盖金融报告、医疗政务法律、企业 Wiki/文档平台三个用户选定方向。

**重要:profile 不调 LLM**,它是 *声明式治理配置*(`pipeline_patch` + `regex_rules` + 可选 `extends`),不要混淆为提示词。本次扩充全部是规则引擎层面,与上一轮 LLM prompt 扩充正交。

### 用户决策摘要

| 决策点 | 选定 |
|---|---|
| 方向 | 扩充治理 profile 内置模板库(不动 LLM) |
| 范围 | 金融/金融报告 + 医疗/政务/法律 + 企业 Wiki/文档平台 |

---

## 关键复用

| 现有资产 | 路径 | 复用方式 |
|---|---|---|
| `BuiltinGovernanceProfile` dataclass | `app/services/governance_profiles.py:108-113` | 直接添加新 instance |
| `_p()` payload helper | `app/services/governance_profiles.py:116-127` | 复用构造 payload |
| `GOVERNANCE_RULE_PACKS` 现有 10 包 | `app/rag/preprocessing/rule_packs.py:15-122` | 新 profile 引用 + 补充 4 个新 pack |
| `extends` 继承机制 | `GovernanceProfilePayload.extends` schema | 垂直 profile 可继承通用 `kb_default` / `pdf_text` / `legal_compliance` |
| `pipeline_patch` 字段集 | `app/api/schemas/document.py::DocumentPipelineOptions` | 已知关键字段约 25 个 |
| Profile 列表 endpoint | `app/api/v1/pipeline.py` (governance_profiles GET/POST) | 既有,**无需改动** |
| 前端 profile 卡片网格 | `web/components/governance-profiles/governance-profiles-page.tsx` | 既有,**无需改动**(`is_system` 自动渲染为内置 Badge) |

**关键判断**:profile 写完后,前端会通过现有 list endpoint 自动出现,无须前端代码改动。这是和上一轮 prompts 任务的最大区别(上一轮需要前端加 Tab)。

---

## 新增清单(12 条 + 4 个新 rule pack)

### 第一组:rule_packs.py 新增 4 个 pack(为后续 profile 提供原料)

新增到 `GOVERNANCE_RULE_PACKS` 字典:

| pack key | 用途 | 模式举例 |
|---|---|---|
| `cn_finance_report_artifacts` | A 股年报/招股书页眉页脚、免责声明、披露说明 | `本公告(简式权益变动报告书)依据...`、`本公司董事会、监事会及董事...真实性...承诺`、`年度报告全文披露于...` |
| `cn_gov_redhead_artifacts` | 政府公文抄送/印发/签发说明 | `^抄送：.*$`、`^.*印发$`、`^签发：.*$`、`^承办单位：.*$` |
| `cn_medical_record_artifacts` | 病历科室/医生/床号(脱敏前去除展示性表头) | `^门诊号：[\d]+\s*$`、`^床位号：.*$`、`^主管医生：.*$`、`^主治医师：.*$` |
| `feishu_lark_noise` | 飞书/Lark 知识库导出标识 | `^由飞书文档导出$`、`^Powered by 飞书$`、`^最后编辑：.*$`、`^文档归属：.*$`、`^协作者：.*$` |

### 第二组:`get_builtin_governance_profiles()` 新增 12 条

#### A. 金融报告(4 条,均 PDF 重)

| key | name | extends(继承) | 关键 pipeline_patch | 引用 rule_packs |
|---|---|---|---|---|
| `builtin:cn_a_share_annual_report` | A 股年报 PDF(表格+口径) | (无,自包含) | tables=True / drop_duplicate_paragraphs / unwrap_lines / max_blank_lines=1 / parse_fallback_enabled | `cn_finance_report_artifacts` `pdf_header_footer_cn` `pdf_watermark` |
| `builtin:cn_prospectus` | A 股招股书(目录裁剪+风险因素去重) | (无) | trim_references / drop_duplicate_paragraphs (min_occurrences=2 风险因素重复) / remove_toc_lines | `cn_finance_report_artifacts` `pdf_header_footer_cn` |
| `builtin:bank_compliance_report` | 银行/金融机构合规报告(强 PII) | builtin:legal_compliance | pii_anonymize=True / secrets_redact=True / normalize_tables=True | `cn_finance_report_artifacts` `pdf_watermark` |
| `builtin:insurance_policy_pdf` | 保险合同 PDF(条款结构友好) | (无) | unwrap_lines=True / normalize_tables=True / trim_references=False(保留附录) / max_blank_lines=1 | `pdf_watermark` `pdf_header_footer_cn` |

#### B. 医疗/政务/法律(4 条)

| key | name | extends | 关键 pipeline_patch | 引用 rule_packs |
|---|---|---|---|---|
| `builtin:medical_emr` | 电子病历(强 PHI 脱敏) | builtin:legal_compliance | pii_anonymize=True / pii_mode=mask / secrets_redact=True / unwrap_lines=True | `cn_medical_record_artifacts` `pdf_header_footer_cn` |
| `builtin:government_redhead` | 政府红头公文(保留红头+章节) | (无) | remove_toc_lines=False (公文目录是正文) / unwrap_lines=True / max_blank_lines=1 | `cn_gov_redhead_artifacts` `pdf_header_footer_cn` `pdf_watermark` |
| `builtin:china_law_regulation` | 中国法规条例(条款结构) | builtin:policy_manual_pdf | drop_duplicate_paragraphs=True / trim_references=False(法规附则需要保留) / normalize_tables=True | `pdf_header_footer_cn` `pdf_watermark` |
| `builtin:court_judgment` | 法院判决书(裁判文书脱敏) | builtin:legal_compliance | pii_anonymize=True / pii_mode=mask / drop_duplicate_paragraphs=True | `cn_gov_redhead_artifacts` (法院签发格式相近) `pdf_header_footer_cn` |

#### C. 企业 Wiki / 文档平台(4 条)

| key | name | extends | 关键 pipeline_patch | 引用 rule_packs |
|---|---|---|---|---|
| `builtin:confluence_enterprise` | Confluence 企业导出(强化) | builtin:wiki_longform | remove_boilerplate=True / drop_duplicate_paragraphs=True / normalize_urls=True | `confluence_jira_noise` `web_navigation` `email_disclaimer` |
| `builtin:sharepoint_o365` | SharePoint / O365 导出 | builtin:wiki_longform | remove_boilerplate=True / remove_images="decorative" / normalize_urls=True | `web_navigation` `email_disclaimer` `markdown_export_noise` |
| `builtin:notion_database` | Notion 数据库 + 文档导出 | builtin:wiki_longform | normalize_tables=True (properties 表) / unwrap_lines=True | `notion_export_noise` `markdown_export_noise` |
| `builtin:feishu_lark_doc` | 飞书/Lark 知识库 | builtin:wiki_longform | drop_duplicate_paragraphs=True / normalize_urls=True / unwrap_lines=True | `feishu_lark_noise` `web_navigation` |

---

## 修改文件清单

### Backend(2 个文件,均纯追加)

**`app/rag/preprocessing/rule_packs.py`**(122 行 → ~180 行)

- 在 `GOVERNANCE_RULE_PACKS` 字典末尾追加 4 个新 pack:`cn_finance_report_artifacts` / `cn_gov_redhead_artifacts` / `cn_medical_record_artifacts` / `feishu_lark_noise`
- 每个 pack 5-8 条 `RegexRule(pattern=..., repl="", flags=0)`,**保守 line-oriented**(用 `(?m)` 锚定行首,避免误删段内文字),复用 `\u4e00-\u9fff` 中文字符类
- 不动现有 10 个 pack

**`app/services/governance_profiles.py`**(450 行 → ~700 行)

- 不动现有 15 个 BuiltinGovernanceProfile + `_p()` helper + 校验逻辑
- 在 `get_builtin_governance_profiles()` 返回列表末尾追加 12 条新 profile
- 每条用 `_p(input_formats=..., pipeline_patch=..., regex_rules=...)` 构造 payload
- 需要 `extends` 的 profile 直接在 `_p()` 后用 `.model_copy(update={"extends": "builtin:xxx"})` 或在 `_p()` 中加 extends 参数(看是否要扩 helper)
  - **决策**:扩 `_p()` 增加 `extends: str | None = None` 参数(向下兼容,默认 None),最小侵入

### Frontend(无)

前端 `governance-profiles-page.tsx` 自动展示新条目(`is_system=True` 自动 Badge);无需改动。

---

## YAGNI(本次不做)

- 不引入 AI 增强(LLM 推荐规则 / 自动描述生成)——用户明确不要
- 不动前端 UI(profile 卡片网格已能呈现 27 条)
- 不加新的 `pipeline_patch` 字段(只用已存在的)
- 不写 processing_scripts 附件(脚本风险高,暂不预置)
- 不做 profile 之间 diff / merge / preview UI 升级(留待后续 plan)
- 不重命名/重排现有 15 条
- 不引入新依赖

---

## Verification

按顺序跑 5 步:

1. **Python 单元**
   - `cd /data/temp34/MimirQ && python -c "from app.services.governance_profiles import get_builtin_governance_profiles; ps = get_builtin_governance_profiles(); print(f'total={len(ps)}'); keys=[p.key for p in ps]; assert len(set(keys))==len(keys), 'dup'; print('unique OK'); [print(p.key) for p in ps]"`
   - 应输出 27 个唯一 key,全部以 `builtin:` 开头

2. **Rule pack 引用合法**
   - `python -c "from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS; from app.services.governance_profiles import get_builtin_governance_profiles; pack_keys=set(GOVERNANCE_RULE_PACKS.keys()); print(f'packs={len(pack_keys)}'); ps=get_builtin_governance_profiles(); missing=[]; [missing.extend([(p.key,r) for r in (p.payload.pipeline_patch.get('governance_rule_packs') or []) if r not in pack_keys]) for p in ps]; print(f'missing refs: {missing}')"`
   - missing refs 必须为空数组

3. **Pipeline patch 合法性**
   - `python -c "from app.services.governance_profiles import get_builtin_governance_profiles, validate_and_normalize_payload; ps=get_builtin_governance_profiles(); [validate_and_normalize_payload(p.payload) for p in ps]; print('all payloads pass validation')"`
   - 必须无异常

4. **现有 pytest 不破坏**
   - `pytest tests/ -k "governance or profile" -v 2>&1 | tail -30`
   - 现有测试应全部通过

5. **lint**
   - `ruff check app/services/governance_profiles.py app/rag/preprocessing/rule_packs.py`
   - 必须 All checks passed

6. **前端冒烟**
   - `cd web && pnpm dev` 启动
   - 访问 `http://localhost:3000/data-governance/profiles`
   - 统计卡片"内置"应显示 27,网格能看到 12 条新条目
   - 任选 2 条新 profile 点击"查看",JSON payload 字段完整、`extends` 字段(若有)正确

---

## 工作量预估

- rule_packs.py 4 个新 pack(每 pack 5-8 条 regex): **0.5 天**
- governance_profiles.py 12 条新 profile(每条 pipeline_patch + regex_rules 设计): **1.5 天**(主要时间花在 regex 测试 + 决定每条用哪些 pack)
- Verification + 抽检: **0.5 天**
- **合计 ~2.5 天**

## 风险

| 风险 | 缓解 |
|---|---|
| 新 regex 误删正文 | 全部 line-oriented + `(?m)` 锚定行首/锚定整行;复用上一行 regex 风格;不引入跨行 `re.DOTALL` |
| `extends` 形成循环引用 | 现有 `validate_and_normalize_payload` + resolver 已有循环检测,新 profile 都 extends 已有内置,不会循环 |
| 新 profile 与现有 profile 重名 / key 冲突 | Verification Step 1 强制 key 唯一断言 |
| 垂直 profile 太激进(误删行业特有正文,如法规条款编号) | `china_law_regulation` 特意 `trim_references=False`;`government_redhead` 特意 `remove_toc_lines=False`;每条都在 plan 注明保留项 |
| 用户后续要求加 AI 增强 | 本期专注规则;若要加 AI(智能描述生成 / 规则推荐),开新 plan(参考上轮 prompts 已用的 builtin_library.py 通道) |
