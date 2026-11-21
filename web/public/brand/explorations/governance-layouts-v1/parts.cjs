const fs = require('node:fs')
const path = require('node:path')
const facts = require('./facts.json')
const root = path.resolve(__dirname, '../../../../..')
const selected = facts.files.find(file => file.id === facts.selectedId)
const stats = Object.fromEntries(['pending','running','review','done'].map(status => [status,facts.files.filter(file => file.status===status).length]))
const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')
function icon(name, className='') {
  const aliases={graph:'knowledge-graph',evaluations:'evaluation',audit:'audit-log',loader:'loader2',more:'more-horizontal',word:'file-type',excel:'file-spreadsheet',markdown:'file-markdown',users:'members','group-management':'groups',phone:'hash','file-text':'file'}
  const source=fs.readFileSync(path.join(root,'web/public/icons/ragvia',(aliases[name]||name)+'.svg'),'utf8')
  return source.replace(/<\?xml[^>]*>/g,'').replace(/<svg\b/,'<svg aria-hidden="true" class="icon '+esc(className)+'"')
}
const btn=(label,name='',cls='')=>'<button type="button" class="btn '+cls+'"'+(!label?' aria-label="更多操作"':'')+'>'+(name?icon(name):'')+esc(label)+'</button>'
const select=(label,name='',cls='')=>'<div class="select '+cls+'">'+(name?icon(name):'')+'<span>'+esc(label)+'</span>'+icon('chevron-down')+'</div>'
const search=(label='搜索文档',cls='')=>'<div class="search '+cls+'">'+icon('search')+'<span>'+esc(label)+'</span></div>'
const fileIcon=file=>icon(({pdf:'file-pdf',docx:'file-type',xlsx:'file-spreadsheet',md:'file-markdown',txt:'file-text'})[file.kind]||'file-type','file-'+file.kind)
const statusMeta={pending:['待治理','clock'],running:['清洗中','loader'],review:['待核对','alert-circle'],done:['已完成','check-circle']}
function state(file) { const [label,name]=statusMeta[file.status];return '<span class="state '+file.status+'">'+icon(name)+label+(file.status==='running'?' · '+file.progress+'%':'')+'</span>' }
const score=file=>file.score==null?'<span class="muted">—</span>':'<span class="quality-score '+(file.score>=80?'good':'warn')+'">'+file.score+'<small> / 100</small></span>'
const checkbox=(checked=false)=>'<span class="check-box '+(checked?'checked':'')+'">'+(checked?icon('check'):'')+'</span>'
function sidebar() {
  const group=(label,rows)=>'<div class="nav-group">'+label+icon('chevron-down')+'</div>'+rows.map(([label,name])=>'<div class="nav-item '+(label==='数据治理'?'active':'')+'">'+icon(name)+label+'</div>').join('')
  return '<aside class="sidebar"><div class="brand"><img src="../../ragvia/logo.svg" alt="Ragvia">'+icon('panel-left-close')+'</div><div class="sidebar-new">'+icon('plus')+'新对话</div><div class="sidebar-search">'+icon('search')+'搜索与命令<small>⌘K</small></div><nav class="nav-scroll">'+group('工作区',[['对话','conversation'],['问答历史','history']])+group('知识库管理',[['数据集','dataset'],['知识库','knowledge-base'],['隔离队列','quarantine'],['反馈质检','feedback']])+group('入库流程',[['入库管理','ingestion'],['文档解析','parsing'],['数据治理','data-governance'],['治理配置','rule-set'],['切块预览','chunking']])+group('分析工具',[['知识图谱','graph'],['RAG 评测','evaluations'],['数据报告','reports'],['提示词','prompts']])+group('系统',[['诊断','diagnostics'],['用量 / 配额','usage'],['审计日志','audit'],['成员权限','users'],['组管理','group-management'],['设置','settings']])+'</nav><div class="sidebar-bottom"><div class="profile"><span class="avatar">'+icon('user')+'</span><div><strong>开发模式</strong><small>本地开发环境</small></div><span class="profile-icons">'+icon('log-out')+icon('sun')+'</span></div><div class="appearance">'+icon('palette')+'界面外观<span>5 种风格</span></div><div class="service"><i></i>服务已就绪</div></div></aside>'
}
const header=(extra='',actions='')=>'<header class="page-header"><div class="heading">'+icon('data-governance')+'<h1>数据治理</h1></div>'+extra+'<div class="header-end">'+actions+btn('添加文档','upload')+'</div></header>'
const tabs=(active='quality')=>'<div class="tabs tool-tabs">'+[['quality','质量检测','scan-line'],['clean','数据清洗','wrench'],['annotate','数据标注','tag'],['classify','分类归档','folder-tree']].map(([id,label,name])=>'<span class="'+(id===active?'active':'')+'">'+icon(name)+label+'</span>').join('')+'</div>'
const issueRows=()=>facts.issues.map(issue=>'<div class="issue-row"><span class="issue-mark '+issue.tone+'">'+icon(issue.icon)+'</span><div><strong>'+esc(issue.title)+'</strong><p>'+esc(issue.location)+'</p></div><span class="issue-count '+issue.tone+'">'+issue.count+issue.unit+'</span>'+icon('chevron-right')+'</div>').join('')
function documentBody({clean=false,highlight=false,compact=false}={}) {
  const d=facts.detail
  return '<article class="document-body '+(compact?'compact':'')+'"><h2>'+esc(d.title)+'</h2><h3>'+esc(d.subtitle)+'</h3>'+d.paragraphs.map(p=>'<p>'+esc(p)+'</p>').join('')+(!clean?'<div class="duplicate-excerpt '+(highlight?'highlight':'')+'">'+(highlight?'<span class="inline-label">重复段落 · 2 处</span>':'')+'<p>'+esc(d.duplicate)+'</p></div>':'')+'<div class="table-caption">'+esc(d.tableTitle)+'</div><table><thead><tr>'+d.columns.map(v=>'<th>'+esc(v)+'</th>').join('')+'</tr></thead><tbody>'+d.rows.map(row=>'<tr>'+row.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table><h3>'+esc(d.nextHeading)+'</h3><p>'+esc(d.after)+'</p><div class="contact '+(highlight&&!clean?'sensitive':'')+'">'+esc(clean?d.maskedContact:d.contact)+'</div></article>'
}
const footer=(left='',right='')=>'<footer class="workspace-footer">'+left+'<div class="spacer"></div>'+right+'</footer>'
const frame=(title,css,content)=>'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1600,initial-scale=1"><title>'+esc(title)+' · Ragvia</title><link rel="stylesheet" href="./common.css"><link rel="stylesheet" href="./governance.css"><style>'+css+'</style></head><body><div class="app">'+sidebar()+'<main class="main">'+content+'</main></div></body></html>'
const write=(name,title,css,content)=>fs.writeFileSync(path.join(__dirname,name+'.html'),frame(title,css,content))
module.exports={facts,selected,stats,esc,icon,btn,select,search,fileIcon,state,score,checkbox,sidebar,header,tabs,issueRows,documentBody,footer,frame,write}
