const { selected, icon, btn, select, fileIcon, state, review, header, markdown, paper, write, esc } = require('./parts.cjs')

const css = `
.b-scope{border:0;background:transparent;width:148px;padding:0;color:var(--muted)}
.b-document{height:68px;flex:none;display:flex;align-items:center;gap:20px;padding:0 28px;border-bottom:1px solid var(--line)}
.b-file{display:flex;align-items:center;gap:11px;min-width:310px}.b-file>.icon{width:26px;height:26px}.b-file strong{display:block;font-size:15px}.b-file small{font-size:12px;color:var(--muted)}.b-file>.icon:last-child{width:13px;height:13px;color:var(--muted);margin-left:10px}
.b-file-actions{display:flex;align-items:center;gap:9px;margin-left:auto}.b-file-actions label{font-size:12px;color:var(--muted)}.b-file-actions .select{width:122px}.b-divider{height:20px;width:1px;background:var(--line);margin:0 6px}
.b-workspace{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr}.b-source,.b-result{min-width:0;display:flex;flex-direction:column;overflow:hidden}.b-source{border-right:1px solid var(--line)}
.b-toolbar{height:48px;flex:none;display:flex;align-items:center;gap:8px;padding:0 20px;border-bottom:1px solid var(--line);background:var(--fog)}.b-toolbar>strong{font-size:13px;font-weight:550}.b-toolbar>.icon{width:15px;color:var(--muted)}.b-toolbar .btn.square{width:26px;height:26px;border-color:transparent;background:transparent}.b-pages{font-size:12px;display:flex;align-items:center;gap:9px;margin-left:auto}.b-pages b{font-weight:550;color:var(--ink)}.b-zoom{font-size:12px;color:var(--muted);padding:0 3px}.b-toolbar .tabs{gap:22px;height:48px}.b-toolbar .tabs>span{font-size:13px}.b-toolbar .tabs .icon{width:14px;height:14px}
.b-source-body{flex:1;min-height:0;background:#ECEFF1;padding:28px 20px;display:flex;align-items:flex-start;justify-content:center;overflow:hidden;position:relative}.b-source-body .paper{width:480px;min-height:678px;padding:30px 37px 42px}.b-source-body:after{content:'原始文件 · 第 3 页';position:absolute;bottom:14px;left:0;right:0;text-align:center;font-size:11px;color:var(--muted)}
.b-result-body{flex:1;min-height:0;padding:27px 36px 20px;overflow:hidden}.b-result-body .markdown h2{margin-bottom:17px}.b-result-body .markdown h3{margin-top:20px}.b-result-body .markdown h2+h3{margin-top:0}.b-result-body .markdown p{font-size:14px;line-height:26px}.b-result-body .markdown th,.b-result-body .markdown td{padding:8px 10px}.b-result-body .markdown tbody tr:nth-child(1){background:var(--amber-soft)}.b-result-body .markdown blockquote{margin-top:16px}
.b-result-status{height:38px;flex:none;border-top:1px solid #EAE0C7;background:#FCFAF5;display:flex;align-items:center;gap:7px;padding:0 22px;font-size:12px;color:var(--amber)}.b-result-status>.icon{width:14px;height:14px}.b-result-status>span:last-child{margin-left:auto;font-weight:550}
.b-footer{height:54px;flex:none;display:flex;align-items:center;gap:18px;padding:0 28px;border-top:1px solid var(--line);background:var(--fog);font-size:12px;color:var(--muted)}.b-footer .b-total{display:flex;align-items:center;gap:8px}.b-total>.icon{width:15px;height:15px}.b-footer b{color:var(--ink);font-weight:550}.b-footer .btn{margin-left:auto}.b-footer .b-meta{display:flex;align-items:center;gap:18px}
`
const content = header(select('设备资料','folder','b-scope'),btn('解析设置','settings2','quiet')) + `
<div class="b-document">
  <div class="b-file">${fileIcon(selected)}<div><strong>${esc(selected.name)}</strong><small>2.4 MB · 18 页 · 设备资料</small></div>${icon('chevron-down')}</div>
  ${state(selected)}${review()}
  <div class="b-file-actions"><label>解析器</label>${select('Docling')}${btn('重新解析','rotate-ccw')}<i class="b-divider"></i>${btn('','chevron-left','square')}<span class="muted num">1 / 12</span>${btn('','chevron-right','square')}</div>
</div>
<div class="b-workspace">
  <section class="b-source">
    <div class="b-toolbar">${icon('file-pdf','file-pdf')}<strong>原文 PDF</strong><div class="b-pages">${btn('','chevron-left','square')}<b class="num">3</b><span class="muted">/ 18 页</span>${btn('','chevron-right','square')}<i class="b-divider"></i>${btn('','zoom-out','square')}<span class="b-zoom num">100%</span>${btn('','zoom-in','square')}</div></div>
    <div class="b-source-body">${paper()}</div>
  </section>
  <section class="b-result">
    <div class="b-toolbar"><div class="tabs"><span class="active">Markdown</span><span>内容块 <em>74</em></span><span>提取资源</span></div><span class="spacer"></span>${btn('','code','square')}${btn('','copy','square')}${btn('','download','square')}</div>
    <div class="b-result-body">${markdown()}</div>
    <div class="b-result-status">${icon('alert-circle')}第 3 页 · 表格合并单元格待核对<span>定位原文 ${icon('arrow-up-right')}</span></div>
  </section>
</div>
<footer class="b-footer"><span class="b-total">${icon('blocks')}<b class="num">74</b> 个内容块</span><div class="b-meta"><span>12 标题</span><span>4 表格</span><span>6 图片</span><span>耗时 12.6 秒</span></div>${btn('继续数据治理','arrow-right')}</footer>
`
write('b-compare','B · 原文对照',css + '.b-source-body .paper{font-size:13px}',content)
