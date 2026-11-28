const {
  profiles, selected, groupCounts, labels, btn, icon, esc, search,
  formats, builtin, objectIcon, facts, write,
} = require('./parts.cjs')

// B / 目录分栏：让选择模板与阅读参数始终保持在同一个视野里。
const entries = Object.entries(selected.payload.pipeline_patch)
  .filter(([key]) => key !== 'governance_enabled')
const ruleEntries = entries.filter(([, value]) => typeof value === 'boolean')
const parameterEntries = entries.filter(([, value]) => typeof value !== 'boolean')
const purposes = {
  governance_remove_toc_lines: '移除目录标题与目录条目',
  governance_remove_noise_lines: '清理孤立噪声行',
  governance_unwrap_lines: '合并段内异常断行',
  governance_remove_common_lines: '移除跨页重复页眉页脚',
  governance_normalize_tables: '统一 Markdown 表格格式',
  governance_max_blank_lines: '限制段落之间的连续空行',
}

const directory = Object.keys(groupCounts).map(group => `
  <section class="directory-group">
    <h3>${esc(group)}<span>${groupCounts[group]}</span></h3>
    ${profiles.filter(profile => profile.group === group).map(profile => `
      <div class="directory-item ${profile.key === selected.key ? 'current' : ''}" title="${esc(profile.name)}">
        ${objectIcon(profile)}
        <span>${esc(profile.shortName)}</span>
        ${profile.key === selected.key ? icon('chevron-right') : ''}
      </div>`).join('')}
  </section>`).join('')

const fieldRow = ([key, value], index, isParameter = false) => `
  <div class="rule-line ${isParameter ? 'parameter-line' : ''}" role="row">
    <div class="rule-name" role="cell"><span class="rule-number">${String(index + 1).padStart(2, '0')}</span>${esc(labels[key] || key)}</div>
    <span class="rule-purpose" role="cell">${esc(purposes[key] || labels[key])}</span>
    <div class="rule-value" role="cell">${typeof value === 'boolean'
      ? `<span class="value-state">${icon(value ? 'check' : 'minus')}<span>${value ? '启用' : '关闭'}</span></span>`
      : `<strong>${esc(value)}</strong><span>${key === 'governance_max_blank_lines' ? '行' : ''}</span>`}
    </div>
  </div>`

const beforeLines = facts.sample.before.split('\n')
const removedLines = new Set([0, 2, 3, beforeLines.length - 1])
const before = beforeLines.map((line, index) => removedLines.has(index)
  ? `<span class="removed-line">${esc(line)}</span>` : esc(line)).join('\n')
const afterBlocks = facts.sample.after.split('\n\n')
const tableLines = afterBlocks.slice(1).join('\n').split('\n').filter(line => line.trim().startsWith('|'))
const cells = line => line.split('|').slice(1, -1).map(cell => cell.trim())
const table = tableLines.length ? `<table><thead><tr>${cells(tableLines[0]).map(cell => `<th>${esc(cell)}</th>`).join('')}</tr></thead><tbody>${tableLines.slice(2).map(line => `<tr>${cells(line).map(cell => `<td>${esc(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>` : ''

const css = `
.directory-layout{height:928px;display:flex;background:var(--surface)}
.profile-directory{width:280px;flex:none;border-right:1px solid var(--line);display:flex;flex-direction:column;background:#FAFBFC;overflow:hidden}
.directory-head{padding:20px 18px 0;flex:none}
.directory-title{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:600;line-height:24px;margin-bottom:14px}
.directory-title .directory-total{font-size:13px;color:var(--muted);font-weight:450;margin-left:auto}
.directory-head .search{background:var(--surface);font-size:13px;height:36px}
.directory-tabs{height:46px;display:flex;align-items:center;gap:22px;font-size:13px;border-bottom:1px solid var(--line);color:var(--muted)}
.directory-tabs span{height:46px;display:flex;align-items:center;position:relative}
.directory-tabs .active{color:var(--ink);font-weight:600}
.directory-tabs .active:after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:var(--ink)}
.directory-scroll{flex:1;overflow:hidden;padding:5px 10px 16px;position:relative}
.directory-scroll:after{content:'';position:absolute;right:3px;top:14px;width:3px;height:344px;background:#CED5DB;border-radius:3px}
.directory-group h3{height:34px;margin:0 8px;display:flex;align-items:center;font-size:13px;font-weight:550;color:var(--muted)}
.directory-group h3 span{margin-left:auto;font-size:13px;font-weight:450;font-variant-numeric:tabular-nums;color:#63717D}
.directory-group+.directory-group{border-top:1px solid var(--line);margin-top:8px;padding-top:5px}
.directory-item{height:35px;display:flex;align-items:center;gap:10px;padding:0 9px;border-radius:5px;position:relative;font-size:14px;color:#48545F;white-space:nowrap}
.directory-item .object-icon{width:23px;height:23px;border:0;background:transparent;border-radius:0}
.directory-item .object-icon .icon{width:17px;height:17px}
.directory-item>span:not(.object-icon){overflow:hidden;text-overflow:ellipsis}
.directory-item>.icon{width:13px;height:13px;margin-left:auto;color:#586570}
.directory-item.current{background:var(--selected);color:var(--ink);font-weight:600}
.directory-item.current:before{content:'';position:absolute;left:0;top:10px;bottom:10px;width:3px;border-radius:3px;background:var(--ink)}
.directory-footer{height:44px;flex:none;border-top:1px solid var(--line);display:flex;align-items:center;gap:7px;padding:0 18px;font-size:13px;color:var(--muted)}
.directory-footer .icon{width:13px;height:13px}
.profile-detail{width:1056px;min-width:0;display:flex;flex-direction:column;overflow:hidden;background:var(--surface)}
.detail-hero{padding:22px 32px 20px;flex:none}
.detail-location{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted);height:20px}
.detail-location .icon{width:12px;height:12px;color:#63717D}
.detail-title-row{margin-top:10px;display:flex;align-items:center;gap:11px}
.detail-title-row h2{font-size:20px;font-weight:650;line-height:30px;letter-spacing:-.2px;white-space:nowrap}
.detail-title-row .object-icon{width:32px;height:32px}
.detail-title-row .object-icon .icon{width:19px;height:19px}
.detail-actions{margin-left:auto;display:flex;gap:8px}
.detail-actions .btn{height:36px}
.detail-description{margin-top:10px;font-size:14px;line-height:24px;color:var(--muted)}
.detail-attributes{display:flex;align-items:center;gap:27px;margin-top:17px;font-size:13px;line-height:24px;white-space:nowrap}
.detail-attributes>div{display:flex;align-items:center;gap:9px}
.attribute-label{color:var(--muted)}
.detail-attributes code{font:450 13px/24px ui-monospace,SFMono-Regular,Consolas,monospace;color:#53616D}
.detail-attributes .format{font-size:13px;line-height:22px;padding:0 6px}
.detail-attributes .builtin{font-size:13px}
.governance-on{display:inline-flex;align-items:center;gap:4px;color:var(--green);font-size:13px}
.governance-on .icon{width:14px;height:14px}
.detail-rule-section{flex:none;border-top:1px solid var(--line);padding:20px 32px 17px}
.detail-section-head{height:26px;display:flex;align-items:center;gap:12px}
.detail-section-head h3{font-size:14px;line-height:24px;font-weight:600}
.detail-section-head .section-meta{font-size:13px;color:var(--muted)}
.detail-section-head .readonly-note{margin-left:auto;font-size:13px}
.rule-table{margin-top:12px;width:100%}
.rule-columns,.rule-line{display:grid;grid-template-columns:270px minmax(0,1fr) 140px;align-items:center;column-gap:14px}
.rule-columns{height:30px;color:var(--muted);font-size:13px;background:var(--fog);padding:0 12px}
.rule-columns span:last-child{padding-left:6px}
.rule-line{height:38px;padding:0 12px;font-size:14px}
.rule-name{display:flex;align-items:center;gap:13px;white-space:nowrap}
.rule-number{font-size:12px;color:#687581;font-variant-numeric:tabular-nums;width:18px}
.rule-purpose{font-size:13px;line-height:22px;color:#697580;white-space:nowrap}
.rule-value{display:flex;align-items:center;gap:10px;padding-left:6px;font-size:13px}
.value-state{display:inline-flex;align-items:center;gap:5px;color:var(--ink)}
.value-state .icon{width:14px;height:14px;color:var(--green)}
.rule-value strong{font:600 15px/24px var(--font)}
.parameter-line{border-top:1px solid var(--line);margin-top:7px;padding-top:5px;height:43px}
.rule-config-link{height:24px;display:flex;align-items:center;justify-content:flex-end;padding-right:12px}
.rule-config-link .quiet-link{height:24px;font-size:13px}
.detail-preview{border-top:1px solid var(--line);padding:19px 32px 0;flex:1;min-height:0}
.detail-preview .detail-section-head{margin-bottom:15px}
.preview-file{margin-left:auto;display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted)}
.preview-file .icon{width:14px;height:14px}
.preview-pair{display:grid;grid-template-columns:1fr 1fr;gap:0}
.preview-column{min-width:0}
.preview-column:first-child{padding-right:25px}
.preview-column+.preview-column{padding-left:25px;border-left:1px solid var(--line)}
.preview-label{display:flex;align-items:center;gap:8px;margin-bottom:11px;font-size:13px;color:var(--muted)}
.preview-label .icon{width:14px;height:14px}
.preview-column pre{margin:0;font:450 13px/20px var(--font);color:#5C6873;white-space:pre-wrap;overflow-wrap:anywhere}
.removed-line{color:#895C55;text-decoration:line-through;text-decoration-color:#C8A9A5;background:#FCF5F3}
.cleaned-output{font-size:14px;line-height:25px;color:var(--ink)}
.cleaned-output p{margin-top:1px}
.cleaned-output table{border-collapse:collapse;width:100%;margin-top:18px;font-size:13px;line-height:23px;text-align:left}
.cleaned-output th{font-weight:550;background:var(--fog)}
.cleaned-output th,.cleaned-output td{padding:8px 10px;border:1px solid var(--line)}
.cleaned-output th:first-child{width:36%}
`

const content = `
<div class="directory-layout">
  <aside class="profile-directory" aria-label="治理模板目录">
    <div class="directory-head">
      <div class="directory-title">模板目录<span class="directory-total">${profiles.length} 个模板</span></div>
      ${search('搜索模板名称')}
      <div class="directory-tabs"><span class="active">内置模板</span><span>自定义配置</span></div>
    </div>
    <div class="directory-scroll">${directory}</div>
    <div class="directory-footer">${icon('lock')}内置模板可复制为自定义配置</div>
  </aside>
  <article class="profile-detail" aria-label="${esc(selected.name)}">
    <header class="detail-hero">
      <div class="detail-location"><span>${esc(selected.group)}</span>${icon('chevron-right')}<span>配置详情</span></div>
      <div class="detail-title-row">
        ${objectIcon(selected)}<h2>${esc(selected.name)}</h2>
        <div class="detail-actions">${btn('导出', 'download')}${btn('复制为自定义', 'copy', 'solid')}</div>
      </div>
      <p class="detail-description">${esc(selected.description)}</p>
      <div class="detail-attributes">
        <div><span class="attribute-label">输入格式</span>${formats(selected)}</div>
        <div><span class="attribute-label">治理清洗</span><span class="governance-on">${icon('check')}已启用</span></div>
        <div><span class="attribute-label">配置标识</span><code>${esc(selected.key)}</code></div>
        <div>${builtin()}<span class="attribute-label">只读</span></div>
      </div>
    </header>
    <section class="detail-rule-section">
      <div class="detail-section-head"><h3>规则与参数</h3><span class="section-meta">${ruleEntries.length} 条清洗规则 · ${parameterEntries.length} 项参数</span><span class="readonly-note">${icon('lock')}复制后可调整</span></div>
      <div class="rule-table" role="table" aria-label="模板明确设置的管线参数">
        <div class="rule-columns" role="row"><span role="columnheader">规则</span><span role="columnheader">作用</span><span role="columnheader">状态</span></div>
        ${ruleEntries.map((entry, index) => fieldRow(entry, index)).join('')}
        ${parameterEntries.map((entry, index) => fieldRow(entry, ruleEntries.length + index, true)).join('')}
      </div>
      <div class="rule-config-link"><button type="button" class="quiet-link">${icon('braces')}查看配置 JSON</button></div>
    </section>
    <section class="detail-preview">
      <div class="detail-section-head"><h3>清洗前后摘录</h3><span class="preview-file">${icon('file-markdown')}${esc(facts.sample.filename)}</span></div>
      <div class="preview-pair">
        <div class="preview-column"><div class="preview-label">清洗前</div><pre>${before}</pre></div>
        <div class="preview-column"><div class="preview-label">清洗后</div><div class="cleaned-output"><p>${esc(afterBlocks[0])}</p>${table}</div></div>
      </div>
    </section>
  </article>
</div>`

write('b-directory', '治理配置 · B 目录分栏', css, content)
