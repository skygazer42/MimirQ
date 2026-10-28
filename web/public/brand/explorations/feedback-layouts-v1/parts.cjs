const fs = require('node:fs')
const path = require('node:path')
const facts = require('./facts.json')
const root = path.resolve(__dirname, '../../../../..')
const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
const stats = {
  total: facts.feedback.length,
  pending: facts.feedback.filter(item => !item.archived).length,
  archived: facts.feedback.filter(item => item.archived).length,
  negative: facts.feedback.filter(item => item.rating <= 2).length,
  neutral: facts.feedback.filter(item => item.rating === 3).length,
  positive: facts.feedback.filter(item => item.rating >= 4).length,
  priority: facts.feedback.filter(item => !item.archived && item.rating <= 2).length,
  average: (facts.feedback.reduce((sum, item) => sum + item.rating, 0) / facts.feedback.length).toFixed(1),
}
function icon(name, className = '') {
  const aliases = { archive: 'archive', external: 'arrow-up-right', more: 'more-horizontal', check: 'check', feedback: 'feedback', compare: 'layout', graph: 'knowledge-graph', evaluations: 'evaluation', audit: 'audit-log' }
  const source = fs.readFileSync(path.join(root, 'web/public/icons/ragvia', (aliases[name] || name) + '.svg'), 'utf8')
  return source.replace(/<\?xml[^>]*>/g, '').replace(/<svg\b/, '<svg aria-hidden="true" class="icon ' + esc(className) + '"')
}
const btn = (label, name = '', cls = '') => '<button type="button" class="btn ' + cls + '">' + (name ? icon(name) : '') + esc(label) + '</button>'
const select = (label, name = '', cls = '') => '<div class="select ' + cls + '">' + (name ? icon(name) : '') + '<span>' + esc(label) + '</span>' + icon('chevron-down') + '</div>'
const search = (label = '搜索问题、反馈或用户', cls = '') => '<div class="search ' + cls + '">' + icon('search') + '<span>' + esc(label) + '</span></div>'
const tone = item => item.rating <= 2 ? 'negative' : item.rating >= 4 ? 'positive' : 'neutral'
const kindLabel = item => item.rating <= 2 ? '点踩' : item.rating >= 4 ? '点赞' : '中立'
const rating = item => '<span class="rating ' + tone(item) + '">' + icon(item.rating <= 2 ? 'thumbs-down' : item.rating >= 4 ? 'thumbs-up' : 'minus') + '<b>' + item.rating + '</b><span>/ 5</span></span>'
const state = item => '<span class="state ' + (item.archived ? 'archived' : item.rating <= 2 ? 'priority' : 'pending') + '"><i></i>' + (item.archived ? '已归档' : item.rating <= 2 ? '优先分析' : '待分析') + '</span>'
function tabs(active = '全部') {
  return '<div class="tabs">' + [['全部', stats.total], ['待分析', stats.pending], ['高优先级', stats.priority], ['已归档', stats.archived]].map(([label, count]) => '<span class="' + (label === active ? 'active' : '') + '">' + label + '<em>' + count + '</em></span>').join('') + '</div>'
}
function sidebar() {
  const group = (name, rows) => '<div class="nav-group">' + name + icon('chevron-down') + '</div>' + rows.map(([label, name]) => '<div class="nav-item ' + (label === '反馈质检' ? 'active' : '') + '">' + icon(name) + label + '</div>').join('')
  return '<aside class="sidebar"><div class="brand"><img src="../../ragvia/logo.svg" alt="Ragvia">' + icon('panel-left-close') + '</div><div class="sidebar-new">' + icon('plus') + '新对话</div><div class="sidebar-search">' + icon('search') + '搜索与命令<small>⌘K</small></div><nav class="nav-scroll">' + group('工作区', [['对话', 'conversation'], ['问答历史', 'history']]) + group('知识库管理', [['数据集', 'dataset'], ['知识库', 'knowledge-base'], ['隔离队列', 'quarantine'], ['反馈质检', 'feedback']]) + group('入库流程', [['入库管理', 'ingestion'], ['文档解析', 'parsing'], ['数据治理', 'data-governance'], ['治理配置', 'rule-set'], ['切块预览', 'chunking']]) + group('分析工具', [['知识图谱', 'graph'], ['RAG 评测', 'evaluations'], ['数据报告', 'reports'], ['提示词', 'prompts']]) + group('系统', [['诊断', 'diagnostics'], ['用量 / 配额', 'usage'], ['审计日志', 'audit'], ['设置', 'settings']]) + '</nav><div class="sidebar-bottom"><div class="profile"><span class="avatar">' + icon('user') + '</span><div><strong>开发模式</strong><small>本地开发环境</small></div><span class="profile-icons">' + icon('log-out') + icon('sun') + '</span></div><div class="appearance">' + icon('palette') + '界面外观<span>5 种风格</span></div><div class="service"><i></i>服务已就绪</div></div></aside>'
}
function header(extra = '') {
  return '<header class="page-header"><div class="heading">' + icon('feedback') + '<h1>反馈质检</h1></div>' + extra + '<div class="header-end">' + btn('反哺候选', 'workflow', 'quiet') + '<span class="header-divider"></span>' + select(facts.range, 'calendar') + btn('刷新', 'refresh-cw', 'quiet') + '</div></header>'
}
const pagination = (label = '共 12 条反馈') => '<footer class="pagination"><span>' + label + '</span><div><span class="muted">20 条 / 页</span>' + icon('chevron-down') + '<span class="page-prev">' + icon('chevron-left') + '</span><b>1</b><span class="muted">/ 1</span><span class="page-next">' + icon('chevron-right') + '</span></div></footer>'
const citations = () => facts.detail.citations.map((citation, index) => '<div class="citation"><span class="citation-num">' + (index + 1) + '</span>' + icon(citation.kind === 'md' ? 'file-markdown' : 'file-pdf', 'file-' + citation.kind) + '<div><strong>' + esc(citation.name) + '</strong><span>' + esc(citation.location) + '</span></div>' + icon('arrow-up-right') + '</div>').join('')
function frame(title, css, content) {
  return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1600,initial-scale=1"><title>' + esc(title) + ' · Ragvia</title><link rel="stylesheet" href="./common.css"><style>' + css + '</style></head><body><div class="app">' + sidebar() + '<main class="main">' + content + '</main></div></body></html>'
}
const write = (name, title, css, content) => fs.writeFileSync(path.join(__dirname, name + '.html'), frame(title, css, content))
module.exports = { facts, stats, esc, icon, btn, select, search, tone, kindLabel, rating, state, tabs, sidebar, header, pagination, citations, frame, write }
