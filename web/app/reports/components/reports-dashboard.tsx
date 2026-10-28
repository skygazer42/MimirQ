'use client'

import { useState } from 'react'
import type { DatasetReport, DatasetReportPipelineVersion } from '@/types'
import type { CategoryMetricDatum, CoverageRow, IssueRow, PipelineVersionDatum, ReportMetricDatum, RetrievalAudit } from '../types'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Link } from '@/i18n/navigation'
import { ChevronRight, FileText } from '@/components/icons'
import { formatDate, formatFileSize } from '@/lib/utils'
import { countFindingsByPattern, filterReportFindings, safeNumber, shortPipelineHash } from '../report-format'
import { recordedRiskValue, reportStatusRows } from '../report-overview-model'
import { AuditPanel, CoverageRows, FindingsTable } from './report-panels'
import { cn } from '@/lib/utils'
import styles from '../reports.module.css'

export type ReportsDashboardProps = Readonly<{
  totalDocs: number
  totalBytes: number
  successDocs: number
  successRate: string
  failed: number
  failedRate: string
  pipelineVersions: DatasetReportPipelineVersion[]
  pipelineVersionsWithFill: PipelineVersionDatum[]
  pipelineFilterLabel: string
  latestAuditTime: string
  retrievalAudit: RetrievalAudit | null
  missingFindingCount: number
  duplicateFindingCount: number
  lowQualityFindingCount: number
  fieldCoverageRows: CoverageRow[]
  fieldCoverageBadge: string
  topDocumentRows: ReportMetricDatum[]
  topDocumentMax: number
  onClearFolderQuery: () => void
  governanceAuditUrlValue: string
  governanceAuditUrlSub: string
  governanceAuditImageValue: string
  governanceAuditImageSub: string
  governanceAuditHasSamples: boolean
  sensitiveHits: number
  piiHits: number
  secretHits: number
  categoryBarData: CategoryMetricDatum[]
  versionTotal: number
  issueRows: IssueRow[]
  report: DatasetReport
  baseCoverageRows: CoverageRow[]
  showOnlyIssues: boolean
  onShowOnlyIssuesChange: (value: boolean) => void
  redact: boolean
}>

const sections=[['overview','报告总览'],['quality','数据质量'],['audit','召回审计'],['structure','结构与风险']] as const

function Distribution({rows,unit='文档'}:{rows: Array<{name:string;value:number}>;unit?:string}) {
  const max=Math.max(1,...rows.map(row=>row.value))
  return rows.length?<div className={styles.distribution}>{rows.map(row=><div key={row.name}><span title={row.name}>{row.name}</span><i aria-hidden="true"><i style={{width:`${Math.max(0,row.value/max*100)}%`}}/></i><strong>{row.value}<small>{unit}</small></strong></div>)}</div>:<p className={styles.inlineEmpty}>暂无分布数据</p>
}

function Versions({rows,compact=false}:{rows:DatasetReportPipelineVersion[];compact?:boolean}) {
  const visible=compact?rows.slice(0,2):rows
  return visible.length?<div className={styles.versions}>{visible.map(row=><div key={row.pipeline_hash}><span title={row.pipeline_hash}>{row.pipeline_hash&&row.pipeline_hash!=='unknown'?shortPipelineHash(row.pipeline_hash):'未记录版本'}</span><strong>{row.documents} 个文档</strong></div>)}</div>:<p className={styles.inlineEmpty}>暂无处理版本记录</p>
}

export function ReportsDashboard(props:ReportsDashboardProps) {
  const [section,setSection]=useState('overview')
  const report=props.report
  const statusRows=reportStatusRows(report.profile.by_status||{})
  const done=statusRows.filter(row=>row.tone==='success').reduce((sum,row)=>sum+row.value,0)
  const statusTotal=statusRows.reduce((sum,row)=>sum+row.value,0)
  const findings=filterReportFindings(report.profile.findings||[],props.showOnlyIssues)
  const activeFindings=findings.filter(row=>safeNumber(row.count)>0)
  const files=Object.entries(report.profile.by_file_type||{}).map(([name,value])=>({name,value})).sort((a,b)=>b.value-a.value)
  const directories=Object.entries(report.profile.by_directory||{}).map(([name,value])=>({name,value})).sort((a,b)=>b.value-a.value)
  const failedRuns=(report.connectors||[]).filter(run=>/fail|error/i.test(run.status))
  const runRows=props.showOnlyIssues?failedRuns:report.connectors||[]
  const datasetName=report.dataset_name||'当前数据集'
  const piiRecorded=Object.keys(report.compliance.pii_hits_total||{}).length>0||Object.keys(report.profile.pii_hits_total||{}).length>0
  const secretsRecorded=Object.keys(report.compliance.secrets_hits_total||{}).length>0||Object.keys(report.profile.secrets_hits_total||{}).length>0
  const qualityHits=countFindingsByPattern(report.profile.findings||[],/quality|低质量|low/i)
  const rules=(compact=false)=><FindingsTable rows={compact?activeFindings:findings} onlyIssues={props.showOnlyIssues} onOnlyIssuesChange={props.onShowOnlyIssuesChange} datasetName={datasetName} scope={props.pipelineFilterLabel} compact={compact} onExpand={()=>setSection('quality')} runErrors={failedRuns.length} onViewRuns={()=>setSection('structure')}/>
  return <div className={styles.reportBody} data-reports-overview>
    <Tabs value={section} onValueChange={setSection} className={styles.tabsRoot}><TabsList aria-label="报告内容" className={styles.tabs}>{sections.map(([id,label])=><TabsTrigger key={id} value={id} className={styles.tab}>{label}</TabsTrigger>)}</TabsList>
      <TabsContent value="overview" className={styles.tabBody}>
        {props.totalDocs===0?<div className={styles.emptyDataset}><FileText/><h2>该数据集还没有文档</h2><p>导入文档后可查看处理状态和质量报告。</p><Link href={`/knowledge?dataset_id=${encodeURIComponent(report.dataset_id)}`}>前往知识库<ChevronRight/></Link></div>:<div className={styles.overview}>
          <section className={styles.metrics} aria-label="报告摘要"><dl><div><dt>文档总数</dt><dd>{props.totalDocs}<small>{props.pipelineFilterLabel}</small></dd></div><div><dt>已完成</dt><dd>{statusRows.length?done:'—'}<small>{statusRows.length&&props.totalDocs?`${(done/props.totalDocs*100).toFixed(1)}%`:'暂无状态统计'}</small></dd></div><div><dt>数据体积</dt><dd>{formatFileSize(props.totalBytes)}</dd></div><div><dt>解析失败</dt><dd>{props.failed}<small>{props.failedRate}</small></dd></div></dl></section>
          <section className={styles.processing}><span>处理结果</span>{statusRows.length?<><div className={styles.statusBar} aria-hidden="true">{statusRows.map(row=><i key={row.key} className={styles[row.tone]} style={{width:`${statusTotal?row.value/statusTotal*100:0}%`}}/>)}</div><div className={styles.statusLegend}>{statusRows.map(row=><span key={row.key}><i className={styles[row.tone]}/>{row.label}<strong>{row.value}</strong></span>)}</div></>:<span>暂无处理状态统计</span>}</section>
          <div className={styles.analysisColumns}><section className={styles.coverageSection}><div className={styles.sectionHeading}><h2>字段覆盖</h2><small>按 {props.totalDocs} 个文档统计</small></div><CoverageRows rows={props.baseCoverageRows}/></section><AuditPanel report={report} onExpand={()=>setSection('audit')}/></div>
          {rules(true)}
          <div className={styles.structureSummary}><section><div className={styles.sectionHeading}><h2>处理版本</h2>{props.pipelineVersions.length>2&&<button type="button" onClick={()=>setSection('structure')}>查看全部 {props.pipelineVersions.length} 个版本</button>}</div><Versions rows={props.pipelineVersions} compact/></section><section><div className={styles.sectionHeading}><h2>文件构成</h2>{files.length>4&&<button type="button" onClick={()=>setSection('structure')}>查看全部</button>}</div><div className={styles.fileTypes}>{files.slice(0,4).map(row=><div key={row.name}><span>{row.name.toUpperCase()}</span><strong>{row.value}</strong></div>)}</div></section></div>
        </div>}
      </TabsContent>
      <TabsContent value="quality" className={styles.tabBody}><div className={styles.detailPage}>
        {rules()}
        <div className={styles.qualityColumns}><section><div className={styles.sectionHeading}><h2>字段覆盖</h2><small>基础画像</small></div><CoverageRows rows={props.baseCoverageRows}/></section><section><div className={styles.sectionHeading}><h2>{props.fieldCoverageBadge==='治理审计'?'治理覆盖':'内容健康'}</h2></div>{props.fieldCoverageBadge==='治理审计'?<CoverageRows rows={props.fieldCoverageRows}/>:<p className={styles.inlineEmpty}>尚无治理审计记录</p>}</section></div>
        <section className={styles.contentHealth}><div className={styles.sectionHeading}><h2>内容健康</h2></div><dl>{[['URL 变更',props.governanceAuditUrlValue],['图片处理',props.governanceAuditImageValue],['隐私信息命中',recordedRiskValue(props.piiHits,piiRecorded)],['密钥命中',recordedRiskValue(props.secretHits,secretsRecorded)],['低质量命中',recordedRiskValue(qualityHits,safeNumber(report.governance_audit?.docs_with_governance_quality)>0)]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p className={styles.tableNote}>未返回检测记录的指标显示为待评估。</p></section>
        {report.governance_metrics&&<section className={styles.governanceDetails}><div className={styles.sectionHeading}><h2>治理记录</h2><small>{report.governance_metrics.used_documents} 个已统计文档</small></div><dl>{[['治理记录',report.governance_metrics.docs_with_governance],['规则应用次数',report.governance_metrics.rules_applied_total],['变更文档',report.governance_metrics.changed_documents_total],['过滤文档',report.governance_metrics.dropped_documents_total]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>{report.governance_metrics.truncated&&<p>统计范围已达到采样上限。</p>}</section>}
      </div></TabsContent>
      <TabsContent value="audit" className={styles.tabBody}><div className={styles.detailPage}><AuditPanel report={report} full/></div></TabsContent>
      <TabsContent value="structure" className={styles.tabBody}><div className={styles.detailPage}>
        <div className={styles.structureColumns}><section><div className={styles.sectionHeading}><h2>文件类型分布</h2><small>文档数量</small></div><Distribution rows={files}/></section><section><div className={styles.sectionHeading}><h2>处理版本</h2><small>{props.pipelineVersions.length} 个版本</small></div><Versions rows={props.pipelineVersions}/></section><section><div className={styles.sectionHeading}><h2>目录分布</h2><small>各目录文档数量</small></div><Distribution rows={directories}/></section><section><div className={styles.sectionHeading}><h2>知识分类</h2><small>数据集数量</small></div><Distribution rows={props.categoryBarData} unit="数据集"/></section></div>
        <section className={styles.connectorSection}><div className={styles.sectionHeading}><h2>运行记录</h2><small>{runRows.length} 条</small></div><div className={styles.localTable}><table className={styles.connectorTable} aria-label="运行记录"><thead><tr><th>连接器</th><th>状态</th><th>创建时间</th><th>运行信息</th></tr></thead><tbody>{runRows.map(run=><tr key={run.id}><th scope="row">{run.connector_id}</th><td><span className={cn(styles.level,/fail|error/i.test(run.status)?styles.error:styles.info)}>{run.status==='failed'?'失败':run.status==='completed'?'已完成':run.status}</span></td><td>{formatDate(run.created_at)}</td><td>{run.error_message||'—'}</td></tr>)}</tbody></table></div>{!runRows.length&&<p className={styles.inlineEmpty}>当前范围没有运行记录</p>}</section>
        <details className={styles.rawDetails}><summary>数据来源与范围</summary><pre>{JSON.stringify({dataset:report.dataset_id,pipeline_hash:report.pipeline_hash,generated_at:report.generated_at,data_provenance:report.data_provenance},null,2)}</pre></details>
      </div></TabsContent>
    </Tabs>
    <footer className={styles.footer}><span title={datasetName}>{datasetName} · {props.totalDocs} 个文档</span><span>{props.pipelineFilterLabel}</span><span>HTML／ZIP 脱敏{props.redact?'已开启':'已关闭'}</span></footer>
  </div>
}
