const { facts, selected, esc, icon, btn, select, fileIcon, score, checkbox, header, tabs, footer, write } = require('./parts.cjs')

const d = facts.detail
const totalChanges = facts.issues.reduce((total, item) => total + item.count, 0)
const sourceContact = esc(d.contact)
  .replace('service@example.com', '<mark>service@example.com</mark>')
  .replace('13800000000', '<mark>13800000000</mark>')
const cleanContact = esc(d.maskedContact)
  .replace('[邮箱已脱敏]', '<mark>[邮箱已脱敏]</mark>')
  .replace('[电话已脱敏]', '<mark>[电话已脱敏]</mark>')

function document(clean) {
  return `<section class="diff-pane ${clean ? 'after' : 'before'}">
    <div class="pane-head"><div><strong>${clean ? '清洗预览' : '原始内容'}</strong><span>${clean ? d.previewCharacters.toLocaleString('en-US') : d.characters.toLocaleString('en-US')} 字</span></div>${clean ? '<span class="change-count">−244 字</span>' : '<span class="original-label">当前版本</span>'}</div>
    <div class="pane-location">第 3 页 / ${selected.pages} 页<span>维护与保养</span></div>
    <article class="diff-document">
      <h2>${esc(d.title)}</h2>
      <h3>${esc(d.subtitle)}</h3>
      <div class="unchanged-copy">${d.paragraphs.map(p => `<p>${esc(p)}</p>`).join('')}</div>
      <div class="diff-duplicate ${clean ? 'resolved' : 'removed'}">
        <div class="change-label">${icon(clean ? 'check' : 'minus')}<span>${clean ? '重复段落已移除' : '重复段落 · 2 处'}</span></div>
        ${clean ? '<p class="resolved-copy">保留首次出现的维护说明。</p><span class="matched-space">此处与原文对应</span>' : `<p>${esc(d.duplicate)}</p>`}
      </div>
      <div class="blank-change ${clean ? 'resolved-blank' : ''}">${icon(clean ? 'check' : 'align-left')}<span>${clean ? '连续空行合并为单行' : '连续空行 · 6 处'}</span></div>
      <div class="table-caption">${esc(d.tableTitle)}</div>
      <table><thead><tr>${d.columns.map(column => `<th>${esc(column)}</th>`).join('')}</tr></thead><tbody>${d.rows.slice(0, 2).map(row => `<tr>${row.map(cell => `<td>${esc(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>
      <div class="table-rest">${icon('more-horizontal')}<span>其余 2 项维护要求保持不变</span></div>
      <div class="diff-contact ${clean ? 'added' : 'removed'}"><span class="contact-caption">${icon(clean ? 'check' : 'shield-alert')}${clean ? '联系信息已脱敏' : '联系信息 · 2 处敏感内容'}</span><p>${clean ? cleanContact : sourceContact}</p></div>
    </article>
  </section>`
}

const rules = facts.issues.map((issue, index) => `<div class="rule-row">
  ${checkbox(true)}<div class="rule-main"><div class="rule-title"><strong>${esc(issue.action)}</strong><span>${issue.count}${esc(issue.unit)}</span></div><p>${esc(issue.location)}</p><div class="rule-effect">${['保留第一次出现的内容', '保留一行作为段落分隔', '替换为 [邮箱已脱敏]', '替换为 [电话已脱敏]'][index]}</div></div>
</div>`).join('')

const css = `
.c-tabs{height:46px;flex:none;padding:0 28px;border-bottom:1px solid var(--line);background:var(--surface)}
.file-bar{height:88px;flex:none;padding:0 28px;display:flex;align-items:center;gap:18px}
.file-select{height:52px;display:flex;align-items:center;gap:12px;padding:0 14px;border:1px solid #CDD4DB;border-radius:6px;background:var(--surface);width:397px}
.file-select>.icon:first-child{width:21px;height:25px}.file-select>div{min-width:0}.file-select strong{font-size:14px;display:block;font-weight:600}.file-select small{display:block;color:var(--muted);font-size:12px;line-height:19px}.file-select>.icon:last-child{width:14px;height:14px;margin-left:auto;color:var(--muted)}
.file-position{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:12px}.file-position .btn{width:28px;height:28px;padding:0;background:transparent;border-color:transparent}.file-position .icon{width:15px;height:15px}.file-quality{margin-left:auto;display:flex;align-items:center;gap:16px;font-size:12px}.file-quality>div{display:flex;align-items:center;gap:7px}.file-quality .quality-score{font-size:18px}.quality-warning{color:var(--amber);display:flex;gap:6px;align-items:center}.quality-warning .icon{width:15px;height:15px}
.compare-intro{height:58px;flex:none;padding:0 28px 14px;display:flex;align-items:center;gap:14px}.compare-intro h2{font-size:16px;font-weight:600;line-height:24px}.compare-intro>p{font-size:12px;color:var(--muted)}.preview-state{margin-left:auto;display:flex;gap:7px;align-items:center;font-size:12px;color:var(--amber)}.preview-state .icon{width:15px;height:15px}
.clean-workbench{flex:1;min-height:0;display:flex;gap:24px;padding:0 28px 22px}.diff-view{flex:1;min-width:0;border:1px solid var(--line);border-radius:6px;display:grid;grid-template-columns:1fr 1fr;overflow:hidden;background:var(--surface)}.diff-pane{min-width:0}.diff-pane+.diff-pane{border-left:1px solid var(--line)}
.pane-head{height:52px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;border-bottom:1px solid var(--line)}.pane-head>div{display:flex;align-items:baseline;gap:11px}.pane-head strong{font-size:14px;font-weight:600}.pane-head>div>span,.original-label{color:var(--muted);font-size:12px}.change-count{font-size:12px;color:var(--green);font-variant-numeric:tabular-nums}.pane-location{height:34px;display:flex;align-items:center;gap:12px;padding:0 20px;border-bottom:1px solid #EDF0F2;font-size:12px;color:var(--muted);background:#FBFCFC}.pane-location span{padding-left:12px;border-left:1px solid var(--line);line-height:14px}
.diff-document{padding:16px 20px 0;font-size:13px;line-height:1.8}.diff-document h2{font-size:20px;line-height:29px;font-weight:650;margin-bottom:5px}.diff-document h3{font-size:14px;line-height:22px;font-weight:600;margin-bottom:6px}.unchanged-copy{height:114px}.unchanged-copy p{margin-bottom:10px}.diff-duplicate{height:96px;padding:9px 12px;border-radius:3px;margin-top:2px}.diff-duplicate.removed{background:#FAF1EF;border-left:2px solid #BC7770}.diff-duplicate p{font-size:13px;line-height:22px;margin-top:5px}.change-label{display:flex;align-items:center;gap:6px;font-size:12px;line-height:18px}.change-label .icon{width:13px;height:13px}.removed .change-label{color:#97554F}.resolved{background:#F2F6F3;border:1px dashed #CCDCD0;color:#4E6858}.resolved .change-label{color:var(--green)}.matched-space{display:block;font-size:12px;color:#7D8B82;margin-top:10px}.resolved-copy{color:#5E7064}.blank-change{height:30px;display:flex;align-items:center;gap:6px;color:var(--amber);font-size:12px;border-bottom:1px dashed #E3D5B8;margin-top:3px}.blank-change .icon{width:13px;height:13px}.resolved-blank{color:var(--green);border-bottom-color:#D8E2DA}.diff-document .table-caption{margin:10px 0 5px;font-size:12px}.diff-document table{border-collapse:collapse;table-layout:fixed;width:100%;font-size:13px;line-height:20px}.diff-document th,.diff-document td{border:1px solid var(--line);padding:6px 8px;text-align:left}.diff-document th{background:var(--fog);font-weight:550}.diff-document th:nth-child(1){width:33%}.diff-document th:nth-child(2){width:20%}.table-rest{height:27px;display:flex;align-items:center;justify-content:center;gap:6px;color:var(--muted);font-size:12px;border:1px solid var(--line);border-top:0}.table-rest .icon{width:15px;height:15px}.diff-contact{margin-top:14px;padding:9px 11px 10px;border-left:2px solid #BC7770;background:#FAF1EF}.contact-caption{font-size:12px;color:#97554F;display:flex;align-items:center;gap:6px;line-height:18px}.contact-caption .icon{width:13px;height:13px}.diff-contact p{margin-top:4px;font-size:13px;line-height:23px;overflow-wrap:anywhere}.diff-contact mark{background:#F0DAD6;color:#8D4942;border-radius:2px;padding:1px 2px}.diff-contact.added{background:#F0F6F1;border-left-color:#7FAD8D}.added .contact-caption{color:var(--green)}.diff-contact.added mark{background:#DEEBE1;color:#386D47}
.rules-panel{width:260px;flex:none;padding-top:1px;display:flex;flex-direction:column}.rules-heading{height:34px;display:flex;align-items:flex-start;justify-content:space-between}.rules-heading h3{font-size:14px;font-weight:600}.rules-heading>span{font-size:12px;color:var(--muted);padding-top:1px}.rules-profile{padding:0 0 18px;border-bottom:1px solid var(--line)}.rules-profile>span{display:block;color:var(--muted);font-size:12px;margin-bottom:6px}.rules-profile .select{height:36px;width:100%;font-size:13px}.rule-row{display:flex;align-items:flex-start;gap:10px;padding:18px 0;border-bottom:1px solid var(--line)}.rule-row>.check-box{margin-top:3px;flex:none}.rule-main{min-width:0;flex:1}.rule-title{display:flex;align-items:center;gap:10px}.rule-title strong{font-size:13px;font-weight:550}.rule-title>span{margin-left:auto;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}.rule-main>p{font-size:12px;color:var(--muted);margin-top:5px;line-height:20px}.rule-effect{font-size:12px;color:#73806F;margin-top:7px}.rule-summary{padding-top:19px}.rule-summary strong{font-size:13px;font-weight:550}.rule-summary p{font-size:12px;color:var(--muted);line-height:21px;margin-top:6px}.rules-link{display:flex;align-items:center;gap:6px;font-size:12px;margin-top:14px;color:#465660}.rules-link .icon{width:13px;height:13px}.scope-note{margin-top:auto;font-size:12px;line-height:21px;color:var(--muted);padding-top:24px}
.workspace-footer{height:60px;padding:0 28px;background:var(--surface)}.footer-preview{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}.footer-preview .icon{width:14px;height:14px;color:var(--amber)}.workspace-footer .btn.solid{height:36px;padding:0 18px}.workspace-footer .btn.quiet{color:var(--muted)}.footer-next{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);margin-left:10px}.footer-next .icon{width:14px;height:14px}
`

const content = header(select(facts.dataset, 'dataset')) +
  `<div class="c-tabs">${tabs('clean')}</div>
  <div class="file-bar">
    <div class="file-select">${fileIcon(selected)}<div><strong>${esc(selected.name)}</strong><small>${esc(facts.folder)} · ${selected.pages} 页 · ${esc(selected.size)}</small></div>${icon('chevron-down')}</div>
    <div class="file-position">${btn('', 'chevron-left')}<span>1 / ${facts.files.length} 文档</span>${btn('', 'chevron-right')}</div>
    <div class="file-quality"><div><span class="muted">质量评分</span>${score(selected)}</div><span class="thin-separator"></span><span class="quality-warning">${icon('alert-circle')}${selected.issues} 类问题</span></div>
  </div>
  <div class="compare-intro"><h2>核对清洗结果</h2><p>逐项查看移除与替换内容</p><div class="preview-state">${icon('clock')}预览尚未应用</div></div>
  <div class="clean-workbench">
    <div class="diff-view">${document(false)}${document(true)}</div>
    <aside class="rules-panel">
      <div class="rules-heading"><h3>清洗规则</h3><span>4 / 4 已启用</span></div>
      <div class="rules-profile"><span>规则配置</span>${select(d.profile, 'rule-set')}</div>
      <div class="rules-list">${rules}</div>
      <div class="rule-summary"><strong>${totalChanges} 处内容将被处理</strong><p>清洗后减少 244 字，保留原有段落顺序与表格结构。</p></div>
      <div class="rules-link">管理规则配置${icon('arrow-up-right')}</div>
      <p class="scope-note">当前显示第 3 页内容节选。<br>所选规则将应用至整篇文档。</p>
    </aside>
  </div>` + footer(`<span class="footer-preview">${icon('info')}清洗结果将在应用后写入文档</span>`, btn('恢复默认', '', 'quiet') + btn('应用清洗结果', 'check', 'solid') + `<span class="footer-next">下一步：切块预览${icon('arrow-right')}</span>`)

write('c-diff', 'C · 清洗对照', css, content)
