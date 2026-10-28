import type { GovernanceProfileSummary } from '@/types'

const GROUPS: Record<string, string[]> = {
  通用文档: ['kb_default', 'pdf_text', 'policy_manual_pdf', 'pdf_scanned_ocr', 'wiki_longform'],
  网页与协作: ['html_web', 'html_xpath_main', 'chat_exports', 'confluence_enterprise', 'sharepoint_o365', 'notion_database', 'feishu_lark_doc'],
  代码与结构: ['code_repo', 'structured_data', 'metadata_enrich'],
  合规与行业: ['legal_compliance', 'quality_gate_quarantine', 'pii_secrets_quarantine', 'cn_a_share_annual_report', 'cn_prospectus', 'bank_compliance_report', 'insurance_policy_pdf', 'medical_emr', 'government_redhead', 'china_law_regulation', 'court_judgment'],
}

const NAMES: Record<string, string> = {
  kb_default: '知识库默认', pdf_text: 'PDF 文本版', policy_manual_pdf: '制度与手册', pdf_scanned_ocr: '扫描件与 OCR', wiki_longform: '长文与 Wiki',
  html_web: '网页 HTML', html_xpath_main: '网页正文提取', chat_exports: '聊天记录', confluence_enterprise: 'Confluence 导出', sharepoint_o365: 'SharePoint 导出', notion_database: 'Notion 导出', feishu_lark_doc: '飞书知识库',
  code_repo: '代码仓库', structured_data: '结构化数据', metadata_enrich: '元数据增强', legal_compliance: '合规脱敏', quality_gate_quarantine: '质量门禁', pii_secrets_quarantine: '合规门禁', cn_a_share_annual_report: 'A 股年报', cn_prospectus: 'A 股招股书', bank_compliance_report: '金融合规报告', insurance_policy_pdf: '保险合同', medical_emr: '电子病历', government_redhead: '政府公文', china_law_regulation: '法规条例', court_judgment: '法院判决书',
}

export function profileRef(profile: GovernanceProfileSummary) {
  return profile.is_system ? profile.key : profile.id?.trim() || profile.key
}

export function profileIdentity(profile: GovernanceProfileSummary) {
  const id = profile.is_system ? profile.key.replace(/^builtin:/, '') : ''
  const group = profile.is_system ? Object.entries(GROUPS).find(([, keys]) => keys.includes(id))?.[0] || '其他模板' : '自定义配置'
  const kind = /pdf|report|prospectus|policy|manual|government|law|judgment/.test(id) ? 'pdf'
    : /html|confluence|sharepoint|notion|feishu/.test(id) ? 'web'
      : /legal|pii|medical|quarantine/.test(id) ? 'privacy'
        : /code/.test(id) ? 'code' : /structured/.test(id) ? 'data' : 'text'
  return { group, kind, name: NAMES[id] || profile.name }
}

// These are presentation labels for existing pipeline fields, not defaults.
const FIELDS: Record<string, [string, string, string?]> = {
  governance_enabled: ['启用治理清洗', '对解析后的文档应用治理规则'],
  governance_remove_toc_lines: ['移除目录行', '移除目录标题与目录条目'],
  governance_remove_noise_lines: ['清理噪声行', '清理孤立噪声行'],
  governance_unwrap_lines: ['合并异常换行', '合并段内异常断行'],
  governance_remove_common_lines: ['去重复页眉页脚', '移除跨页重复页眉页脚'],
  governance_normalize_tables: ['规范 Markdown 表格', '统一 Markdown 表格格式'],
  governance_max_blank_lines: ['连续空行上限', '限制段落之间的连续空行', '行'],
  governance_remove_boilerplate: ['移除网页样板', '清理网页导航与页脚等样板内容'],
  governance_normalize_urls: ['规范链接', '统一链接格式'],
  governance_normalize_urls_strip_tracking: ['移除跟踪参数', '清除链接中的跟踪参数'],
  governance_drop_duplicate_paragraphs: ['移除重复段落', '清理重复出现的正文段落'],
  governance_drop_duplicate_paragraphs_min_occurrences: ['重复段落次数下限', '达到该次数后识别为重复', '次'],
  governance_drop_duplicate_paragraphs_min_chars: ['重复段落最短长度', '跳过较短的段落', '字符'],
  governance_drop_duplicate_paragraphs_max_chars: ['重复段落最长长度', '跳过超过长度上限的段落', '字符'],
  governance_pii_anonymize: ['个人信息脱敏', '处理邮箱、电话等个人信息'],
  governance_pii_mode: ['个人信息处理方式', '选择遮盖或替换的方式'],
  governance_pii_mask: ['个人信息替换文本', '替代检测到的个人信息'],
  governance_pii_max_hits: ['个人信息命中上限', '限制个人信息检测的命中数量', '处'],
  governance_secrets_redact: ['密钥脱敏', '处理 Token 与密钥等敏感内容'],
  governance_secrets_mode: ['密钥处理方式', '选择遮盖或替换的方式'],
  governance_secrets_mask: ['密钥替换文本', '替代检测到的密钥'],
  governance_secrets_max_hits: ['密钥命中上限', '限制密钥检测的命中数量', '处'],
  governance_strip_code_line_numbers: ['移除代码行号', '保留代码内容与缩进'],
  governance_trim_references: ['裁剪参考文献', '清理文末参考文献部分'],
  governance_rule_packs: ['规则包', '应用选定的清洗规则包'],
  governance_regex_rules: ['正则规则', '按表达式执行文本替换'],
  governance_remove_images: ['图片处理', '控制图片标记的保留方式'],
  governance_extract_frontmatter: ['提取文档元信息', '从 Frontmatter 中提取文档属性'],
  governance_strip_frontmatter: ['移除文档元信息', '清理正文开头的 Frontmatter'],
  governance_detect_language: ['识别文档语言', '根据文档内容检测语言'],
  governance_language_min_chars: ['语言识别最短长度', '内容达到该长度后检测', '字符'],
  governance_extract_keywords: ['提取关键词', '从文档中提取关键词'],
  governance_keywords_provider: ['关键词提取方式', '选择关键词提取器'],
  governance_keywords_top_k: ['关键词数量', '限制返回的关键词数量', '个'],
  governance_keywords_max_chars: ['关键词处理长度', '限制用于提取关键词的文本长度', '字符'],
  governance_noise_ratio_threshold: ['噪声比例阈值', '按噪声占比判断异常行'],
  governance_common_lines_min_docs: ['重复行最少文档数', '达到该数量后识别重复行', '份'],
  governance_common_lines_min_ratio: ['重复行比例阈值', '按重复行占比识别通用内容'],
  governance_html_xpath: ['网页正文路径', '使用 XPath 提取网页正文'],
  governance_drop_outline_only: ['过滤目录型内容', '过滤只有目录或标题的文档'],
  governance_drop_outline_min_content_chars: ['目录过滤最短正文', '保留正文长度的判断依据', '字符'],
  governance_drop_outline_max_heading_ratio: ['标题占比上限', '判断目录型文档的标题占比'],
  governance_drop_low_density: ['过滤低密度内容', '过滤有效信息过少的文档'],
  governance_drop_low_density_threshold: ['内容密度阈值', '有效内容的最低占比'],
  governance_quarantine_on_drop: ['过滤后进入隔离队列', '保留被过滤的文档以便复核'],
  parse_fallback_enabled: ['解析兜底', '解析失败或内容不足时尝试其他方式'],
  parse_fallback_max_retries: ['兜底重试上限', '限制解析兜底的重试次数', '次'],
  parse_fallback_min_content_chars: ['解析最短内容', '触发解析兜底的内容长度', '字符'],
}

export function profileField(key: string) {
  const field = FIELDS[key]
  return { label: field?.[0] || key, purpose: field?.[1] || '自定义管线参数', unit: field?.[2] || '' }
}

const RULE_PACK_NAMES: Record<string, string> = {
  ai_chat_export_noise: 'AI 对话导出噪声',
  cn_finance_report_artifacts: '金融报告噪声',
  cn_gov_redhead_artifacts: '政府公文尾部',
  cn_medical_record_artifacts: '医疗记录表头',
  confluence_jira_noise: 'Confluence / Jira 残留',
  email_disclaimer: '邮件免责声明',
  feishu_lark_noise: '飞书 / Lark 导出',
  markdown_export_noise: 'Markdown 导出噪声',
  notion_export_noise: 'Notion 导出噪声',
  pdf_header_footer_cn: '中文 PDF 页眉页脚',
  pdf_watermark: 'PDF 水印',
  web_cookie_banners: '网页 Cookie 横幅',
  web_navigation: '网页导航菜单',
  wechat_mp_noise: '微信公众号噪声',
}

export function profileValue(value: unknown, field?: string): string {
  if (value === null || value === undefined) return '沿用默认'
  if (typeof value === 'boolean') return value ? '启用' : '关闭'
  if (typeof value === 'string') {
    const names: Record<string, string> = field === 'governance_remove_images' ? { none: '保留全部图片', all: '移除全部图片', decorative: '移除装饰图片' }
      : field === 'governance_pii_mode' || field === 'governance_secrets_mode' ? { mask: '遮盖', hash: '哈希替换' }
        : field === 'governance_keywords_provider' ? { auto: '自动' } : {}
    return names[value] || value || '空文本'
  }
  if (Array.isArray(value)) return value.length ? value.map(item => typeof item === 'string' ? field === 'governance_rule_packs' ? RULE_PACK_NAMES[item] || item : item : JSON.stringify(item)).join('、') : '未配置'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
