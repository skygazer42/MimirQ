const { facts, esc, icon, file, button, select, modes, header, write } = require('./parts.cjs')

const css = `
.wizard-steps{height:98px;flex:none;border-bottom:1px solid var(--line);background:var(--fog)}
.steps-inner{width:960px;height:100%;margin:0 auto;display:flex;align-items:center;gap:28px}
.step{display:flex;align-items:center;gap:12px;flex:none;color:var(--muted)}
.step-number{height:28px;width:28px;display:grid;place-items:center;border:1px solid #C4CCD3;border-radius:50%;font-size:12px;font-weight:600;background:var(--surface)}
.step-number .icon{width:14px;height:14px}.step.complete{color:var(--ink)}.step.complete .step-number{background:var(--selected);border-color:var(--selected)}
.step.current{color:var(--ink)}.step.current .step-number{background:var(--ink);border-color:var(--ink);color:var(--white)}
.step strong{display:block;font-size:13px;font-weight:600}.step small{display:block;margin-top:1px;font-size:11px;color:var(--muted)}
.step-line{height:1px;background:#CDD4DA;flex:1;min-width:30px}.step-line.done{background:#7C8792}
.wizard-content{width:960px;margin:0 auto;padding:27px 0 20px;flex:1;min-height:0}
.wizard-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:19px}
.wizard-title h2{font-size:22px;font-weight:650;line-height:30px;letter-spacing:-.3px}.wizard-title p{font-size:13px;color:var(--muted);margin-top:4px}.wizard-title>span{font-size:12px;color:var(--muted)}
.batch-summary{display:grid;grid-template-columns:180px 1fr;gap:24px;padding:16px 0 17px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.batch-label{display:flex;flex-direction:column;align-items:flex-start;gap:5px}.batch-label strong{font-size:13px}.batch-label>span{font-size:12px;color:var(--muted)}
.batch-files{min-width:0}.batch-file-heading{display:flex;align-items:center;justify-content:space-between;height:23px;margin-bottom:7px}.batch-file-heading>span{font-size:12px;color:var(--muted)}
.batch-file-grid{display:grid;grid-template-columns:1fr 1fr;column-gap:25px;row-gap:7px}.batch-file{min-width:0;display:flex;align-items:center;gap:15px;height:23px}.batch-file .file-name{font-size:12px;flex:1}.batch-file .file-name .icon{width:15px;height:17px}.batch-file>span{font-size:11px;color:var(--muted);white-space:nowrap}
.summary-note{font-size:11px;color:var(--muted);margin-top:8px}
.form-section{padding-top:23px}.section-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.section-heading h3{font-size:14px;font-weight:600}.section-heading>span{font-size:12px;color:var(--muted)}
.wizard-content .mode-options{gap:0}.wizard-content .mode-option{width:33.333%;padding:15px 18px 16px;border:0;border-bottom:1px solid #CDD4DA;border-right:1px solid #E1E6EA;border-radius:0;background:transparent;min-height:87px;gap:11px}.wizard-content .mode-option:first-child{border-left:1px solid #E1E6EA}.wizard-content .mode-option.selected{background:var(--selected);border-bottom:2px solid var(--ink);padding-bottom:15px}.wizard-content .mode-option strong{font-size:14px}.wizard-content .mode-option p{font-size:12px;margin-top:5px}.wizard-content .mode-option .radio{margin-top:4px}
.mode-result{height:31px;display:flex;align-items:center;gap:8px;margin-top:9px;font-size:12px;color:var(--muted)}.mode-result .icon{width:14px;height:14px;color:#74818C}.mode-result strong{font-weight:500;color:var(--ink)}
.parser-section{padding-top:19px}.parser-fields{display:grid;grid-template-columns:1fr 1fr;column-gap:28px}.parser-field .select{height:38px}.field-help{font-size:11px;color:var(--muted);margin-top:6px}.parser-field .field-label{margin-bottom:7px}
.dataset-row{display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--line);padding:15px 0;margin-top:5px}.dataset-row .field-label{width:109px;margin:0;font-size:13px;color:var(--ink)}.dataset-row .select{width:306px;height:36px}.dataset-row>span{margin-left:auto;font-size:12px;color:var(--muted)}
.advanced-row{height:53px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.advanced-toggle{display:flex;align-items:center;gap:10px;font-size:13px;font-weight:500}.advanced-toggle .icon{width:14px;height:14px;color:var(--muted)}.advanced-row>span{font-size:12px;color:var(--muted)}
.wizard-footer{height:76px;flex:none;border-top:1px solid var(--line);background:var(--fog)}.wizard-footer-inner{width:960px;height:100%;margin:0 auto;display:flex;align-items:center;gap:18px}.footer-summary{margin-left:auto;text-align:right;font-size:12px;color:var(--muted)}.footer-summary strong{display:block;font-size:13px;color:var(--ink);font-weight:550}.wizard-footer .solid{height:40px;padding:0 20px}.wizard-footer .back{padding-left:0}
`

const step = (number, title, subtitle, cls = '') => `<div class="step ${cls}"><span class="step-number">${cls === 'complete' ? icon('check') : number}</span><div><strong>${title}</strong><small>${subtitle}</small></div></div>`

const content = `${header()}
<div class="wizard-steps"><div class="steps-inner">
  ${step(1, '来源与文件', '已添加 12 个文件', 'complete')}<span class="step-line done"></span>
  ${step(2, '处理设置', '选择执行终点与解析方式', 'current')}<span class="step-line"></span>
  ${step(3, '确认提交', '核对本次入库内容')}
</div></div>
<div class="wizard-content">
  <div class="wizard-title"><div><h2>处理设置</h2><p>选择本批文件需要处理到哪一步。</p></div><span>第 2 步，共 3 步</span></div>
  <div class="batch-summary">
    <div class="batch-label"><strong>${esc(facts.source)}</strong><span>${facts.documents.length} 个文件 · ${facts.totalSize}</span><button class="text-action" type="button">更换来源${icon('chevron-down')}</button></div>
    <div class="batch-files"><div class="batch-file-heading"><span>已添加文件</span><button class="text-action" type="button">管理文件${icon('arrow-right')}</button></div><div class="batch-file-grid">${facts.documents.slice(0,4).map(doc=>`<div class="batch-file">${file(doc)}<span>${doc.size}</span></div>`).join('')}</div><div class="summary-note">另有 8 个文件</div></div>
  </div>
  <section class="form-section"><div class="section-heading"><h3>执行终点</h3><span>本批文件采用相同的处理方式</span></div>${modes()}<div class="mode-result">${icon('arrow-right')}<span>登记文件 → 提取正文<strong>，本次不建立检索索引</strong></span></div></section>
  <section class="parser-section"><div class="section-heading"><h3>解析设置</h3></div><div class="parser-fields"><div class="parser-field"><label class="field-label">解析器</label>${select(facts.parser,'parsing')}<p class="field-help">根据文件类型选择解析器</p></div><div class="parser-field"><label class="field-label">重复文件识别</label>${select(facts.dedup,'copy')}<p class="field-help">按文件内容识别已存在的文档</p></div></div></section>
  <div class="dataset-row"><label class="field-label">目标数据集</label>${select(facts.dataset,'dataset')}<span>${esc(facts.ingestMode)}</span></div>
  <div class="advanced-row"><button type="button" class="advanced-toggle">${icon('chevron-right')}高级设置</button><span>导入选项、切块与索引参数</span></div>
</div>
<footer class="wizard-footer"><div class="wizard-footer-inner">${button('上一步：来源与文件','arrow-left','quiet back')}<div class="footer-summary"><strong>下一步核对文件和设置</strong><span>确认后${esc(facts.primaryAction)}</span></div>${button('下一步：确认提交','arrow-right','solid')}</div></footer>`

write('b-wizard', 'B · 分步向导', css, content)
