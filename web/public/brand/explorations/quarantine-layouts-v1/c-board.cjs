const { facts, esc, icon, file, risk, review, btn, control, search, header, footer, write } = require('./parts.cjs')

// C · 原因分组看板：用三个静态原因泳道，让同类文档在首屏直接比较。
const lanes = [
  { name: '敏感信息', icon: 'shield', description: '个人信息 · 疑似密钥' },
  { name: '内容质量', icon: 'align-left', description: '大纲文档 · 正文不足' },
  { name: '处理失败', icon: 'alert-circle', description: '文档解析 · 索引写入' },
]

function record(doc) {
  const selected = doc.id === facts.selectedId
  const previewLine = facts.preview.paragraphs[1].split('。')[0] + '。'
  const excerpt = selected
    ? `<p class="record-note record-excerpt"><span>原文</span>${esc(previewLine)}</p>`
    : `<p class="record-note">${esc(doc.note)}</p>`
  const action = '复核'
  return `<article class="record${selected ? ' is-selected' : ''}" aria-label="${esc(doc.name)}${selected ? '，已选中' : ''}">
    <div class="record-title">${file(doc)}${selected ? `<span class="selected-label">${icon('check')}已选中</span>` : ''}</div>
    <div class="record-reason"><span>${esc(doc.reason)}</span><span class="risk-label">${risk(doc)}<span>风险</span></span></div>
    <div class="record-meta"><span class="dataset-meta">${icon('dataset')}${esc(doc.dataset)}<span class="meta-dot">·</span>${esc(doc.size)}</span><time datetime="${facts.date}T${doc.time}:00+08:00">${esc(doc.time)}</time></div>
    ${excerpt}
    <div class="record-actions">${review(doc)}<div class="record-buttons"><button type="button" class="original-link">查看原文${icon('arrow-up-right')}</button>${btn(action, '', selected ? 'solid' : '')}</div></div>
  </article>`
}

const content = `${header()}
  <div class="filter-bar">
    ${search('搜索文档或隔离原因')}
    ${control('全部数据集', 'dataset')}
    ${control('全部风险', 'shield-check')}
    ${control('全部来源', 'filter')}
    <div class="filter-end">${icon('calendar')}<span>${facts.date}</span></div>
  </div>
  <div class="review-bar">
    <div class="board-tabs" role="tablist" aria-label="复核状态">
      <button type="button" class="board-tab" role="tab" aria-selected="false">待复核<span>${facts.summary.pending}</span></button>
      <button type="button" class="board-tab active" role="tab" aria-selected="true">全部<span>${facts.summary.total}</span></button>
      <button type="button" class="board-tab" role="tab" aria-selected="false">已复核<span>${facts.summary.reviewed}</span></button>
    </div>
    <div class="board-view">${icon('layout-grid')}<span>按原因分组</span><i></i>${icon('arrow-down')}<span>时间从近到远</span></div>
  </div>
  <section class="reason-board" aria-label="按隔离原因分组的文档">
    ${lanes.map(lane => {
      const docs = facts.documents.filter(doc => doc.group === lane.name)
      return `<section class="reason-lane" aria-label="${lane.name}">
        <header class="lane-heading"><div class="lane-name">${icon(lane.icon)}<h2>${lane.name}</h2><span class="lane-count">${docs.length}</span></div><p>${lane.description}</p></header>
        <div class="lane-records">${docs.map(record).join('')}</div>
      </section>`
    }).join('')}
  </section>
  ${footer()}`

const css = `
.heading>.icon{color:var(--ink)}
.page-header{padding:0 28px;background:var(--fog)}
.filter-bar{height:60px;flex:none;display:flex;align-items:center;gap:10px;padding:0 28px;background:#fff}
.filter-bar .search-control{width:272px}
.filter-bar .control{background:#fff}
.filter-end{display:flex;align-items:center;gap:7px;margin-left:auto;color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.filter-end .icon{width:14px;height:14px}
.review-bar{height:46px;flex:none;display:flex;align-items:stretch;justify-content:space-between;padding:0 28px;border-bottom:1px solid var(--line);background:#fff}
.board-tabs{display:flex;align-items:stretch;gap:26px}
.board-tab{position:relative;display:flex;align-items:center;gap:7px;color:var(--muted);font-size:13px}
.board-tab>span{font-size:11px;min-width:19px;text-align:center;color:var(--muted);font-variant-numeric:tabular-nums}
.board-tab.active{color:var(--ink);font-weight:650}
.board-tab.active>span{color:var(--ink)}
.board-tab.active:after{content:'';position:absolute;left:0;right:0;bottom:-1px;height:2px;background:var(--ink)}
.board-view{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}
.board-view .icon{width:14px;height:14px}
.board-view i{width:1px;height:12px;background:var(--line);margin:0 5px}
.reason-board{flex:1;min-height:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;padding:16px 28px 20px;background:var(--fog)}
.reason-lane{min-width:0;min-height:0;display:flex;flex-direction:column}
.lane-heading{height:50px;flex:none;display:flex;flex-direction:column;justify-content:flex-start;border-bottom:1px solid #D8DEE4;margin-bottom:12px}
.lane-name{display:flex;align-items:center;gap:8px}
.lane-name>.icon{width:17px;height:17px;color:var(--ink)}
.lane-name h2{font-size:15px;line-height:24px;font-weight:650;letter-spacing:.1px}
.lane-count{font-size:12px;line-height:20px;color:var(--muted);font-variant-numeric:tabular-nums;margin-left:1px}
.lane-heading p{font-size:11px;line-height:20px;color:var(--muted);padding-left:25px}
.lane-records{flex:1;min-height:0;display:grid;grid-template-rows:repeat(4,minmax(0,1fr));gap:12px}
.record{min-width:0;min-height:0;display:flex;flex-direction:column;gap:4px;border:1px solid #DCE1E6;border-radius:6px;background:#fff;padding:11px 13px 10px;overflow:hidden}
.record.is-selected{background:#E7EBEF;border-color:#A7B1BA;border-left:3px solid var(--ink);padding-left:11px}
.record-title{height:23px;flex:none;display:flex;align-items:center;gap:7px}
.record-title .file-name{font-size:14px;font-weight:600;gap:8px;flex:1}
.record-title .file-name>.icon{width:19px;height:20px}
.selected-label{display:inline-flex;align-items:center;gap:3px;color:var(--ink);font-size:10px;white-space:nowrap}
.selected-label .icon{width:12px;height:12px}
.record-reason{height:21px;display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;color:#43515D;flex:none}
.record-reason>span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.risk-label{display:inline-flex;align-items:center;gap:2px;flex:none;font-size:11px}
.risk-label>.risk{gap:3px;font-size:11px}
.risk-label>.risk .icon{width:12px;height:12px}
.risk-label>.risk.high+span{color:var(--red)}
.risk-label>.risk.medium+span{color:var(--amber)}
.risk-label>.risk.low+span{color:var(--green)}
.record-meta{height:19px;display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:11px;color:var(--muted);flex:none;font-variant-numeric:tabular-nums}
.dataset-meta{display:flex;align-items:center;gap:5px;white-space:nowrap;min-width:0}
.dataset-meta>.icon{width:13px;height:13px}
.meta-dot{margin:0 2px;color:#9AA4AD}
.record-note{min-width:0;height:20px;flex:none;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:var(--muted);font-size:11px;line-height:20px}
.record-excerpt{font-size:11px;color:#4B5864}
.record-excerpt>span{font-size:11px;color:var(--muted);margin-right:7px}
.record-actions{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:auto;min-height:29px}
.record-actions>.status{font-size:11px;gap:5px}
.record-actions>.status:before{width:5px;height:5px}
.record-buttons{display:flex;align-items:center;gap:10px}
.record-buttons .btn{height:27px;padding:0 10px;border-radius:4px;font-size:11px;background:transparent;border-color:#CFD6DD}
.record-buttons .btn.solid{background:var(--ink);border-color:var(--ink);color:#fff}
.original-link{display:inline-flex;align-items:center;gap:3px;color:#5B6773;font-size:11px;white-space:nowrap}
.original-link .icon{width:12px;height:12px}
.footer{height:42px;min-height:42px;padding:0 28px;background:#fff}
`

write('c-board', 'C · 原因分组看板', css, content)
