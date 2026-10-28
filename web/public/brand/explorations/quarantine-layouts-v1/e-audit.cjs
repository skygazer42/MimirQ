const { facts, esc, icon, file, risk, review, btn, control, search, header, write } = require('./parts.cjs')

// E · 上下分区审计台。记录比较在上，当前文档的判断与动作在下。
const selected = facts.documents.find(doc => doc.id === facts.selectedId)
const visible = facts.documents.slice(0, 7)

const css = `
.page-header{padding-left:24px;padding-right:24px}
.header-context{font-size:12px;color:var(--muted);padding-left:20px;border-left:1px solid var(--line)}
.register{height:460px;flex:none;display:flex;flex-direction:column;background:white}
.register-caption{height:44px;flex:none;display:flex;align-items:center;padding:0 24px;border-bottom:1px solid var(--line);gap:28px}
.register-caption h2{font-size:14px;font-weight:650}
.register-caption .tabs{gap:24px}
.register-caption .tab{font-size:12px;height:44px;gap:6px}
.register-caption .count{height:19px;min-width:19px;font-size:11px;background:transparent;padding:0}
.register-caption .tab.active .count{background:var(--subtle)}
.register-caption .ordering{margin-left:auto;display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}
.ordering .icon{width:14px;height:14px}
.register-filters{height:60px;flex:none;display:flex;align-items:center;gap:9px;padding:0 24px}
.register-filters .control{height:32px;font-size:12px;background:white}
.register-filters .search-control{height:32px;width:286px;margin-left:3px;font-size:12px}
.filter-date{margin-left:auto;display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}
.filter-date .icon{width:14px;height:14px}
.register-table{height:321px;flex:none;padding:0 24px;overflow:hidden}
.register-table table{width:100%;height:321px}
.register-table th{height:34px;background:var(--fog);font-size:11px;font-weight:500}
.register-table td{height:41px;font-size:12px}
.register-table th,.register-table td{padding:0 10px;vertical-align:middle;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.register-table th:first-child,.register-table td:first-child{padding:0;text-align:center}
.register-table th:last-child,.register-table td:last-child{padding:0;text-align:center}
.register-table .file-name{font-size:12px;gap:9px}
.register-table .file-name .icon{width:15px;height:17px}
.register-table .risk,.register-table .status{font-size:11px}
.register-table tbody tr.selected{background:var(--selected)}
.register-table tbody tr.selected td:first-child{box-shadow:inset 2px 0 0 var(--ink)}
.register-table tbody tr.selected .file-name{font-weight:650}
.register-table tbody tr:last-child td{border-bottom:0}
.register-table .row-check{width:12px;height:12px;border:1px solid #B9C2CA;border-radius:2px;display:inline-block;vertical-align:middle;background:white}
.register-table .row-end{width:13px;height:13px;color:#8A959F;display:inline-block}
.register-table tr.selected .row-end{color:var(--ink)}
.register-table .source{color:var(--muted)}
.register-foot{height:35px;flex:none;display:flex;align-items:center;justify-content:space-between;padding:0 24px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}
.register-foot .pagination{font-size:11px;gap:9px}
.register-foot .btn{height:25px;width:25px;border-radius:4px}
.register-foot .btn .icon{width:13px;height:13px}
.splitter{height:8px;flex:none;background:var(--subtle);border-top:1px solid #D4DAE0;border-bottom:1px solid #D4DAE0;display:flex;align-items:center;justify-content:center}
.splitter:after{content:'';width:30px;height:2px;background:#BAC3CB;border-radius:2px}
.inspector{height:460px;flex:none;display:flex;flex-direction:column}
.inspector-head{height:54px;flex:none;background:var(--fog);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px;padding:0 24px}
.inspector-label{font-size:11px;color:var(--muted);padding-right:16px;border-right:1px solid var(--line)}
.inspector-head .file-name{font-size:14px;font-weight:650;gap:9px}
.inspector-head .file-name .icon{width:18px;height:20px}
.inspector-head .object-id{color:var(--muted);font-size:11px;margin-left:-5px}
.inspector-head .status{font-size:11px}
.inspector-head .tag{font-size:11px;line-height:19px;background:#E7EBEF;color:#4C5965}
.inspector-head .review-action{margin-left:auto;height:30px;font-size:12px;background:white}
.inspector-head .expand{height:30px;width:30px;margin-left:-7px}
.inspector-body{height:342px;flex:none;display:grid;grid-template-columns:58% 42%;overflow:hidden}
.excerpt-pane{padding:19px 28px 20px 28px;border-right:1px solid var(--line);min-width:0}
.pane-caption{display:flex;align-items:center;justify-content:space-between;font-size:11px;color:var(--muted);line-height:20px;margin-bottom:14px}
.pane-caption strong{font-size:12px;color:var(--ink);font-weight:600}
.excerpt-document{padding-left:18px;border-left:2px solid #E6E9EC}
.excerpt-document h3{font-size:19px;line-height:29px;font-weight:600;margin-bottom:7px;letter-spacing:.01em}
.excerpt-document h4{font-size:13px;line-height:24px;font-weight:600;margin-bottom:8px}
.excerpt-document .preview-copy{font-size:13px;line-height:25px;color:#4D5964;max-width:680px}
.excerpt-document .preview-copy p+p{margin-top:9px}
.inspection-pane{padding:18px 24px 17px;min-width:0}
.inspection-pane .pane-caption{margin-bottom:8px}
.suspected{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--amber)}
.suspected .icon{width:12px;height:12px}
.rule-line{display:flex;align-items:baseline;gap:12px;margin-bottom:7px}
.rule-line h3{font-size:14px;font-weight:600}
.rule-line .rule-code{font-size:11px;letter-spacing:.01em}
.governance-copy{font-size:13px;line-height:22px;color:var(--muted);margin-bottom:13px}
.object-meta{display:grid;grid-template-columns:1fr 1fr;gap:8px 20px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:11px 0;margin-bottom:12px}
.object-meta>div{display:flex;align-items:baseline;gap:13px;min-width:0;font-size:11px;line-height:20px}
.object-meta dt{color:var(--muted);white-space:nowrap;min-width:49px}
.object-meta dd{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stage-title{font-size:11px;color:var(--muted);line-height:20px;margin-bottom:8px}
.stage-track{display:flex;align-items:center;gap:9px}
.stage{display:flex;align-items:center;gap:8px;min-width:0;flex:1}
.stage>.icon{width:18px;height:18px}
.stage.done>.icon{color:var(--green)}
.stage.current>.icon{color:var(--amber)}
.stage.next>.icon{color:#97A1AB}
.stage strong{display:block;font-size:11px;font-weight:550;line-height:17px;white-space:nowrap}
.stage small{display:block;color:var(--muted);font-size:10px;line-height:16px;white-space:nowrap}
.stage.current small{color:var(--amber)}
.stage-arrow{width:12px;height:12px;color:#9AA5AE;flex:none;margin-right:4px}
.inspector-actions{height:64px;flex:none;display:flex;align-items:center;gap:9px;border-top:1px solid var(--line);padding:0 24px;background:var(--fog)}
.inspector-actions .original{padding-left:0;margin-right:10px;color:var(--ink)}
.inspector-actions .decision-note{color:var(--muted);font-size:11px}
.inspector-actions .decision-note strong{font-weight:500;color:var(--amber)}
.inspector-actions .btn{height:34px;font-size:12px}
.inspector-actions .solid{padding:0 15px}
`

const rows = visible.map(doc => `<tr class="${doc.id === selected.id ? 'selected' : ''}">
  <td><span class="row-check"></span></td>
  <td>${file(doc)}</td>
  <td>${esc(doc.dataset)}</td>
  <td>${esc(doc.reason)}</td>
  <td>${risk(doc)}</td>
  <td>${review(doc)}</td>
  <td class="source">${esc(doc.source)}</td>
  <td class="num muted">${esc(doc.time)}</td>
  <td>${icon(doc.id === selected.id ? 'chevron-down' : 'chevron-right', 'row-end')}</td>
</tr>`).join('')

const content = `${header('<span class="header-context">文档治理 / 审计台账</span>')}
<section class="register" aria-label="文档审计台账">
  <div class="register-caption">
    <h2>文档审计</h2>
    <div class="tabs"><div class="tab active">全部<span class="count">12</span></div><div class="tab">待复核<span class="count">8</span></div><div class="tab">已复核<span class="count">4</span></div></div>
    <span class="ordering">${icon('arrow-down')}隔离时间</span>
  </div>
  <div class="register-filters">${control('全部数据集', 'dataset')}${control('全部原因')}${control('全部风险')}${search('搜索文档或规则')}<span class="filter-date">${icon('calendar')}${esc(facts.date)}</span></div>
  <div class="register-table"><table><colgroup><col style="width:3%"><col style="width:25%"><col style="width:12%"><col style="width:18%"><col style="width:8%"><col style="width:10%"><col style="width:12%"><col style="width:9%"><col style="width:3%"></colgroup><thead><tr><th><span class="row-check"></span></th><th>文档</th><th>所属数据集</th><th>隔离原因</th><th>风险</th><th>复核状态</th><th>来源阶段</th><th>隔离时间</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
  <div class="register-foot"><span>显示 <span class="num">1–7</span> 条，共 <span class="num">12</span> 条记录</span><div class="pagination">每页 20 条${btn('', 'chevron-left', 'quiet square')}<strong>1</strong>${btn('', 'chevron-right', 'quiet square')}</div></div>
</section>
<div class="splitter"></div>
<section class="inspector" aria-label="当前文档检查">
  <div class="inspector-head"><span class="inspector-label">文档检查</span>${file(selected)}<span class="object-id num">${esc(selected.id)}</span>${review(selected)}<span class="tag">隔离中</span>${btn('标记已复核', 'check-check', 'review-action')}${btn('', 'maximize2', 'quiet square expand')}</div>
  <div class="inspector-body">
    <article class="excerpt-pane"><div class="pane-caption"><strong>正文摘录</strong><span>文档解析</span></div><div class="excerpt-document"><h3>${esc(facts.preview.heading)}</h3><h4>${esc(facts.preview.section)}</h4><div class="preview-copy">${facts.preview.paragraphs.map(p => `<p>${esc(p)}</p>`).join('')}</div></div></article>
    <aside class="inspection-pane"><div class="pane-caption"><strong>隔离依据</strong><span class="suspected">${icon('alert-triangle')}疑似风险 · 待确认</span></div><div class="rule-line"><h3>${esc(selected.reason)}</h3><span class="rule-code">${esc(selected.reasonKey)}</span></div><p class="governance-copy">${esc(facts.preview.governance)}</p><dl class="object-meta"><div><dt>数据集</dt><dd>${esc(selected.dataset)}</dd></div><div><dt>文件大小</dt><dd class="num">${esc(selected.size)}</dd></div><div><dt>来源阶段</dt><dd>${esc(selected.source)}</dd></div><div><dt>隔离时间</dt><dd class="num">${esc(selected.time)}</dd></div></dl><div class="stage-title">入库阶段</div><div class="stage-track"><div class="stage done">${icon('check-circle')}<div><strong>文档解析</strong><small>已完成</small></div></div>${icon('arrow-right', 'stage-arrow')}<div class="stage current">${icon('quarantine')}<div><strong>数据治理</strong><small>已隔离</small></div></div>${icon('arrow-right', 'stage-arrow')}<div class="stage next">${icon('circle-dashed')}<div><strong>分片与索引</strong><small>未开始</small></div></div></div></aside>
  </div>
  <div class="inspector-actions">${btn('查看原文', 'arrow-up-right', 'quiet original')}<span class="decision-note">风险判定为<strong>疑似</strong>，核对后再决定是否放行</span><span class="spacer"></span>${btn('重试', 'rotate-ccw')}${btn('调参', 'settings2')}${btn('放行并重试', 'play', 'solid')}</div>
</section>`

write('e-audit', 'E · 上下分区审计台', css, content)
