const fs = require('node:fs')
const path = require('node:path')
const facts = require('./facts.json')
const root = path.resolve(__dirname, '../../../../..')
const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')
const selected = facts.files.find(file => file.id === facts.selectedId)
const stats = Object.fromEntries(['parsed','parsing','pending','error'].map(status => [status, facts.files.filter(file => file.status === status).length]))
function icon(name, className = '') {
  const aliases = { external:'arrow-up-right', more:'more-horizontal', graph:'knowledge-graph', evaluations:'evaluation', audit:'audit-log', word:'file-type', excel:'file-spreadsheet', powerpoint:'file-stack', markdown:'file-markdown', loader:'loader2' }
  const source = fs.readFileSync(path.join(root,'web/public/icons/ragvia',(aliases[name] || name)+'.svg'),'utf8')
  return source.replace(/<\?xml[^>]*>/g,'').replace(/<svg\b/,'<svg aria-hidden="true" class="icon '+esc(className)+'"')
}
const btn = (label, name = '', cls = '') => '<button type="button" class="btn '+cls+'">'+(name ? icon(name) : '')+esc(label)+'</button>'
const select = (label, name = '', cls = '') => '<div class="select '+cls+'">'+(name ? icon(name) : '')+'<span>'+esc(label)+'</span>'+icon('chevron-down')+'</div>'
const search = (label = '搜索文件', cls = '') => '<div class="search '+cls+'">'+icon('search')+'<span>'+esc(label)+'</span></div>'
const fileIcon = file => icon(({pdf:'file-pdf',docx:'file-type',xlsx:'file-spreadsheet',pptx:'file-stack',md:'file-markdown'})[file.kind] || 'file-type', 'file-'+file.kind)
function state(file) {
  const labels = {parsed:'已解析',parsing:'解析中',pending:'待解析',error:'解析失败'}
  return '<span class="state '+file.status+'">'+icon(file.status === 'parsed' ? 'check-circle' : file.status === 'error' ? 'alert-circle' : file.status === 'parsing' ? 'loader' : 'clock')+labels[file.status]+(file.status === 'parsing' ? ' · '+file.progress+'%' : '')+'</span>'
}
const review = () => '<span class="review-label">'+icon('alert-circle')+'1 处需核对</span>'
function sidebar() {
  const group = (name, rows) => '<div class="nav-group">'+name+icon('chevron-down')+'</div>'+rows.map(([label,name])=>'<div class="nav-item '+(label === '文档解析' ? 'active' : '')+'">'+icon(name)+label+'</div>').join('')
  return '<aside class="sidebar"><div class="brand"><img src="../../ragvia/logo.svg" alt="Ragvia">'+icon('panel-left-close')+'</div><div class="sidebar-new">'+icon('plus')+'新对话</div><div class="sidebar-search">'+icon('search')+'搜索与命令<small>⌘K</small></div><nav class="nav-scroll">'+group('工作区',[['对话','conversation'],['问答历史','history']])+group('知识库管理',[['数据集','dataset'],['知识库','knowledge-base'],['隔离队列','quarantine'],['反馈质检','feedback']])+group('入库流程',[['入库管理','ingestion'],['文档解析','parsing'],['数据治理','data-governance'],['治理配置','rule-set'],['切块预览','chunking']])+group('分析工具',[['知识图谱','graph'],['RAG 评测','evaluations'],['数据报告','reports'],['提示词','prompts']])+group('系统',[['诊断','diagnostics'],['用量 / 配额','usage'],['审计日志','audit'],['设置','settings']])+'</nav><div class="sidebar-bottom"><div class="profile"><span class="avatar">'+icon('user')+'</span><div><strong>开发模式</strong><small>本地开发环境</small></div><span class="profile-icons">'+icon('log-out')+icon('sun')+'</span></div><div class="appearance">'+icon('palette')+'界面外观<span>5 种风格</span></div><div class="service"><i></i>服务已就绪</div></div></aside>'
}
const header = (extra = '', actions = '') => '<header class="page-header"><div class="heading">'+icon('parsing')+'<h1>文档解析</h1></div>'+extra+'<div class="header-end">'+actions+btn('上传文件','upload','solid')+'</div></header>'
function markdown(cls = '') {
  const d = facts.detail
  return '<article class="markdown '+cls+'"><h2>'+esc(d.title)+'</h2><h3>'+esc(d.subtitle)+'</h3>'+d.paragraphs.map(p=>'<p>'+esc(p)+'</p>').join('')+'<div class="md-table-caption">'+esc(d.tableTitle)+'</div><table><thead><tr>'+d.columns.map(v=>'<th>'+esc(v)+'</th>').join('')+'</tr></thead><tbody>'+d.rows.map(row=>'<tr>'+row.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table><h3>'+esc(d.nextHeading)+'</h3><p>'+esc(d.after)+'</p><blockquote>'+esc(d.note)+'</blockquote></article>'
}
function paper(cls = '') {
  const d = facts.detail
  return '<article class="paper '+cls+'"><div class="paper-running">设备维护手册<span>使用与维护</span></div><h2>'+esc(d.title)+'</h2><h3>'+esc(d.subtitle)+'</h3>'+d.paragraphs.map(p=>'<p>'+esc(p)+'</p>').join('')+'<div class="paper-caption">'+esc(d.tableTitle)+'</div><table><thead><tr>'+d.columns.map(v=>'<th>'+esc(v)+'</th>').join('')+'</tr></thead><tbody>'+d.rows.map(row=>'<tr>'+row.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table><h3>'+esc(d.nextHeading)+'</h3><p>'+esc(d.after)+'</p><div class="paper-note">'+esc(d.note)+'</div><div class="paper-page">3</div></article>'
}
const frame = (title,css,content) => '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1600,initial-scale=1"><title>'+esc(title)+' · Ragvia</title><link rel="stylesheet" href="./common.css"><style>'+css+'</style></head><body><div class="app">'+sidebar()+'<main class="main">'+content+'</main></div></body></html>'
const write = (name,title,css,content) => fs.writeFileSync(path.join(__dirname,name+'.html'),frame(title,css,content))
module.exports = { facts, selected, stats, esc, icon, btn, select, search, fileIcon, state, review, header, markdown, paper, frame, write }
