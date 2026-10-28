const { facts, esc, icon, file, risk, review, btn, control, search, header, write } = require('./parts.cjs')

// B · 收件箱复核：以逐条处理为主，原因、原文和动作在一个连续复核面中展开。
const selected = facts.documents.find(doc => doc.id === facts.selectedId)
const queue = facts.documents.map((doc, index) => `
  <div class="inbox-row ${doc.id === selected.id ? 'is-current' : ''}" data-document-id="${esc(doc.id)}">
    <div class="inbox-row-top">${file(doc)}<time>${esc(doc.time)}</time></div>
    <div class="inbox-row-bottom"><span class="inbox-reason">${esc(doc.reason)}</span><span class="inbox-states">${risk(doc)}${review(doc)}</span></div>
  </div>`).join('')

const css = `
.inbox-workspace{display:flex;flex:1;min-height:0}
.inbox-pane{width:376px;flex:none;display:flex;flex-direction:column;border-right:1px solid var(--line);background:#FAFBFC}
.inbox-tools{height:112px;flex:none;border-bottom:1px solid var(--line)}
.inbox-views{height:46px;display:flex;align-items:stretch;gap:23px;padding:0 18px;border-bottom:1px solid var(--line)}
.inbox-view{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);position:relative;white-space:nowrap}
.inbox-view.active{font-weight:600;color:var(--ink)}
.inbox-view.active:after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:var(--ink)}
.inbox-view .count{min-width:20px;height:19px;padding:0 4px;font-size:11px}
.inbox-search{height:66px;display:flex;align-items:center;gap:8px;padding:0 16px}
.inbox-search .search-control{flex:1;min-width:0;font-size:12px}
.inbox-search .btn{background:white}
.inbox-list{flex:none}
.inbox-row{height:64px;padding:10px 16px 9px 18px;position:relative;border-bottom:1px solid #E6E9EC;background:white}
.inbox-row.is-current{background:var(--selected)}
.inbox-row.is-current:before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--ink)}
.inbox-row-top{display:flex;align-items:center;gap:10px;height:22px}
.inbox-row-top .file-name{flex:1;font-size:13px;gap:8px}
.inbox-row-top time{font-size:11px;line-height:20px;color:var(--muted);font-variant-numeric:tabular-nums;flex:none}
.inbox-row-bottom{display:flex;align-items:center;gap:8px;padding-left:25px;height:21px}
.inbox-reason{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.inbox-states{display:flex;align-items:center;gap:12px;margin-left:auto;flex:none}
.inbox-states .risk,.inbox-states .status{font-size:10px;gap:4px}
.inbox-states .risk .icon{width:11px;height:11px}
.inbox-states .status:before{width:5px;height:5px}
.inbox-bottom{height:48px;flex:none;display:flex;align-items:center;justify-content:space-between;padding:0 18px;font-size:11px;color:var(--muted);background:var(--fog)}
.inbox-bottom>span:last-child{display:flex;align-items:center;gap:5px}.inbox-bottom .icon{width:13px;height:13px}
.review-pane{flex:1;min-width:0;display:flex;flex-direction:column;background:white}
.review-heading{height:104px;flex:none;display:flex;align-items:center;justify-content:space-between;padding:20px 30px;border-bottom:1px solid var(--line)}
.current-label{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted);margin-bottom:7px}
.current-label .num{font-size:11px;color:var(--muted)}
.current-title{display:flex;align-items:center;gap:12px}
.current-title>.icon{width:27px;height:29px}
.current-title h2{font-size:22px;line-height:31px;letter-spacing:-.3px;font-weight:650}
.current-title .status{margin-left:5px}
.current-nav{display:flex;align-items:center;gap:6px}
.current-nav .btn{background:var(--fog)}
.review-reason{height:214px;flex:none;padding:22px 30px 20px;border-bottom:1px solid var(--line)}
.section-kicker{font-size:12px;font-weight:550;display:flex;align-items:center;gap:9px;margin-bottom:8px}
.section-kicker>.icon{width:15px;height:15px;color:var(--red)}
.reason-title{display:flex;align-items:center;gap:12px}
.reason-title h3{font-size:19px;line-height:29px;font-weight:600}
.reason-title .risk{font-size:11px;border-left:1px solid var(--line);padding-left:13px}
.reason-description{font-size:13px;color:var(--muted);line-height:23px;margin-top:4px}
.reason-rule{font-size:11px;letter-spacing:.1px;color:var(--muted);margin-top:5px}
.review-metadata{display:grid;grid-template-columns:1fr 1fr 1fr 1.4fr;gap:24px;border-top:1px solid #E9ECEF;margin-top:15px;padding-top:13px}
.review-metadata dt{color:var(--muted);font-size:11px;line-height:17px;margin-bottom:3px}
.review-metadata dd{font-size:12px;line-height:19px;display:flex;align-items:center;gap:6px}
.review-metadata .icon{width:13px;height:13px;color:var(--muted)}
.review-preview{flex:1;min-height:0;display:flex;flex-direction:column}
.preview-toolbar{height:58px;flex:none;display:flex;align-items:center;justify-content:space-between;padding:0 30px}
.preview-toolbar h3{font-size:13px;font-weight:550;display:flex;align-items:center;gap:8px}
.preview-toolbar h3 .icon{width:16px;height:16px;color:var(--muted)}
.preview-toolbar h3 span{font-size:11px;font-weight:450;color:var(--muted);padding-left:7px;border-left:1px solid var(--line)}
.source-excerpt{width:704px;max-width:100%;margin:0 auto;flex:1;min-height:0;padding:13px 48px 0}
.source-excerpt h4{font-size:22px;font-weight:600;text-align:center;line-height:34px;margin-bottom:30px;letter-spacing:1px}
.source-excerpt .document-section{font-size:15px;line-height:25px;font-weight:550;margin-bottom:16px}
.source-excerpt .preview-copy{font-size:14px;line-height:29px;color:#3F4A55}
.source-excerpt .preview-copy p+p{margin-top:15px}
.source-excerpt .preview-copy .hit-paragraph{color:var(--ink)}
.source-excerpt .preview-copy mark{padding:2px 3px}
.excerpt-end{display:flex;align-items:center;gap:12px;font-size:11px;color:var(--muted);margin-top:25px;white-space:nowrap}
.excerpt-end:before,.excerpt-end:after{content:'';height:1px;background:#E8EBEE;flex:1}
.governance-note{margin:20px 30px 20px;display:flex;align-items:flex-start;gap:9px;font-size:12px;line-height:21px;color:var(--muted)}
.governance-note .icon{width:14px;height:14px;margin-top:3px;color:#73816F}
.review-actions{height:76px;flex:none;display:flex;align-items:center;gap:9px;padding:0 30px;border-top:1px solid var(--line);background:var(--fog)}
.review-actions .action-context{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:7px;margin-right:auto}
.review-actions .action-context .icon{width:15px;height:15px}
.review-actions .btn{height:36px}
.review-actions .solid{margin-left:3px;padding:0 15px}
`

const paragraphs = facts.preview.paragraphs.map((paragraph, index) => {
  const text = index === 1
    ? esc(paragraph).replace('138****1024', '<mark>138****1024</mark>').replace('139****2301', '<mark>139****2301</mark>')
    : esc(paragraph)
  return `<p class="${index === 1 ? 'hit-paragraph' : ''}">${text}</p>`
}).join('')

const content = `${header(control(facts.scope, 'dataset'))}
<div class="inbox-workspace">
  <section class="inbox-pane" aria-label="待处理文档收件箱">
    <div class="inbox-tools">
      <div class="inbox-views"><span class="inbox-view active">全部<span class="count">${facts.summary.total}</span></span><span class="inbox-view">待复核<span class="count">${facts.summary.pending}</span></span><span class="inbox-view">已复核<span class="count">${facts.summary.reviewed}</span></span></div>
      <div class="inbox-search">${search('搜索文档或隔离原因')}${btn('', 'filter', 'square')}</div>
    </div>
    <div class="inbox-list">${queue}</div>
    <div class="inbox-bottom"><span>12 份文档 · 按时间倒序</span><span>已显示全部</span></div>
  </section>
  <section class="review-pane" aria-label="当前文档复核">
    <div class="review-heading">
      <div><div class="current-label">当前文档<span class="num">1 / ${facts.summary.total}</span><span class="tag">已隔离</span></div><div class="current-title">${icon('file-pdf', 'file-pdf')}<h2>${esc(selected.name)}</h2>${review(selected)}</div></div>
      <div class="current-nav">${btn('', 'chevron-up', 'square')}${btn('', 'chevron-down', 'square')}${btn('', 'more-horizontal', 'quiet square')}</div>
    </div>
    <section class="review-reason">
      <div class="section-kicker">${icon('shield-alert')}隔离原因</div>
      <div class="reason-title"><h3>${esc(selected.reason)}</h3>${risk(selected)}</div>
      <p class="reason-description">${esc(selected.note)}</p>
      <div class="reason-rule">分类 · ${esc(selected.group)}</div>
      <dl class="review-metadata"><div><dt>所属数据集</dt><dd>${icon('dataset')}${esc(selected.dataset)}</dd></div><div><dt>处理来源</dt><dd>${esc(selected.source)}</dd></div><div><dt>文件大小</dt><dd class="num">${esc(selected.size)}</dd></div><div><dt>进入队列</dt><dd class="num">${esc(facts.date)} ${esc(selected.time)}</dd></div></dl>
    </section>
    <section class="review-preview">
      <div class="preview-toolbar"><h3>${icon('scan-text')}文档原文摘录<span>PDF</span></h3>${btn('查看原文', 'external-link', 'quiet')}</div>
      <article class="source-excerpt"><h4>${esc(facts.preview.heading)}</h4><div class="document-section">${esc(facts.preview.section)}</div><div class="preview-copy">${paragraphs}</div><div class="excerpt-end">原文摘录结束</div></article>
      <div class="governance-note">${icon('info')}<p>${esc(facts.preview.governance)}</p></div>
    </section>
    <div class="review-actions"><span class="action-context">${icon('quarantine')}当前保留隔离</span>${btn('调整参数', 'settings2')}${btn('重试', 'refresh-cw')}${btn('放行并重试', 'check', 'solid')}</div>
  </section>
</div>`

write('b-inbox', 'B · 收件箱复核', css, content)
