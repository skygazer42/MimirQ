const fs = require('node:fs')
const path = require('node:path')
const { html, facts, escape, icon, identity, btn } = require('./shared.cjs')

const highlighted = text => escape(text).replace(/数据权限|数据集|角色/g, word => `<mark>${word}</mark>`)
const hits = facts.hits.map((hit, index) => `
  <article class="hit ${index === 0 ? 'primary-hit' : ''}">
    <div class="hit-rank num">${String(hit.rank).padStart(2, '0')}</div>
    <div class="hit-main">
      <div class="hit-top">${identity(hit)}<div class="hit-tools"><span class="score num">${hit.score}</span><span class="score-caption">相关度</span>${icon('external-link')}</div></div>
      <div class="hit-location"><span>${escape(hit.path)}</span><span class="location-dot">·</span><span>第 ${escape(hit.clause)} 节</span><span class="chunk-id">${escape(hit.chunk)}</span></div>
      <p class="hit-copy">${highlighted(index === 0 ? hit.content : hit.excerpt)}</p>
      ${index === 0 ? `<div class="hit-terms">${hit.terms.map(term => `<span>${escape(term)}</span>`).join('')}<span class="hit-source">${icon('file-markdown')}查看完整文档${icon('arrow-right')}</span></div>` : ''}
    </div>
  </article>`).join('')

const body = `<div class="split-layout">
  <aside class="query-pane">
    <section class="query-section">
      <div class="section-heading"><h2>检索问题</h2>${icon('search')}</div>
      <div class="query-box">${escape(facts.query)}<span class="query-shortcut"><kbd>⌘</kbd><kbd>↵</kbd></span></div>
      ${btn('开始检索', 'arrow-right', 'solid run-button')}
    </section>
    <section class="settings-section">
      <h3>检索参数</h3>
      <label class="field-label">检索方式</label>
      <div class="field-value">${facts.mode}${icon('chevron-down')}</div>
      <div class="number-field"><span>返回数量 <small>Top K</small></span><span class="number-input num">${facts.topK}${icon('chevrons-up-down')}</span></div>
      <div class="threshold-label"><span>相似度阈值</span><strong class="num">${facts.threshold}</strong></div>
      <div class="slider"></div><div class="range-labels num"><span>0</span><span>1</span></div>
      <div class="rerank-row"><span>重排序</span><span class="toggle"></span></div>
      <div class="advanced-row"><span>${icon('settings2')}高级参数</span>${icon('chevron-right')}</div>
    </section>
    <section class="recent-section">
      <div class="recent-heading"><h3>最近检索</h3>${icon('history')}</div>
      ${facts.history.map(item => `<div class="recent-item"><span>${escape(item.query)}</span><time class="num">${escape(item.time)}</time></div>`).join('')}
    </section>
  </aside>
  <section class="results-pane">
    <header class="results-heading"><div><h2>检索结果</h2><span class="result-count num">${facts.hits.length}</span></div><p>按相关度排序<span class="heading-divider"></span>阈值 ${facts.threshold}</p></header>
    <div class="hits">${hits}</div>
    <footer class="index-strip"><span class="status">${icon('check-circle')}索引正常</span><span class="index-number num">${facts.documents} 份文档<span> / </span>${facts.chunks} 个分片</span><span class="audit-time">最近检查 ${facts.auditTime}</span><span class="text-action">索引详情${icon('chevron-right')}</span></footer>
  </section>
</div>`

const css = `
.split-layout{display:grid;grid-template-columns:304px minmax(0,1fr);height:872px}
.query-pane{height:872px;padding:27px 24px;background:var(--fog);border-right:1px solid var(--line);display:flex;flex-direction:column}
.section-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:13px}.section-heading h2,.results-heading h2{font-size:16px;line-height:26px;font-weight:650}.section-heading>.icon{width:17px;height:17px;color:#5C6874}
.query-box{position:relative;height:132px;padding:13px 14px 33px;border:1px solid #CDD4DB;border-radius:7px;background:white;font-size:14px;line-height:1.85;box-shadow:0 1px 2px #20262E03}.query-shortcut{position:absolute;bottom:10px;right:10px;display:flex;gap:3px}.query-shortcut kbd{height:19px;min-width:19px;text-align:center;padding:0 3px;background:#F6F7F8;border-color:#E2E6E9;font-size:12px;color:#5C6874}
.run-button{width:100%;height:39px;margin-top:10px;flex-direction:row-reverse;gap:9px;border-radius:6px;font-size:13px}
.settings-section{margin-top:29px}.settings-section h3,.recent-heading h3{font-size:13px;line-height:22px;font-weight:650}.settings-section h3{margin-bottom:17px}.field-label{display:block;color:var(--muted);font-size:12px;margin-bottom:6px}.settings-section .field-value{height:36px;background:white;border-color:#D8DEE4;border-radius:5px}.number-field{display:flex;align-items:center;justify-content:space-between;margin-top:17px;font-size:13px}.number-field small{margin-left:4px;font-size:12px;color:#5C6874}.number-input{height:32px;min-width:67px;display:flex;align-items:center;gap:21px;padding:0 9px;background:white;border:1px solid #D8DEE4;border-radius:5px;font-weight:600}.number-input .icon{width:12px;height:12px;color:#5C6874}.threshold-label{display:flex;align-items:center;justify-content:space-between;margin-top:19px;font-size:13px}.threshold-label strong{font-size:12px}.slider{margin:14px 5px 7px;height:3px}.slider:before{height:3px}.slider:after{width:13px;height:13px;border-width:2px}.range-labels{display:flex;justify-content:space-between;font-size:12px;color:#5C6874;line-height:14px}.rerank-row{display:flex;align-items:center;justify-content:space-between;margin-top:19px;font-size:13px}.advanced-row{display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--line);padding-top:17px;margin-top:20px;color:#596673;font-size:12px}.advanced-row>span{display:flex;align-items:center;gap:7px}.advanced-row .icon{width:14px;height:14px}.advanced-row>.icon{width:12px;height:12px}
.recent-section{margin-top:31px;border-top:1px solid var(--line);padding-top:18px}.recent-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.recent-heading>.icon{width:15px;height:15px;color:#5C6874}.recent-item{display:flex;align-items:center;gap:7px;padding:9px 0;font-size:13px;color:#596673;white-space:nowrap}.recent-item>span{overflow:hidden;text-overflow:ellipsis;flex:1}.recent-item time{font-size:12px;color:#5C6874;flex:none}
.results-pane{height:872px;min-width:0;display:flex;flex-direction:column;padding:20px 32px 16px;background:white}.results-heading{height:50px;flex:none;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #CCD3DA}.results-heading>div{display:flex;align-items:center;gap:9px}.result-count{font-size:12px;color:#5C6874;font-weight:500}.results-heading p{display:flex;align-items:center;gap:12px;font-size:12px;color:#5C6874}.heading-divider{width:1px;height:12px;background:var(--line)}
.hits{display:flex;flex-direction:column;min-height:0;flex:1}.hit{display:flex;gap:18px;flex:1;min-height:0;padding:16px 0;border-bottom:1px solid var(--line)}.hit:last-child{border-bottom:0}.primary-hit{flex:1.7;padding-top:20px}.hit-rank{font-size:12px;line-height:25px;font-weight:500;color:#5C6874;width:22px;flex:none}.primary-hit .hit-rank{color:var(--ink);font-weight:650}.hit-main{min-width:0;flex:1}.hit-top{display:flex;align-items:center;justify-content:space-between;gap:16px;line-height:24px}.hit-top .file-identity strong{font-size:14px;letter-spacing:.05px}.hit-tools{display:flex;align-items:center;gap:7px;flex:none}.hit-tools .score{font-size:13px}.score-caption{font-size:12px;color:#5C6874}.hit-tools>.icon{width:14px;height:14px;margin-left:17px;color:#5C6874}.hit-location{display:flex;align-items:center;gap:7px;font-size:12px;color:#5C6874;line-height:20px;margin-top:2px}.location-dot{color:#5C6874}.chunk-id{margin-left:auto;font-size:12px;color:#5C6874;letter-spacing:.1px}.hit-copy{font-size:13px;line-height:1.9;color:#55616D;margin-top:8px;letter-spacing:.02px;max-width:1035px}.primary-hit .hit-copy{font-size:14px;line-height:1.95;color:#404C58;margin-top:11px;max-width:56em}.hit-copy mark{background:#EBEEF1;padding:0 1px;border-radius:1px;color:#303D49}.hit-terms{display:flex;align-items:center;gap:14px;margin-top:13px;font-size:12px;color:#5C6874}.hit-terms>span:not(.hit-source):before{content:'#';color:#5C6874;margin-right:3px}.hit-source{margin-left:auto;display:flex;align-items:center;gap:5px;color:#596673;font-size:12px}.hit-source .icon{width:12px;height:12px}.index-strip{height:50px;flex:none;display:flex;align-items:center;gap:18px;border-top:1px solid #CCD3DA;background:#FAFBFC;padding:0 13px;border-radius:0 0 4px 4px}.index-strip .status{font-size:12px}.index-number{font-size:12px;color:#5C6874}.index-number>span{padding:0 6px;color:#5C6874}.audit-time{margin-left:auto;font-size:12px;color:#5C6874}.index-strip .text-action{font-size:12px;margin-left:3px}.index-strip .text-action .icon{width:12px;height:12px}
`

fs.writeFileSync(path.join(__dirname, 'a-split.html'), html({ title: 'A · 参数分栏', css, body }), 'utf8')
console.log('Created a-split.html: 1600 × 1000, split configuration and retrieval results.')
