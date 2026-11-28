const fs = require('node:fs')
const path = require('node:path')
const facts = require('./facts.json')
const root = path.resolve(__dirname, '../../../../..')
const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
function icon(name, className = '') {
  const aliases = { 'message-square': 'conversation', 'external-link': 'arrow-up-right' }
  const source = fs.readFileSync(path.join(root, 'web/public/icons/ragvia', (aliases[name] || name) + '.svg'), 'utf8')
  return source.replace(/<\?xml[^>]*>/g, '').replace(/<svg\b/, '<svg aria-hidden="true" class="icon ' + className + '"')
}
function file(doc) {
  const names = { pdf: 'file-pdf', md: 'file-markdown', sheet: 'file-spreadsheet', word: 'file-type', slides: 'document', text: 'document' }
  return `<span class="file-name">${icon(names[doc.kind] || 'document', 'file-' + doc.kind)}<span>${esc(doc.name)}</span></span>`
}
const risk = doc => `<span class="risk ${doc.risk}">${icon(doc.risk === 'high' ? 'alert-triangle' : 'shield-check')}${({ high: '高', medium: '中', low: '低' })[doc.risk]}</span>`
const review = doc => `<span class="status ${doc.review}">${doc.review === 'pending' ? '待复核' : '已复核'}</span>`
const btn = (text, name = '', kind = '') => `<button type="button" class="btn ${kind}">${name ? icon(name) : ''}${text}</button>`
const control = (label, name = '') => `<div class="control">${name ? icon(name) : ''}${label}${icon('chevron-down')}</div>`
const search = (placeholder = '搜索文档、规则或原因') => `<div class="search-control">${icon('search')}<span>${placeholder}</span></div>`
function sidebar() {
  const group = (name, rows) => `<div class="nav-group">${name}${icon('chevron-down')}</div>` + rows.map(([label, name]) => `<div class="nav-item ${label === '隔离队列' ? 'active' : ''}">${icon(name)}${label}</div>`).join('')
  return `<aside class="sidebar"><img class="sidebar-logo" src="../../ragvia/logo.svg" alt="Ragvia"><div class="sidebar-top">${icon('plus')}新对话</div><div class="sidebar-search">${icon('search')}搜索与命令<small>⌘K</small></div>${group('工作区', [['对话', 'message-square'], ['问答历史', 'history']])}${group('知识库管理', [['数据集', 'dataset'], ['知识库', 'knowledge-base'], ['隔离队列', 'quarantine'], ['反馈质检', 'message-square']])}${group('入库流程', [['入库管理', 'ingestion'], ['文档解析', 'parsing'], ['数据治理', 'data-governance'], ['治理配置', 'rule-set'], ['切块预览', 'chunking']])}<div class="sidebar-bottom"><div class="avatar">${icon('user')}</div><div><strong>开发模式</strong><small>本地开发环境</small></div></div></aside>`
}
function header(extra = '') {
  return `<header class="page-header"><div class="heading">${icon('quarantine')}<h1>隔离队列</h1></div>${extra}<div class="header-end"><span class="header-meta">自动刷新<span class="toggle"></span></span>${btn('同步', 'refresh-cw', 'quiet')}${btn('导出', 'download')}</div></header>`
}
const footer = () => `<footer class="footer"><span>共 12 份文档<span style="padding:0 10px">·</span>8 份待复核</span><div class="pagination">每页 20 条${btn('', 'chevron-left', 'quiet square')}<strong>1</strong>${btn('', 'chevron-right', 'quiet square')}</div></footer>`
function frame(title, styles, content) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1600,initial-scale=1"><title>${esc(title)} · Ragvia</title><link rel="stylesheet" href="./common.css"><style>${styles}</style></head><body><div class="app">${sidebar()}<main class="main">${content}</main></div></body></html>`
}
const write = (name, title, css, content) => fs.writeFileSync(path.join(__dirname, name + '.html'), frame(title, css, content))
module.exports = { facts, esc, icon, file, risk, review, btn, control, search, header, footer, frame, write }
