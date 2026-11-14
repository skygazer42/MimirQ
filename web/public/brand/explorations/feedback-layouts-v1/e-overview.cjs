const { facts, stats, esc, icon, btn, select, search, rating, state, tabs, header, write } = require('./parts.cjs')

// E · 质量概览：先定位低分集中处，再沿连续表格核查原始记录。
const negatives = facts.feedback.filter(item => item.rating <= 2)
const issues = Object.entries(negatives.reduce((counts, item) => {
  counts[item.issue] = (counts[item.issue] || 0) + 1
  return counts
}, {})).sort((a, b) => b[1] - a[1])
const sources = [...new Set(facts.feedback.map(item => item.source))].map(name => ({
  name,
  total: facts.feedback.filter(item => item.source === name).length,
  negative: negatives.filter(item => item.source === name).length,
})).sort((a, b) => b.negative - a.negative)

function trendChart() {
  const labels = facts.trend.labels
  const chartTop = 10
  const chartBottom = 91
  const chartHeight = chartBottom - chartTop
  const origin = 27
  const interval = 54
  const y = count => chartBottom - count / 3 * chartHeight
  const grid = [0, 1, 2, 3].map(count => '<line x1="22" y1="' + y(count) + '" x2="390" y2="' + y(count) + '" stroke="#E7EBEF"/><text x="9" y="' + (y(count) + 4) + '" class="axis-num">' + count + '</text>').join('')
  const bars = labels.map((label, index) => {
    const x = origin + index * interval
    const total = facts.trend.total[index]
    const negative = facts.trend.negative[index]
    return '<rect x="' + x + '" y="' + y(total) + '" width="13" height="' + (chartBottom - y(total)) + '" rx="1" fill="#BEC7CF"/>' +
      (negative ? '<rect x="' + (x + 16) + '" y="' + y(negative) + '" width="13" height="' + (chartBottom - y(negative)) + '" rx="1" fill="#A74740"/>' : '') +
      '<text x="' + (x + 15) + '" y="111" text-anchor="middle" class="axis-label">' + label + '</text>'
  }).join('')
  return '<svg class="trend-chart" viewBox="0 0 405 118" role="img" aria-label="最近七天每日反馈量为 1、1、1、2、2、2、3；低分反馈量为 1、0、1、0、1、1、3。">' + grid + bars + '</svg>'
}

const css = `
.page-header .view-name{font-size:13px;color:var(--muted);padding-left:22px;border-left:1px solid var(--line);line-height:20px}
.overview{height:244px;flex:none;padding:0 28px;border-bottom:1px solid var(--line);background:var(--surface)}
.overview-summary{height:74px;display:flex;align-items:center;border-bottom:1px solid var(--line)}
.average{display:flex;align-items:baseline;gap:10px;padding-right:28px;border-right:1px solid var(--line)}
.average-label{font-size:13px;color:var(--muted)}.average strong{font-size:30px;font-weight:600;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-1px}.average small{font-size:13px;color:var(--muted);margin-left:-4px}
.summary-measures{display:flex;align-items:center;gap:30px;padding-left:28px}.measure{display:flex;align-items:baseline;gap:9px;font-size:13px;color:var(--muted);white-space:nowrap}.measure b{font-size:22px;line-height:1.2;color:var(--ink);font-weight:550;font-variant-numeric:tabular-nums}.measure.negative b{color:var(--red)}.measure small{font-size:12px;color:var(--muted);margin-left:-5px}.measure.positive b{color:var(--green)}
.loop-preview{margin-left:auto;display:flex;flex-direction:column;gap:4px;padding-left:24px;border-left:1px solid var(--line)}.loop-preview .loop-title{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px}.loop-title .icon{width:13px;height:13px}.loop-values{font-size:13px;display:flex;align-items:center;gap:15px;white-space:nowrap}.loop-values b{font-weight:600;padding-left:3px;font-variant-numeric:tabular-nums}.loop-values i{font-style:normal;color:var(--muted)}
.analytics{height:169px;display:grid;grid-template-columns:440px 410px minmax(0,1fr);gap:24px;padding-top:13px;padding-bottom:13px}.analytics-section{min-width:0}.analytics-section+.analytics-section{border-left:1px solid var(--line);padding-left:24px}.analysis-title{height:23px;display:flex;align-items:center;justify-content:space-between;gap:12px}.analysis-title h2{font-size:13px;line-height:20px;font-weight:550}.analysis-title .meta{font-size:12px;color:var(--muted);white-space:nowrap}.chart-legend{display:flex;align-items:center;gap:13px;font-size:12px;color:var(--muted)}.chart-legend span{display:flex;align-items:center;gap:5px}.chart-legend i{width:7px;height:7px;background:#BEC7CF;border-radius:1px}.chart-legend .low{background:var(--red)}.trend-chart{width:415px;height:118px;margin-top:1px;overflow:visible}.trend-chart text{font:450 12px var(--font);fill:var(--muted)}.trend-chart .axis-num{font-size:12px}.issue-bars{padding-top:5px;display:grid;gap:5px}.issue-bar{height:18px;display:flex;align-items:center;gap:12px;font-size:13px;line-height:18px}.issue-label{width:105px;flex:none}.bar-track{height:5px;flex:1;background:#F0F2F4}.bar-fill{display:block;height:100%;background:#BC7F78}.issue-bar:first-child .bar-fill,.issue-bar:nth-child(2) .bar-fill{background:var(--red)}.bar-count{font-variant-numeric:tabular-nums;width:14px;text-align:right;font-size:13px}.source-list{padding-top:7px;display:grid;gap:8px}.source-line{height:18px;display:flex;align-items:center;gap:12px;font-size:13px;line-height:18px}.source-name{width:83px;flex:none}.source-line .bar-track{background:#F0F2F4}.source-line .bar-fill{background:#9EAAA8}.source-ratio{width:41px;text-align:right;font-variant-numeric:tabular-nums;color:var(--muted);font-size:12px}.source-ratio b{color:var(--red);font-weight:550;font-size:13px}
.records-toolbar{height:88px;flex:none;padding:0 28px;background:var(--surface)}.records-top{height:44px;display:flex;align-items:center;border-bottom:1px solid var(--line);gap:16px}.records-top .tabs{height:44px;gap:24px}.records-actions{display:flex;align-items:center;gap:8px;margin-left:auto}.records-actions .btn{height:30px}.records-filters{height:44px;display:flex;align-items:center;gap:8px}.records-filters .search{width:300px;height:32px;background:var(--surface)}.records-filters .select{height:32px;min-width:128px}.records-filters .filter-order{margin-left:auto;min-width:130px}.records-filters .filter-action{height:32px;font-size:13px;padding:0 7px;color:var(--muted);display:flex;align-items:center;gap:6px}.filter-action .icon{width:14px;height:14px}
.record-table{padding:0 28px;flex:1;min-height:0;overflow:hidden}.record-table th{height:40px;vertical-align:middle;background:var(--fog);border-top:1px solid var(--line)}.record-table td{height:50px;vertical-align:middle;padding-top:4px;padding-bottom:4px;line-height:19px}.record-table td,.record-table th{padding-left:10px;padding-right:10px}.record-table th:first-child,.record-table td:first-child{padding-left:0;padding-right:12px;text-align:center}.record-table th:last-child,.record-table td:last-child{text-align:right;padding-right:8px}.record-table tbody tr:first-child{background:#FAFBFC}.record-table .question{font-size:13px;font-weight:550;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.record-table .reason{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:19px}.record-table .meta-line{display:block;font-size:12px;color:var(--muted);line-height:18px}.record-table .issue-name{font-size:13px;white-space:nowrap}.record-table .rating{gap:5px}.record-table .rating>span{font-size:12px}.record-table .state{font-size:13px}.row-open{height:30px;padding:0 5px;display:inline-flex;align-items:center;gap:7px;color:var(--muted);font-size:13px;white-space:nowrap}.row-open .icon{width:13px;height:13px}.row-open.primary{color:var(--ink)}.pagination{padding:0 28px;height:56px}.pagination .page-next{color:var(--muted)}
`

const summary = '<section class="overview" aria-label="质量概览">' +
  '<div class="overview-summary"><div class="average"><span class="average-label">平均评分</span><strong>' + stats.average + '</strong><small>/ 5</small></div>' +
  '<div class="summary-measures"><div class="measure"><span>反馈总量</span><b>' + stats.total + '</b></div><div class="measure negative"><span>低分</span><b>' + stats.negative + '</b><small>' + Math.round(stats.negative / stats.total * 100) + '%</small></div><div class="measure"><span>中立</span><b>' + stats.neutral + '</b></div><div class="measure positive"><span>正向</span><b>' + stats.positive + '</b></div></div>' +
  '<div class="loop-preview"><span class="loop-title">' + icon('workflow') + '反哺候选</span><span class="loop-values"><span>HardNeg <b>' + facts.loopCandidates.hardNegatives + '</b></span><span><i>三元组</i> <b>' + facts.loopCandidates.triplets + '</b></span><span><i>规则</i> <b>' + facts.loopCandidates.rules + '</b></span></span></div></div>' +
  '<div class="analytics"><section class="analytics-section"><div class="analysis-title"><h2>7 日反馈趋势</h2><div class="chart-legend"><span><i></i>全部</span><span><i class="low"></i>低分 1–2</span></div></div>' + trendChart() + '</section>' +
  '<section class="analytics-section"><div class="analysis-title"><h2>低分问题分布</h2><span class="meta">共 ' + stats.negative + ' 条</span></div><div class="issue-bars">' + issues.map(([name, count]) => '<div class="issue-bar"><span class="issue-label">' + esc(name) + '</span><span class="bar-track"><span class="bar-fill" style="width:' + (count / 2 * 100) + '%"></span></span><b class="bar-count">' + count + '</b></div>').join('') + '</div></section>' +
  '<section class="analytics-section"><div class="analysis-title"><h2>来源分布</h2><span class="meta">低分 / 全量</span></div><div class="source-list">' + sources.map(source => '<div class="source-line"><span class="source-name">' + esc(source.name) + '</span><span class="bar-track"><span class="bar-fill" style="width:' + (source.negative / source.total * 100) + '%"></span></span><span class="source-ratio"><b>' + source.negative + '</b> / ' + source.total + '</span></div>').join('') + '</div></section></div></section>'

const toolbar = '<section class="records-toolbar"><div class="records-top">' + tabs() + '<div class="records-actions">' + btn('批量归档', 'archive', 'quiet') + btn('导出反馈', '', 'quiet') + '</div></div><div class="records-filters">' + search() + select('全部评分') + select('全部反馈原因') + select('全部来源') + '<button type="button" class="filter-action">' + icon('plus') + '添加筛选</button>' + select('最新反馈', '', 'filter-order') + '</div></section>'

const rows = facts.feedback.slice(0, 10).map((item, index) => '<tr><td><span class="check-box"></span></td><td><div class="question">' + esc(item.question) + '</div><div class="reason">' + esc(item.reason) + '</div></td><td>' + rating(item) + '</td><td><span class="issue-name ' + (item.rating <= 2 ? 'negative' : '') + '">' + esc(item.issue) + '</span></td><td>' + esc(item.source) + '<span class="meta-line">' + esc(item.account) + '</span></td><td>' + state(item) + '</td><td>' + esc(item.time) + '<span class="meta-line">' + esc(item.id) + '</span></td><td><button type="button" class="row-open ' + (index === 0 ? 'primary' : '') + '">查看' + icon('arrow-up-right') + '</button></td></tr>').join('')
const table = '<section class="record-table" aria-label="反馈明细"><table><colgroup><col style="width:32px"><col style="width:528px"><col style="width:80px"><col style="width:134px"><col style="width:140px"><col style="width:116px"><col style="width:134px"><col style="width:116px"></colgroup><thead><tr><th><span class="check-box"></span></th><th>问题 / 用户反馈</th><th>评分</th><th>反馈原因</th><th>来源 / 用户</th><th>分析状态</th><th>反馈时间</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></section>'
const footer = '<footer class="pagination"><span>显示 1–10 条，共 ' + stats.total + ' 条反馈</span><div><span class="muted">10 条 / 页</span>' + icon('chevron-down') + '<span class="page-prev">' + icon('chevron-left') + '</span><b>1</b><span class="muted">/ 2</span><span class="page-next">' + icon('chevron-right') + '</span></div></footer>'

write('e-overview', 'E · 质量概览', css, header('<span class="view-name">质量概览</span>') + summary + toolbar + table + footer)
