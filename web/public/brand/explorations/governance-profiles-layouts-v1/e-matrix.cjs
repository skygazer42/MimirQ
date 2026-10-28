const {
  profiles, selected, esc, icon, btn, select, formats, objectIcon,
  effectivePatch, write,
} = require('./parts.cjs')

const ids = ['kb_default','pdf_text','html_web','pdf_scanned_ocr','legal_compliance','code_repo']
const columns = ids.map(id => profiles.find(p => p.id === id))
const groups = [
  ['清理规则',[
    ['governance_remove_toc_lines','移除目录行'],
    ['governance_remove_noise_lines','清理噪声行'],
    ['governance_remove_common_lines','去重复页眉页脚'],
    ['governance_remove_boilerplate','移除网页样板'],
  ]],
  ['结构修复',[
    ['governance_unwrap_lines','合并异常换行'],
    ['governance_normalize_tables','规范 Markdown 表格'],
    ['governance_drop_duplicate_paragraphs','移除重复段落'],
    ['governance_strip_code_line_numbers','移除代码行号'],
  ]],
  ['脱敏与安全',[
    ['governance_pii_anonymize','个人信息脱敏'],
    ['governance_secrets_redact','密钥脱敏'],
  ]],
  ['链接与参数',[
    ['governance_normalize_urls','规范链接'],
    ['governance_normalize_urls_strip_tracking','移除跟踪参数'],
    ['governance_max_blank_lines','连续空行上限'],
    ['parse_fallback_enabled','解析兜底'],
    ['governance_noise_ratio_threshold','噪声比例阈值'],
  ]],
]
const value = (p, key) => {
  const patch = effectivePatch(p)
  if (!Object.hasOwn(patch,key)) return '<span class="not-set" aria-label="未覆盖，沿用默认">—</span>'
  const v = patch[key]
  if (v === true) return '<span class="matrix-yes" aria-label="启用">'+icon('check')+'</span>'
  if (v === false) return '<span class="matrix-no" aria-label="关闭">'+icon('x')+'</span>'
  if (key === 'governance_max_blank_lines') return '<span class="matrix-number">'+esc(v)+'<small>行</small></span>'
  if (key === 'governance_noise_ratio_threshold') return '<span class="matrix-number">'+esc(Math.round(v*100))+'<small>%</small></span>'
  return esc(v)
}
const head = columns.map(p => '<th class="template-column '+(p.key === selected.key ? 'current-column' : '')+'"><div class="column-heading">'+objectIcon(p)+'<h3>'+esc(p.shortName)+'</h3></div><div class="code-ref">'+esc(p.id)+'</div><div class="column-formats">'+formats(p)+'</div><div class="column-actions">'+btn('查看','','quiet')+btn('复制','copy')+'</div></th>').join('')
const rows = groups.map(([name,rules]) => '<tr class="matrix-group"><th colspan="7">'+esc(name)+'<span>'+rules.length+' 项</span></th></tr>'+rules.map(([key,label]) => '<tr class="matrix-rule"><th scope="row">'+esc(label)+'</th>'+columns.map(p => '<td class="'+(p.key === selected.key ? 'current-column' : '')+'">'+value(p,key)+'</td>').join('')+'</tr>').join('')).join('')

const css = `
.e-page{display:flex;flex:1;min-height:0;flex-direction:column}.e-toolbar{height:72px;display:flex;align-items:center;gap:12px;padding:0 24px;flex:none}.toolbar-title{font-size:13px;color:var(--muted)}.e-picker{width:224px;font-size:14px}.e-picker>.icon:first-child{color:var(--red);width:17px;height:17px}.compare-picker{width:180px}.toolbar-separator{height:18px;width:1px;background:var(--line);margin:0 4px}.e-toolbar .quiet-link{margin-left:auto}
.matrix-surface{flex:1;min-height:0;margin:0 24px 24px;display:flex;flex-direction:column;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface)}.comparison-table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:14px}.comparison-table col.rule-column{width:250px}.comparison-table th,.comparison-table td{border-right:1px solid #E6EAED}.comparison-table tr>:last-child{border-right:0}.comparison-table thead th{height:136px;padding:10px 12px 9px;vertical-align:top;border-bottom:1px solid var(--line);text-align:left;font-weight:450}.comparison-table thead th:first-child{padding:20px 20px}.matrix-title{font-size:16px;line-height:26px;font-weight:600}.matrix-intro{font-size:13px;line-height:22px;color:var(--muted);margin-top:6px}.matrix-intro span{display:inline-flex;align-items:center;gap:5px}.matrix-intro .icon{width:12px;height:12px}.column-heading{display:flex;align-items:center;gap:8px;height:28px}.column-heading .object-icon{height:26px;width:26px;border-radius:5px}.column-heading .object-icon .icon{height:16px;width:16px}.column-heading h3{font-size:14px;font-weight:600;line-height:22px;white-space:nowrap}.template-column .code-ref{font-size:11px;line-height:18px;margin-top:2px}.column-formats{height:25px;display:flex;align-items:center;margin-top:3px}.column-formats .format{font-size:12px;line-height:18px;padding:1px 5px}.column-actions{display:flex;align-items:center;gap:6px;margin-top:6px}.column-actions .btn{height:36px;padding:0 9px;font-size:13px}.column-actions .btn.quiet{padding-left:0;padding-right:6px}.column-actions .icon{height:13px;width:13px}.current-column{background:#F0F3F5}.comparison-table thead .current-column{box-shadow:inset 0 3px 0 var(--ink);background:#E9EEF1}
.matrix-group{height:26px;background:#F6F7F8}.matrix-group th{text-align:left;padding:0 20px;font-size:12px;font-weight:550;line-height:25px;border-bottom:1px solid var(--line);border-top:1px solid var(--line);color:var(--muted)}.matrix-group th>span{font-size:11px;font-weight:400;margin-left:9px;color:#63717D}.matrix-rule{height:36px}.matrix-rule th{text-align:left;padding:0 20px;font-size:14px;font-weight:450;border-bottom:1px solid #E9ECEF;line-height:24px}.matrix-rule td{height:36px;padding:0;text-align:center;vertical-align:middle;border-bottom:1px solid #E9ECEF;font-size:14px;line-height:24px}.matrix-rule:last-child th,.matrix-rule:last-child td{border-bottom:0}.matrix-yes,.matrix-no{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;line-height:1}.matrix-yes{color:var(--green)}.matrix-yes>.icon{width:17px;height:17px;stroke-width:2.1}.matrix-no{color:#687581}.matrix-no>.icon{width:14px;height:14px;stroke-width:1.5}.not-set{color:#687581}.matrix-number{font-variant-numeric:tabular-nums}.matrix-number small{font-size:12px;color:var(--muted);margin-left:5px}.matrix-foot{height:44px;flex:none;margin-top:auto;border-top:1px solid var(--line);padding:0 20px;display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--muted)}.matrix-legend{display:flex;align-items:center;gap:20px}.matrix-legend>span{display:flex;align-items:center;gap:6px}.matrix-legend .icon{width:14px;height:14px}.matrix-legend .yes{color:var(--green)}.matrix-legend .no{color:#63717D}.matrix-foot>span{display:flex;align-items:center;gap:5px}.matrix-foot>span>.icon{width:12px;height:12px}
`

const content = '<section class="e-page"><div class="e-toolbar"><span class="toolbar-title">当前模板</span>'+select(selected.shortName,selected.iconName,'e-picker')+'<span class="toolbar-separator"></span>'+select('常用模板 · 6 / '+profiles.length,'table2','compare-picker')+'<span class="quiet-link">'+icon('settings2')+'选择对比模板</span></div>'+
  '<div class="matrix-surface"><table class="comparison-table"><colgroup><col class="rule-column"><col><col><col><col><col><col></colgroup><thead><tr><th><h2 class="matrix-title">规则对照</h2><p class="matrix-intro">6 个常用内置模板<br><span>'+icon('lock')+'内置只读，复制后可修改</span></p></th>'+head+'</tr></thead><tbody>'+rows+'</tbody></table><footer class="matrix-foot"><div class="matrix-legend"><span class="yes">'+icon('check')+'启用</span><span class="no">'+icon('x')+'关闭</span><span><b class="not-set">—</b>未覆盖，沿用默认</span></div><span>'+icon('file-pdf')+'浅底列为当前模板 · PDF 文本版</span></footer></div></section>'

write('e-matrix','E · 规则矩阵',css,content)
