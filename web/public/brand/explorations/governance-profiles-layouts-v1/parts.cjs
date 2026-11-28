const fs = require('node:fs')
const path = require('node:path')
const shared = require('../governance-layouts-v1/parts.cjs')
const facts = require('./facts.json')
const esc = shared.esc
const icon = (name, className='') => {
  try { return shared.icon(name, className) }
  catch { return shared.icon('rule-set', className) }
}
const btn = (label, name='', cls='') => '<button type="button" class="btn '+cls+'"'+(!label?' aria-label="'+esc(({'copy':'复制配置','more-horizontal':'更多操作','chevron-left':'上一页','chevron-right':'下一页','x':'关闭详情'})[name]||name)+'"':'')+'>'+(name?icon(name):'')+esc(label)+'</button>'
const { select, search, checkbox } = shared
const groupKeys = {
  '通用文档': ['kb_default','pdf_text','policy_manual_pdf','pdf_scanned_ocr','wiki_longform'],
  '网页与协作': ['html_web','html_xpath_main','chat_exports','confluence_enterprise','sharepoint_o365','notion_database','feishu_lark_doc'],
  '代码与结构': ['code_repo','structured_data','metadata_enrich'],
  '合规与行业': ['legal_compliance','quality_gate_quarantine','pii_secrets_quarantine','cn_a_share_annual_report','cn_prospectus','bank_compliance_report','insurance_policy_pdf','medical_emr','government_redhead','china_law_regulation','court_judgment'],
}
const displayNames = {
  kb_default:'知识库默认',html_web:'网页 HTML',pdf_text:'PDF 文本版',policy_manual_pdf:'制度与手册',pdf_scanned_ocr:'扫描件与 OCR',legal_compliance:'合规脱敏',wiki_longform:'长文与 Wiki',code_repo:'代码仓库',structured_data:'结构化数据',chat_exports:'聊天记录',metadata_enrich:'元数据增强',quality_gate_quarantine:'质量门禁',pii_secrets_quarantine:'合规门禁',html_xpath_main:'网页正文提取',cn_a_share_annual_report:'A 股年报',cn_prospectus:'A 股招股书',bank_compliance_report:'金融合规报告',insurance_policy_pdf:'保险合同',medical_emr:'电子病历',government_redhead:'政府公文',china_law_regulation:'法规条例',court_judgment:'法院判决书',confluence_enterprise:'Confluence 导出',sharepoint_o365:'SharePoint 导出',notion_database:'Notion 导出',feishu_lark_doc:'飞书知识库',
}
const profileMeta = p => {
  const id=p.key.split(':')[1]
  const group=Object.entries(groupKeys).find(([,keys])=>keys.includes(id))?.[0]||'通用文档'
  const kind = /pdf|report|prospectus|policy|manual|government|law|judgment/.test(id)?'pdf':/html|confluence|sharepoint|notion|feishu/.test(id)?'web':/legal|pii|medical/.test(id)?'privacy':/code/.test(id)?'code':/structured/.test(id)?'data':'text'
  const meta={pdf:['file-pdf','file-pdf'],web:['globe','source'],privacy:['shield-check','privacy'],code:['braces','code'],data:['database','dataset'],text:['file-markdown','text']}
  return { ...p, id, group, shortName:displayNames[id]||p.name, kind, iconName:meta[kind][0], tone:meta[kind][1] }
}
const profiles=facts.profiles.map(profileMeta)
const selected=profiles.find(p=>p.key===facts.selectedKey)
const groupCounts=Object.fromEntries(Object.keys(groupKeys).map(key=>[key,profiles.filter(p=>p.group===key).length]))
const labels={
  governance_enabled:'启用治理清洗',governance_remove_toc_lines:'移除目录行',governance_remove_noise_lines:'清理噪声行',governance_unwrap_lines:'合并异常换行',governance_remove_common_lines:'去重复页眉页脚',governance_remove_boilerplate:'移除网页样板',governance_normalize_tables:'规范 Markdown 表格',governance_normalize_urls:'规范链接',governance_drop_duplicate_paragraphs:'移除重复段落',governance_pii_anonymize:'个人信息脱敏',governance_secrets_redact:'密钥脱敏',governance_strip_code_line_numbers:'移除代码行号',governance_trim_references:'裁剪参考文献',parse_fallback_enabled:'解析兜底',governance_max_blank_lines:'连续空行上限',governance_normalize_urls_strip_tracking:'移除跟踪参数',
}
const effectivePatch=p=>({...((p.payload.extends&&profiles.find(x=>x.key===p.payload.extends))?effectivePatch(profiles.find(x=>x.key===p.payload.extends)):{}),...p.payload.pipeline_patch})
const enabled=p=>Object.entries(effectivePatch(p)).filter(([key,v])=>v===true&&labels[key]&&key!=='governance_enabled')
const objectIcon=p=>'<span class="object-icon '+p.tone+'">'+icon(p.iconName)+'</span>'
const ruleTags=(p,max=3)=>enabled(p).slice(0,max).map(([key])=>'<span class="rule-tag">'+esc(labels[key])+'</span>').join('')
const builtin=()=>'<span class="builtin">'+icon('lock')+'内置</span>'
const formats=p=>p.payload.input_formats.map(fmt=>'<span class="format '+(fmt==='html'?'html':'')+'">'+(fmt==='html'?'HTML':'Markdown')+'</span>').join('')
function sidebar() {
  return shared.sidebar().replace('nav-item active','nav-item').replace('<div class="nav-item ">'+shared.icon('rule-set')+'治理配置','<div class="nav-item active">'+shared.icon('rule-set')+'治理配置')
}
const header=(description='管理可复用的文档清洗与脱敏规则')=>'<header class="page-header"><div class="page-heading">'+icon('rule-set')+'<div><h1>治理配置</h1><p>'+esc(description)+'</p></div></div><div class="header-end">'+btn('重复内容规则','hash','quiet')+'<span class="header-divider"></span>'+btn('导入','upload')+btn('新建配置','plus','solid')+'</div></header>'
const frame=(title,css,content)=>'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1600,initial-scale=1"><title>'+esc(title)+' · Ragvia</title><link rel="stylesheet" href="./common.css"><style>'+css+'</style></head><body><div class="app">'+sidebar()+'<main class="main">'+header()+content+'</main></div></body></html>'
const write=(name,title,css,content)=>fs.writeFileSync(path.join(__dirname,name+'.html'),frame(title,css,content))
module.exports={facts,profiles,selected,groupKeys,groupCounts,esc,icon,btn,select,search,checkbox,labels,effectivePatch,enabled,objectIcon,ruleTags,builtin,formats,frame,write}
