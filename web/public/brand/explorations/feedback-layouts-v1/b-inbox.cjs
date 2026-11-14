const { facts, stats, esc, icon, btn, select, search, rating, state, header, write } = require('./parts.cjs')

const selected = facts.feedback.find(item => item.id === facts.selectedId)

const css = `
.header-view{display:flex;align-items:center;gap:7px;font-size:13px;color:var(--muted)}
.header-view .icon{width:15px;height:15px}
.inbox{display:flex;flex:1;min-height:0}
.queue{width:316px;flex:none;min-height:0;display:flex;flex-direction:column;border-right:1px solid var(--line);background:var(--fog)}
.queue-tools{height:120px;flex:none;padding:17px 16px 15px;border-bottom:1px solid var(--line)}
.queue-tools .search{height:34px;background:var(--surface)}
.queue-filters{display:flex;align-items:center;gap:8px;margin-top:12px}
.queue-filters .select{height:30px;flex:1;font-size:12px;background:transparent;padding:0 9px}
.queue-filters .select:last-child{flex:1.06}
.queue-list{flex:1;min-height:0;overflow-y:auto;scrollbar-width:thin;scrollbar-color:#C8D0D7 transparent}
.queue-item{height:76px;display:block;padding:8px 16px;border-bottom:1px solid var(--line);background:var(--surface)}
.queue-item.selected{background:var(--selected)}
.queue-question{height:38px;font-size:13px;line-height:19px;font-weight:450}
.queue-item.selected .queue-question{font-weight:600}
.queue-meta{height:18px;display:flex;align-items:center;gap:10px;margin-top:3px;font-size:12px;line-height:18px;color:var(--muted)}
.queue-meta .rating{gap:4px;font-size:12px}
.queue-meta .rating>.icon{width:12px;height:12px}
.queue-meta .rating>span{font-size:11px}
.queue-issue{min-width:0;white-space:nowrap}
.queue-time{margin-left:auto;white-space:nowrap;font-size:12px;font-variant-numeric:tabular-nums}
.queue-bottom{height:48px;flex:none;display:flex;align-items:center;gap:9px;padding:0 16px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
.queue-bottom>.icon{width:13px;height:13px}
.queue-bottom .queue-pages{margin-left:auto;display:flex;align-items:center;gap:12px}
.queue-pages .icon{width:13px;height:13px;color:#AAB4BD}
.reader{flex:1;min-width:0;display:flex;flex-direction:column;background:var(--surface)}
.reading{flex:1;min-height:0;padding:22px 36px 0}
.record-bar{height:24px;display:flex;align-items:center;gap:12px;font-size:12px;color:var(--muted)}
.record-id{font-weight:550;color:var(--ink);font-variant-numeric:tabular-nums}
.record-nav{display:flex;align-items:center;gap:10px;margin-left:auto}
.record-nav .btn{width:26px;height:26px;padding:0;border-color:transparent;background:var(--fog)}
.record-nav .btn .icon{width:13px;height:13px}
.record-nav .btn:first-of-type{color:#AAB4BD}
.question{margin-top:13px;font-size:20px;font-weight:600;line-height:30px;letter-spacing:0}
.context{display:flex;align-items:center;gap:17px;margin-top:9px;font-size:12px;line-height:20px;color:var(--muted)}
.context>span{display:flex;align-items:center;gap:6px;white-space:nowrap}
.context .icon{width:13px;height:13px}
.section{padding:19px 0;border-top:1px solid var(--line)}
.feedback-section{margin-top:20px;padding-top:18px;padding-bottom:18px}
.section-heading{height:22px;display:flex;align-items:center;gap:11px;margin-bottom:10px}
.section-heading h2{font-size:13px;line-height:22px;font-weight:600}
.section-heading .rating{margin-left:auto}
.section-heading .section-meta{font-size:12px;color:var(--muted)}
.feedback-reason{font-size:14px;line-height:1.8}
.feedback-tags{display:flex;gap:7px;margin-top:10px}
.feedback-tags .tag{background:var(--fog)}
.copy{font-size:14px;line-height:1.8;max-width:890px}
.copy p+p{margin-top:7px}
.expected-list{list-style:none;padding:0;margin:0;display:grid;gap:7px}
.expected-list li{display:flex;align-items:baseline;gap:12px;font-size:14px;line-height:1.8}
.expected-list .step{font-size:12px;color:var(--muted);width:13px;flex:none;font-variant-numeric:tabular-nums}
.citations-section{padding-top:18px;padding-bottom:0}
.citations-section .section-heading{margin-bottom:3px}
.source-row{display:flex;align-items:flex-start;gap:11px;padding:10px 0;border-bottom:1px solid var(--line)}
.source-row:last-child{border-bottom:0}
.source-row>.icon{width:18px;height:19px;margin-top:3px}
.source-row>.icon:last-child{margin-left:auto;width:13px;height:13px;color:var(--muted);margin-top:5px}
.source-order{font-size:12px;line-height:23px;color:var(--muted);width:10px;flex:none}
.source-content{min-width:0}
.source-title{display:flex;align-items:center;gap:12px;font-size:13px;line-height:23px}
.source-title strong{font-weight:550}
.source-title span{font-size:12px;color:var(--muted)}
.source-excerpt{font-size:14px;line-height:1.8;color:var(--muted);margin-top:2px}
.record-actions{height:68px;flex:none;border-top:1px solid var(--line);display:flex;align-items:center;gap:8px;padding:0 36px;background:var(--fog)}
.record-actions>.state{margin-right:auto}
.record-actions .btn{height:35px}
`

const queueItems = facts.feedback.map(item => `
  <div class="queue-item ${item.id === selected.id ? 'selected' : ''}">
    <div class="queue-question">${esc(item.question)}</div>
    <div class="queue-meta">
      ${rating(item)}<span class="queue-issue">${esc(item.issue)}</span><span class="queue-time">${esc(item.time)}</span>
    </div>
  </div>`).join('')

const sourceRows = facts.detail.citations.map((citation, index) => `
  <div class="source-row">
    <span class="source-order">${index + 1}</span>
    ${icon(citation.kind === 'md' ? 'file-markdown' : 'file-pdf', 'file-' + citation.kind)}
    <div class="source-content">
      <div class="source-title"><strong>${esc(citation.name)}</strong><span>${esc(citation.location)}</span></div>
      <p class="source-excerpt">${esc(citation.excerpt)}</p>
    </div>
    ${icon('arrow-up-right')}
  </div>`).join('')

const content = header(`<span class="header-view">${icon('mail')}收件箱</span>`) + `
  <div class="inbox">
    <aside class="queue" aria-label="反馈队列">
      <div class="queue-tools">
        ${search('搜索问题、反馈或用户')}
        <div class="queue-filters">${select('全部反馈 · ' + stats.total)}${select('评分 · 全部')}</div>
      </div>
      <div class="queue-list">${queueItems}</div>
      <div class="queue-bottom"><span>共 ${stats.total} 条反馈</span><div class="queue-pages"><span>1 / 1</span>${icon('chevron-left')}${icon('chevron-right')}</div></div>
    </aside>
    <section class="reader" aria-label="反馈详情">
      <article class="reading">
        <div class="record-bar">
          <span class="record-id">${esc(selected.id)}</span>${state(selected)}
          <div class="record-nav"><span>1 / ${stats.total}</span>${btn('', 'chevron-left', 'square')}${btn('', 'chevron-right', 'square')}</div>
        </div>
        <h2 class="question">${esc(selected.question)}</h2>
        <div class="context">
          <span>${icon('user')}${esc(selected.account)}</span><span>${esc(selected.source)}</span><span>${esc(selected.time)}</span><span>知识库 · ${esc(facts.detail.dataset)}</span>
        </div>
        <section class="section feedback-section">
          <div class="section-heading"><h2>用户反馈</h2><span class="tag">${esc(selected.issue)}</span>${rating(selected)}</div>
          <p class="feedback-reason">${esc(selected.reason)}</p>
          <div class="feedback-tags">${selected.tags.map(tag => `<span class="tag">${esc(tag)}</span>`).join('')}</div>
        </section>
        <section class="section">
          <div class="section-heading"><h2>原回答</h2></div>
          <div class="copy">${facts.detail.answer.map(paragraph => `<p>${esc(paragraph)}</p>`).join('')}</div>
        </section>
        <section class="section">
          <div class="section-heading"><h2>期望回答</h2></div>
          <ol class="expected-list">${facts.detail.expected.map((paragraph, index) => `<li><span class="step">${index + 1}.</span><span>${esc(paragraph)}</span></li>`).join('')}</ol>
        </section>
        <section class="section citations-section">
          <div class="section-heading"><h2>原回答引用</h2><span class="section-meta">${facts.detail.citations.length} 个来源</span></div>
          ${sourceRows}
        </section>
      </article>
      <footer class="record-actions">
        <span class="state"><i></i>待分析</span>
        ${btn('原会话', 'conversation')}${btn('创建回归用例', 'evaluation')}${btn('标记已处理', 'check', 'solid')}
      </footer>
    </section>
  </div>`

write('b-inbox', 'B · 质检收件箱', css, content)
