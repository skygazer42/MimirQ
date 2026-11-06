const fs = require('node:fs')
const path = require('node:path')
const facts = require('./facts.json')
const root = path.resolve(__dirname, '../../../../..')
const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
function icon(name, className = '') {
  const aliases = { 'message-square': 'conversation', 'external-link': 'arrow-up-right', trash: 'trash2', sliders: 'settings2' }
  const filePath = path.join(root, 'web/public/icons/ragvia', (aliases[name] || name) + '.svg')
  const source = fs.readFileSync(filePath, 'utf8')
  return source.replace(/<\?xml[^>]*>/g, '').replace(/<svg\b/, '<svg aria-hidden="true" class="icon ' + esc(className) + '"')
}
function file(doc) {
  const names = { pdf: 'file-pdf', word: 'file-type', md: 'file-markdown', sheet: 'file-spreadsheet', code: 'file-code', json: 'file-json', zip: 'file-archive', text: 'file' }
  return `<span class="file-name">${icon(names[doc.kind] || 'file', 'file-' + doc.kind)}<span>${esc(doc.name)}</span></span>`
}
const button = (label, name = '', cls = '') => `<button type="button" class="btn ${cls}">${name ? icon(name) : ''}${esc(label)}</button>`
const select = (label, name = '', cls = '') => `<div class="select ${cls}">${name ? icon(name) : ''}<span>${esc(label)}</span>${icon('chevron-down')}</div>`
const status = (label = '待提交', cls = '') => `<span class="status ${cls}">${esc(label)}</span>`
function sourceTabs(cls = '') {
  return `<div class="source-tabs ${cls}">${facts.sources.map((source, index) => `<div class="source-tab ${index === 0 ? 'active' : ''}">${icon(source.icon)}${esc(source.label)}</div>`).join('')}</div>`
}
function modes(cls = '') {
  return `<div class="mode-options ${cls}">${facts.modes.map(mode => `<div class="mode-option ${mode.value === facts.executionMode ? 'selected' : ''}"><span class="radio" aria-hidden="true"></span><div><strong>${esc(mode.label)}</strong><p>${esc(mode.description)}</p></div></div>`).join('')}</div>`
}
function sidebar() {
  const group = (name, rows) => `<div class="nav-group">${name}${icon('chevron-down')}</div>` + rows.map(([label, name]) => `<div class="nav-item ${label === '入库管理' ? 'active' : ''}">${icon(name)}${label}</div>`).join('')
  return `<aside class="sidebar"><div class="brand"><img src="../../ragvia/logo.svg" alt="Ragvia">${icon('panel-left-close')}</div><div class="sidebar-new">${icon('plus')}新对话</div><div class="sidebar-search">${icon('search')}搜索与命令<small>⌘K</small></div>${group('工作区', [['对话', 'conversation'], ['问答历史', 'history']])}${group('知识库管理', [['数据集', 'dataset'], ['知识库', 'knowledge-base'], ['隔离队列', 'quarantine'], ['反馈质检', 'message-square']])}${group('入库流程', [['入库管理', 'ingestion'], ['文档解析', 'parsing'], ['数据治理', 'data-governance'], ['治理配置', 'rule-set'], ['切块预览', 'chunking']])}<div class="sidebar-bottom"><div class="profile"><span class="avatar">${icon('user')}</span><div><strong>开发模式</strong><small>本地开发环境</small></div><span class="profile-icons">${icon('log-out')}${icon('sun')}</span></div><div class="appearance">${icon('palette')}界面外观<span>5 种风格</span></div><div class="service"><i></i>本地开发环境</div></div></aside>`
}
function header() {
  return `<header class="page-header"><div class="heading">${icon('ingestion')}<h1>入库管理</h1></div><div class="view-tabs"><span class="active">入库操作</span><span>执行监控</span></div><div class="header-end">${button('查看文档', 'arrow-up-right', 'quiet')}</div></header>`
}
function submit(cls = '') {
  return `<footer class="submit ${cls}"><div class="submit-summary"><strong>${facts.documents.length} 个文件<span class="divider-dot">·</span>${facts.totalSize}</strong><span>目标：${facts.dataset}<span class="divider-dot">·</span>登记 → 解析</span></div><div class="submit-actions">${button('清空队列', '', 'quiet')}${button(facts.primaryAction, 'arrow-right', 'solid')}</div></footer>`
}
function frame(title, css, content) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1600,initial-scale=1"><title>${esc(title)} · Ragvia</title><link rel="stylesheet" href="./common.css"><style>${css}</style></head><body><div class="app">${sidebar()}<main class="main">${content}</main></div></body></html>`
}
const write = (name, title, css, content) => fs.writeFileSync(path.join(__dirname, name + '.html'), frame(title, css, content))
module.exports = { facts, esc, icon, file, button, select, status, sourceTabs, modes, header, submit, frame, write }
