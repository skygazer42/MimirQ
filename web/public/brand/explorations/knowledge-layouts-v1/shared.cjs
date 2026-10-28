const fs = require('node:fs')
const path = require('node:path')
const facts = JSON.parse(fs.readFileSync(path.join(__dirname, 'facts.json'), 'utf8'))
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
const icon = (name, cls = '') => fs.readFileSync(path.resolve(__dirname, '../../../icons/ragvia', `${name}.svg`), 'utf8').trim().replace('<svg ', `<svg class="icon ${cls}" aria-hidden="true" `)
const fileIcon = (doc, cls = '') => icon({ pdf: 'file-pdf', md: 'file-markdown', xlsx: 'file-spreadsheet', docx: 'file' }[doc.type], `type-${doc.type} ${cls}`)
const stateConfig = {
  ready: { label: '已就绪', icon: 'check-circle' },
  processing: { label: '处理中', icon: 'loader2' },
  failed: { label: '失败', icon: 'alert-circle' },
  quarantined: { label: '已隔离', icon: 'lock' },
}
const state = doc => `<span class="state state-${doc.state}">${icon(stateConfig[doc.state].icon)}${stateConfig[doc.state].label}</span>`
const nav = () => fs.readFileSync(path.join(__dirname, 'nav.html'), 'utf8')
const html = ({ title, css, body }) => `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1600,initial-scale=1"><title>${escape(title)} · Ragvia</title><link rel="stylesheet" href="./common.css"><style>${css}</style></head><body><div class="app">${nav()}${body}</div></body></html>`
module.exports = { facts, escape, icon, fileIcon, state, stateConfig, html }
