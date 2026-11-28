const { facts, stats, esc, icon, select, search, rating, header, write } = require('./parts.cjs')

const excerpts = {
  'FB-0128': '没有具体的配置示例',
  'FB-0127': '没有说明 OCR 的适用范围',
  'FB-0126': '成员角色和数据集授权之间的区别',
  'FB-0125': '回答没有找到对应的版本',
  'FB-0124': '希望能说明回答的适用范围',
  'FB-0123': '没有说明重试间隔和错误码',
  'FB-0122': '结合内部文档的例子也容易理解',
  'FB-0121': '还需要核对文档版本',
  'FB-0120': '给出的排查顺序和页面入口都能对应上',
  'FB-0119': '实际引用的是旧版制度',
  'FB-0118': '文件格式和限制也说明了',
  'FB-0117': '已补充归档和访问权限的区别',
}

const groups = [
  { name: '低分待分析', label: '1–2 分 · 未归档', icon: 'thumbs-down', tone: 'negative', filter: item => !item.archived && item.rating <= 2 },
  { name: '中立待确认', label: '3 分 · 未归档', icon: 'minus', tone: 'neutral', filter: item => !item.archived && item.rating === 3 },
  { name: '正向反馈', label: '4–5 分 · 未归档', icon: 'thumbs-up', tone: 'positive', filter: item => !item.archived && item.rating >= 4 },
  { name: '已归档', label: '已归档的全部反馈', icon: 'archive', tone: 'neutral', filter: item => item.archived },
]

function feedbackCard(item) {
  return `<article class="board-item" data-id="${esc(item.id)}">
    <h3 title="${esc(item.question)}">${esc(item.question)}</h3>
    <p class="item-reason" title="${esc(item.reason)}">${esc(excerpts[item.id])}</p>
    <div class="item-meta"><span>${esc(item.source)}</span><time>${esc(item.time)}</time></div>
    <div class="item-actions">${rating(item)}<span class="action-space"></span><button class="inspect" type="button">查看问答${icon('arrow-up-right')}</button>${item.archived ? '<span class="archive-label">已归档</span>' : `<button class="archive-action" type="button">${icon('archive')}归档</button>`}</div>
  </article>`
}

const board = groups.map(group => {
  const items = facts.feedback.filter(group.filter)
  return `<section class="board-column">
    <header class="column-heading"><div><span class="column-title">${icon(group.icon, group.tone)}<h2>${esc(group.name)}</h2><span class="column-count">${items.length}</span></span><p>${esc(group.label)}</p></div><button type="button" class="column-menu" aria-label="${esc(group.name)}的更多操作">${icon('more')}</button></header>
    <div class="column-items">${items.map(feedbackCard).join('')}</div>
  </section>`
}).join('')

const css = `
.board-toolbar{height:64px;flex:none;display:flex;align-items:center;gap:10px;padding:0 28px;border-bottom:1px solid var(--line);background:var(--surface)}
.board-toolbar .search{width:294px;background:var(--surface)}
.board-toolbar .select{width:136px}
.board-toolbar .issue-filter{width:148px}
.toolbar-total{font-size:12px;color:var(--muted);margin-left:auto;white-space:nowrap}
.toolbar-total strong{font-weight:550;color:var(--ink);font-variant-numeric:tabular-nums}
.view-separator{height:18px;width:1px;background:var(--line);margin:0 6px}
.view-mode{display:flex;align-items:center;gap:7px;height:32px;padding:0 9px;background:var(--selected);border-radius:4px;font-size:12px;white-space:nowrap}
.view-mode .icon{width:15px;height:15px}
.feedback-board{flex:1;min-height:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;padding:20px 18px 20px;background:var(--fog)}
.board-column{min-width:0;padding:0 10px;position:relative}
.board-column+.board-column{border-left:1px solid #E2E6E9}
.column-heading{height:54px;display:flex;align-items:flex-start;justify-content:space-between;padding:0 2px}
.column-title{display:flex;align-items:center;gap:8px;line-height:22px}
.column-title>.icon{width:16px;height:16px}
.column-title h2{font-size:14px;font-weight:600}
.column-count{font-size:12px;line-height:20px;min-width:21px;display:inline-flex;justify-content:center;background:#E8ECEF;color:var(--muted);border-radius:3px;margin-left:1px;font-variant-numeric:tabular-nums}
.column-heading p{font-size:12px;color:var(--muted);line-height:18px;margin-top:4px;margin-left:24px}
.column-menu{height:24px;width:24px;display:grid;place-items:center;color:var(--muted);margin-right:-3px}
.column-menu .icon{height:16px;width:16px}
.column-items{display:flex;flex-direction:column;gap:8px}
.board-item{height:136px;flex:none;min-width:0;padding:10px 12px;background:var(--surface);border:1px solid var(--line);border-radius:5px}
.board-item h3{font-size:13px;line-height:19px;font-weight:550;height:38px;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.item-reason{font-size:13px;line-height:18px;color:var(--muted);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item-meta{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;line-height:18px;color:var(--muted);margin-top:4px;white-space:nowrap}
.item-meta time{font-variant-numeric:tabular-nums}
.item-actions{display:flex;align-items:center;gap:11px;height:23px;margin-top:6px;white-space:nowrap}
.item-actions .rating{font-size:12px;gap:4px}
.item-actions .rating>.icon{height:14px;width:14px}
.item-actions .rating>span{font-size:12px}
.action-space{flex:1}
.inspect,.archive-action{display:inline-flex;align-items:center;gap:4px;font-size:12px;line-height:22px;color:var(--ink)}
.inspect .icon{height:12px;width:12px}
.archive-action{color:var(--muted)}
.archive-action .icon{height:13px;width:13px}
.archive-label{color:var(--muted);font-size:12px;line-height:22px}
.board-footer{height:44px;flex:none;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-top:1px solid var(--line);background:var(--fog);font-size:12px;color:var(--muted)}
.board-footer>span:last-child{display:flex;align-items:center;gap:8px}
.board-footer .icon{width:14px;height:14px}
`

const content = `${header()}
<div class="board-toolbar">${search()}${select('全部来源')}${select('全部问题类型', '', 'issue-filter')}<span class="toolbar-total">全部 <strong>${stats.total}</strong> 条<span class="total-dot"> · </span>待分析 <strong>${stats.pending}</strong> 条</span><span class="view-separator"></span><span class="view-mode">${icon('compare')}分类看板</span></div>
<div class="feedback-board">${board}</div>
<footer class="board-footer"><span>共 ${stats.total} 条反馈 · ${esc(facts.rangeLabel)}</span><span>${icon('compare')}按评分与归档状态分组</span></footer>`

write('d-board', 'D · 分类看板', css, content)
