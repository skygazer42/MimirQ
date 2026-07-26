import type { DatasetPrecheckSummary, Document } from '@/types'
import { formatFileSize } from '@/lib/utils'

import { stringifyForDisplay } from './document-signals'

export function escapeHtml(value: unknown): string {
  return stringifyForDisplay(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

export type ReportEvidenceRow = {
  actionLabel: string
  fileName: string
  fileSizeLabel: string
  fileType: string
  primaryRisk: string
  riskDescription: string
}

export function buildReportHtml({
  datasetLabel,
  totalDocs,
  readyRate,
  manualQueue,
  efficiency,
  latencyP90,
  selectedReason,
  documents,
  salesAuditSummary,
  salesPocCandidates,
  salesHighRiskFiles,
}: Readonly<{
  datasetLabel: string
  totalDocs: number
  readyRate: number
  manualQueue: number
  efficiency: string
  latencyP90: string
  selectedReason: string | null
  documents: Document[]
  salesAuditSummary?: DatasetPrecheckSummary | null
  salesPocCandidates?: ReportEvidenceRow[]
  salesHighRiskFiles?: ReportEvidenceRow[]
}>) {
  const rows = documents
    .slice(0, 12)
    .map(
      (document) => `
 <tr>
 <td>${escapeHtml(document.filename)}</td>
 <td>${escapeHtml(document.status || '-')}</td>
 <td>${escapeHtml(document.current_stage || '-')}</td>
 <td>${formatFileSize(document.file_size || 0)}</td>
 <td>${escapeHtml(document.error_message || '—')}</td>
 </tr>`
    )
    .join('')
  const findingRows = (salesAuditSummary?.findings ?? [])
    .slice(0, 8)
    .map(
      (item) => `
 <tr>
 <td>${escapeHtml(item.label)}</td>
 <td><span class="status-pill">${escapeHtml(item.severity)}</span></td>
 <td>${Number(item.count || 0).toLocaleString()}</td>
 <td>${escapeHtml(item.key)}</td>
 </tr>`
    )
    .join('')
  const pocRows = salesPocCandidates
    ?.slice(0, 8)
    .map(
      (item) => `
 <tr>
 <td>${escapeHtml(item.fileName)}</td>
 <td>${escapeHtml(item.fileType)}</td>
 <td>${escapeHtml(item.fileSizeLabel)}</td>
 <td>${escapeHtml(item.primaryRisk)}</td>
 <td><span class="action-pill">${escapeHtml(item.actionLabel)}</span></td>
 <td>${escapeHtml(item.riskDescription)}</td>
 </tr>`
    )
    .join('')
  const highRiskRows = salesHighRiskFiles
    ?.slice(0, 8)
    .map(
      (item) => `
 <tr>
 <td>${escapeHtml(item.fileName)}</td>
 <td>${escapeHtml(item.fileType)}</td>
 <td>${escapeHtml(item.fileSizeLabel)}</td>
 <td>${escapeHtml(item.primaryRisk)}</td>
 <td>${escapeHtml(item.riskDescription)}</td>
 </tr>`
    )
    .join('')
  const totalPrecheckFiles = Number(
    salesAuditSummary?.total_files || totalDocs || 0
  )
  const scannedPdf = Number(salesAuditSummary?.pdf_scan.scanned || 0)
  const mixedPdf = Number(salesAuditSummary?.pdf_scan.unknown || 0)
  const blockingCount = (salesAuditSummary?.findings ?? [])
    .filter((item) => ['parse_failed', 'pii', 'secrets'].includes(item.key))
    .reduce((sum, item) => sum + Number(item.count || 0), 0)
  const generatedAt = new Intl.DateTimeFormat('zh-CN', {
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date())
  const metricCards = [
    { glyph: 'S', label: '范围', tone: 'blue', value: datasetLabel },
    {
      glyph: 'DOC',
      label: '文件总数',
      tone: 'blue',
      value: totalPrecheckFiles.toLocaleString(),
    },
    { glyph: '%', label: '健康可入库', tone: 'steel', value: `${readyRate}%` },
    {
      glyph: 'H',
      label: '待人工处理',
      tone: 'violet',
      value: manualQueue.toLocaleString(),
    },
    { glyph: 'MB', label: '处理效率', tone: 'cyan', value: efficiency },
    { glyph: 'P90', label: 'P90 周期', tone: 'violet', value: latencyP90 },
    {
      glyph: 'F',
      label: '当前聚焦线索',
      tone: 'blue',
      value: selectedReason || '全部',
    },
    { glyph: 'JPG', label: '导出方式', tone: 'cyan', value: 'JPG 图片' },
  ]
    .map(
      (item) => `
 <article class="kpi-card kpi-card--${item.tone}">
 <div class="metric-icon" aria-hidden="true">${escapeHtml(item.glyph)}</div>
 <div class="metric-copy">
 <div class="metric-label">${escapeHtml(item.label)}</div>
 <div class="metric-value">${escapeHtml(item.value)}</div>
 </div>
 </article>`
    )
    .join('')
  const basisCards = [
    {
      glyph: 'I',
      label: '预检总量',
      tone: 'cyan',
      value: totalPrecheckFiles.toLocaleString(),
    },
    {
      glyph: 'DB',
      label: '总体体量',
      tone: 'blue',
      value: formatFileSize(salesAuditSummary?.total_size_bytes || 0),
    },
    {
      glyph: 'PDF',
      label: '扫描 / 混排',
      tone: 'violet',
      value: (scannedPdf + mixedPdf).toLocaleString(),
    },
    {
      glyph: '!',
      label: '阻断项',
      tone: 'orange',
      value: blockingCount.toLocaleString(),
    },
  ]
    .map(
      (item) => `
 <article class="basis-card basis-card--${item.tone}">
 <div class="metric-icon metric-icon--small" aria-hidden="true">${escapeHtml(item.glyph)}</div>
 <div>
 <div class="metric-label">${escapeHtml(item.label)}</div>
 <div class="metric-value metric-value--compact">${escapeHtml(item.value)}</div>
 </div>
 </article>`
    )
    .join('')

  return `<!doctype html>
<html lang="zh-CN">
<head>
 <meta charset="utf-8" />
 <meta name="viewport" content="width=device-width, initial-scale=1" />
 <title>入库预检报告</title>
 <style>
 :root {
 --paper: #f5f8fc;
 --paper-strong: #ffffff;
 --ink: #0c1730;
 --muted: #52627a;
 --line: #dfe7f2;
 --line-soft: #edf2f8;
 --blue: #1264e8;
 --cyan: #0ea5b7;
 --violet: #6d47e8;
 --orange: #f97316;
 --shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
 }
 * { box-sizing: border-box; }
 body {
 margin: 0;
 min-height: 100vh;
 color: var(--ink);
 background:
 radial-gradient(circle at 18% 0%, rgba(18, 100, 232, 0.08), transparent 26rem),
 linear-gradient(180deg, #f8fbff 0%, var(--paper) 52%, #eef4fb 100%);
 font-family:"Inter","PingFang SC","Microsoft YaHei", ui-sans-serif, system-ui, sans-serif;
 padding: 36px;
 }
 .report-shell {
 max-width: 1760px;
 margin: 0 auto;
 }
 .report-header {
 display: flex;
 align-items: flex-start;
 justify-content: space-between;
 gap: 24px;
 margin-bottom: 24px;
 }
 h1 {
 margin: 0;
 font-size: clamp(28px, 2.3vw, 40px);
 line-height: 1.1;
 letter-spacing: -0.05em;
 }
 h2 {
 margin: 0;
 font-size: 20px;
 letter-spacing: -0.03em;
 }
 .report-subtitle {
 max-width: 980px;
 margin: 10px 0 0;
 color: var(--muted);
 font-size: 15px;
 line-height: 1.6;
 }
 .generated-at {
 margin-top: 8px;
 color: #718096;
 font-size: 12px;
 }
 .toolbar {
 display: flex;
 flex-wrap: wrap;
 gap: 12px;
 justify-content: flex-end;
 }
 .toolbar button {
 min-height: 48px;
 border: 1px solid var(--line);
 border-radius: 10px;
 background: rgba(255, 255, 255, 0.82);
 color: var(--ink);
 cursor: pointer;
 font: inherit;
 font-weight: 700;
 padding: 0 20px;
 box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
 }
 .toolbar .primary {
 border-color: #0d5bd6;
 background: linear-gradient(135deg, #1668ee, #0d5bd6);
 color: #ffffff;
 }
 .button-icon {
 display: inline-flex;
 min-width: 24px;
 margin-right: 8px;
 font-size: 12px;
 letter-spacing: -0.04em;
 }
 .kpi-grid,
 .basis-grid {
 display: grid;
 grid-template-columns: repeat(4, minmax(0, 1fr));
 gap: 16px;
 }
 .kpi-grid {
 margin-bottom: 12px;
 }
 .kpi-card,
 .basis-card,
 .section-card {
 border: 1px solid var(--line);
 background: rgba(255, 255, 255, 0.86);
 box-shadow: var(--shadow);
 }
 .kpi-card,
 .basis-card {
 display: flex;
 align-items: center;
 gap: 20px;
 min-height: 108px;
 border-radius: 12px;
 padding: 22px;
 }
 .metric-icon {
 display: inline-flex;
 align-items: center;
 justify-content: center;
 width: 64px;
 height: 64px;
 flex: 0 0 auto;
 border-radius: 16px;
 background: #eef5ff;
 color: var(--blue);
 font-size: 13px;
 font-weight: 900;
 letter-spacing: -0.05em;
 }
 .metric-icon--small {
 width: 48px;
 height: 48px;
 border-radius: 14px;
 font-size: 12px;
 }
 .kpi-card--cyan .metric-icon,
 .basis-card--cyan .metric-icon { background: #e9fbfd; color: var(--cyan); }
 .kpi-card--violet .metric-icon,
 .basis-card--violet .metric-icon { background: #f0ebff; color: var(--violet); }
 .basis-card--orange .metric-icon { background: #fff2e8; color: var(--orange); }
 .kpi-card--steel .metric-icon { background: #edf2f8; color: #334155; }
 .metric-label {
 color: var(--muted);
 font-size: 14px;
 line-height: 1.2;
 }
 .metric-value {
 margin-top: 8px;
 color: var(--ink);
 font-size: 26px;
 font-weight: 900;
 letter-spacing: -0.04em;
 line-height: 1.1;
 }
 .metric-value--compact {
 font-size: 22px;
 }
 .section-card {
 margin-top: 12px;
 border-radius: 12px;
 padding: 16px 20px;
 }
 .section-head {
 display: flex;
 align-items: flex-end;
 justify-content: space-between;
 gap: 18px;
 margin-bottom: 14px;
 }
 .section-note {
 margin: 4px 0 0;
 color: var(--muted);
 font-size: 13px;
 line-height: 1.5;
 }
 .table-frame {
 overflow: hidden;
 border: 1px solid var(--line);
 border-radius: 10px;
 background: var(--paper-strong);
 }
 table {
 width: 100%;
 border-collapse: collapse;
 font-size: 14px;
 }
 th,
 td {
 border-bottom: 1px solid var(--line-soft);
 padding: 12px 16px;
 text-align: left;
 vertical-align: top;
 }
 th {
 color: #475569;
 background: #f8fbff;
 font-size: 12px;
 font-weight: 800;
 }
 tbody tr:last-child td {
 border-bottom: 0;
 }
 .status-pill,
 .action-pill {
 display: inline-flex;
 align-items: center;
 min-height: 24px;
 border: 1px solid #a7c9ff;
 border-radius: 7px;
 background: #eaf3ff;
 color: #075bd8;
 font-size: 12px;
 font-weight: 700;
 padding: 2px 9px;
 }
 .action-pill {
 border-color: #9bdfb8;
 background: #e9fbf0;
 color: #067647;
 }
 .split-grid {
 display: grid;
 grid-template-columns: repeat(2, minmax(0, 1fr));
 gap: 16px;
 margin-top: 12px;
 }
 .empty {
 border: 1px dashed var(--line);
 border-radius: 10px;
 color: var(--muted);
 padding: 18px;
 background: #f8fbff;
 }
 @media (max-width: 980px) {
 body { padding: 20px; }
 .report-header { display: block; }
 .toolbar { justify-content: flex-start; margin-top: 16px; }
 .kpi-grid,
 .basis-grid,
 .split-grid { grid-template-columns: 1fr; }
 }
 @media print {
 body { background: #ffffff; padding: 0; }
 .report-shell { max-width: none; }
 .toolbar { display: none; }
 .kpi-card,
 .basis-card,
 .section-card { box-shadow: none; break-inside: avoid; }
 }
 </style>
</head>
<body>
 <main class="report-shell">
 <header class="report-header">
 <div>
 <h1>入库预检报告</h1>
 <p class="report-subtitle">Sensitive Data Policy: 默认仅展示脱敏后的聚合事实与待确认线索，不做主观评分；需要人工判断的项统一保留在样本槽与风险清单里。</p>
 <div class="generated-at">生成时间：${escapeHtml(generatedAt)}</div>
 </div>
 <div class="toolbar" aria-label="报告操作">
 <button type="button" onclick="window.location.reload()"><span class="button-icon">R</span>刷新数据</button>
 <button class="primary" type="button"><span class="button-icon">JPG</span>导出 JPG</button>
 </div>
 </header>

 <section class="kpi-grid" aria-label="项目指标">
 ${metricCards}
 </section>

 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>入库依据</h2>
 <p class="section-note">面向入库前预检与确认入库，仅保留脱敏后的规模、体量和阻断线索。</p>
 </div>
 </div>
 <div class="basis-grid">
 ${basisCards}
 </div>
 </section>

 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>风险分布</h2>
 <p class="section-note">按后端预检 findings 聚合，等级用于排查优先级，不代表最终主观评分。</p>
 </div>
 </div>
 ${
   findingRows
     ? `<div class="table-frame">
 <table>
 <thead>
 <tr><th>类型</th><th>等级</th><th>数量</th><th>KEY</th></tr>
 </thead>
 <tbody>${findingRows}</tbody>
 </table>
 </div>`
     : '<div class="empty">暂无风险分布数据</div>'
 }
 </section>

 <div class="split-grid">
 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>入库抽样确认</h2>
 <p class="section-note">优先挑选能代表复杂度、体量和阻断原因的样本，用于确认是否入库或转人工处理。</p>
 </div>
 </div>
 ${
   pocRows
     ? `<div class="table-frame">
 <table>
 <thead>
 <tr><th>文件</th><th>类型</th><th>大小</th><th>主要风险</th><th>建议动作</th><th>原因</th></tr>
 </thead>
 <tbody>${pocRows}</tbody>
 </table>
 </div>`
     : '<div class="empty">暂无入库样本数据</div>'
 }
 </section>

 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>高风险文件</h2>
 <p class="section-note">用于人工复核与实施排期，不在报告中暴露原始敏感内容。</p>
 </div>
 </div>
 ${
   highRiskRows
     ? `<div class="table-frame">
 <table>
 <thead>
 <tr><th>文件</th><th>类型</th><th>大小</th><th>风险</th><th>原因</th></tr>
 </thead>
 <tbody>${highRiskRows}</tbody>
 </table>
 </div>`
     : '<div class="empty">暂无高风险文件数据</div>'
 }
 </section>
 </div>

 <section class="section-card">
 <div class="section-head">
 <div>
 <h2>当前页面样本</h2>
 <p class="section-note">导出时页面内可见文件的脱敏状态快照。</p>
 </div>
 </div>
 <div class="table-frame">
 <table>
 <thead>
 <tr>
 <th>文件</th>
 <th>状态</th>
 <th>阶段</th>
 <th>大小</th>
 <th>线索</th>
 </tr>
 </thead>
 <tbody>${rows || '<tr><td colspan="5">暂无当前页面样本</td></tr>'}</tbody>
 </table>
 </div>
 </section>
 </main>
</body>
</html>`
}
