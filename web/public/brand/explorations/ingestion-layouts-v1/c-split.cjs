const { facts, esc, icon, file, button, select, status, sourceTabs, modes, header, submit, write } = require('./parts.cjs')

const css = `
.split-workspace{height:852px;display:grid;grid-template-columns:minmax(0,1fr) 354px;min-height:0}
.files-pane{min-width:0;padding:20px 28px 22px;display:flex;flex-direction:column}
.sources-line{height:44px;flex:none;border-bottom:1px solid var(--line);display:flex;align-items:stretch}
.sources-line .source-tabs{height:44px;gap:25px}
.sources-line .source-tab{height:44px;position:relative}
.sources-line .source-tab.active:after{content:'';position:absolute;left:0;right:0;bottom:-1px;height:2px;background:var(--ink)}
.drop-band{height:104px;flex:none;margin:14px 0 16px;border:1px dashed #BFC7CF;border-radius:6px;background:#F5F7F8;display:flex;align-items:center;gap:16px;padding:18px 20px}
.drop-band .drop-icon{width:42px;height:42px;background:#E9EDF0}
.drop-copy{min-width:0}.drop-copy strong{display:block;font-size:14px;font-weight:600;line-height:22px}
.drop-copy p{font-size:13px;line-height:21px;color:var(--muted);margin-top:4px}
.drop-band>.btn{margin-left:auto;flex:none}
.queue-top{height:44px;flex:none;display:flex;align-items:center;gap:10px}
.queue-top h2{font-size:15px;line-height:24px;font-weight:600}
.queue-top .queue-size{font-size:13px;color:var(--muted);margin-left:2px}
.queue-top .text-action{margin-left:auto;font-size:13px}
.queue-top .count{font-size:13px;background:#E8ECEF}
.file-table{flex:none;font-variant-numeric:tabular-nums}
.file-table col:first-child{width:34px}.file-table col:nth-child(3){width:100px}.file-table col:nth-child(4){width:100px}.file-table col:nth-child(5){width:104px}.file-table col:last-child{width:34px}
.file-table thead{background:#F0F3F5}.file-table th{height:36px;font-size:13px;font-weight:500;padding:0 10px}
.file-table th:first-child{padding:0 0 0 10px}.file-table td{height:42px;padding:0 10px;font-size:13px}
.file-table td:first-child{padding:0 0 0 10px;color:var(--muted);font-size:13px}
.file-table td:last-child,.file-table th:last-child{padding:0}
.file-table .file-name{font-size:13px;gap:10px}.file-table .status{font-size:13px}
.file-table .format{font-size:13px;color:var(--muted)}.file-table .size{text-align:right;color:var(--muted);padding-right:22px}
.file-table .remove{height:32px;width:32px;display:grid;place-items:center;color:#76828D}.file-table .remove .icon{width:14px;height:14px}
.files-note{margin-top:18px;display:flex;gap:7px;align-items:center;color:var(--muted);font-size:13px;line-height:20px}
.files-note .icon{width:14px;height:14px}
.settings-pane{border-left:1px solid var(--line);background:#F0F3F5;padding:24px 24px 22px;min-width:0;display:flex;flex-direction:column}
.settings-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}
.settings-title h2{font-size:15px;line-height:24px;font-weight:600}.settings-title>.icon{width:17px;height:17px;color:var(--muted)}
.settings-section{padding:0 0 22px}
.settings-pane .field-label{font-size:13px;line-height:20px;color:#4D5A66;margin-bottom:10px;font-weight:550}
.settings-pane .select{height:38px;font-size:13px;background:#FAFBFC;border-color:#CFD6DD}
.settings-pane .mode-options{flex-direction:column;gap:0;margin:0 -8px}
.settings-pane .mode-option{border:0;border-radius:5px;background:none;padding:9px;min-height:60px;align-items:flex-start;gap:10px}
.settings-pane .mode-option.selected{background:#E6EAED}
.settings-pane .mode-option strong{font-size:14px;line-height:22px;font-weight:550}
.settings-pane .mode-option p{font-size:13px;line-height:20px;margin-top:2px;white-space:nowrap;color:#52606C}
.settings-pane .radio{margin-top:3px;width:15px;height:15px}
.settings-section.execution{border-top:1px solid #D7DDE2;padding:20px 0 0}
.process-settings{display:grid;gap:16px;padding:23px 0}
.settings-section.advanced{border-top:1px solid #D7DDE2;padding:16px 0}
.settings-section.compact{padding:18px 0}
.inline-field{display:flex;align-items:center;justify-content:space-between;gap:12px}
.inline-field .field-label{margin-bottom:0}
.inline-field .small-select{width:156px;height:36px}
.setting-detail{font-size:13px;line-height:21px;color:var(--muted);margin-top:10px}
.dedup-value{display:flex;align-items:center;gap:7px;font-size:13px}.dedup-value .icon{width:15px;height:15px;color:var(--muted)}
.advanced-entry{display:flex;align-items:center;justify-content:space-between;height:28px;font-size:13px;font-weight:550}
.advanced-entry .icon{height:14px;width:14px;color:var(--muted)}
.advanced-details{font-size:13px;color:var(--muted);line-height:21px;margin-top:7px}
.settings-tail{display:flex;align-items:center;gap:7px;margin-top:auto;padding-top:18px;color:var(--muted);font-size:13px;line-height:21px}
.settings-tail .icon{width:14px;height:14px}
`

const rows = facts.documents.map((doc, index) => `<tr>
  <td>${String(index + 1).padStart(2, '0')}</td>
  <td>${file(doc)}</td>
  <td class="format">${esc(doc.format)}</td>
  <td class="size">${esc(doc.size)}</td>
  <td>${status(doc.status)}</td>
  <td><button type="button" class="remove" aria-label="移除 ${esc(doc.name)}">${icon('x')}</button></td>
</tr>`).join('')

const content = `${header()}
<div class="split-workspace">
  <section class="files-pane" aria-label="导入文件">
    <div class="sources-line">${sourceTabs()}</div>
    <div class="drop-band">
      <span class="drop-icon">${icon('upload-cloud')}</span>
      <div class="drop-copy"><strong>拖拽文件到这里，或从电脑选择</strong><p>支持 PDF、Word、表格等文件，单个文件最大 ${esc(facts.maxFileSize)}</p></div>
      ${button('添加文件', 'plus')}
    </div>
    <div class="queue-top"><h2>待提交文件</h2><span class="count">${facts.documents.length}</span><span class="queue-size">共 ${esc(facts.totalSize)}</span><span class="text-action">${icon('trash2')}清空</span></div>
    <table class="file-table" aria-label="待提交文件清单">
      <colgroup><col><col><col><col><col><col></colgroup>
      <thead><tr><th>#</th><th>文件名称</th><th>格式</th><th class="size">大小</th><th>状态</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </section>
  <aside class="settings-pane" aria-label="入库配置">
    <div class="settings-title"><h2>入库配置</h2></div>
    <section class="settings-section">
      <span class="field-label">目标数据集</span>
      ${select(facts.dataset, 'dataset')}
    </section>
    <section class="settings-section execution">
      <span class="field-label">处理方式</span>
      ${modes()}
    </section>
    <div class="process-settings">
      <div class="inline-field"><span class="field-label">解析器</span>${select(facts.parser, '', 'small-select')}</div>
      <div class="inline-field"><span class="field-label">重复处理</span>${select(facts.dedup, '', 'small-select')}</div>
    </div>
    <section class="settings-section advanced">
      <div class="advanced-entry"><span>高级设置</span>${icon('chevron-down')}</div>
      <p class="advanced-details">导入方式、标签与目录</p>
    </section>
  </aside>
</div>
${submit()}`

write('c-split', 'C · 文件与配置分栏', css, content)
