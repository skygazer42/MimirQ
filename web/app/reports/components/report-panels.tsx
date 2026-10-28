'use client'

import { useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronRight, Clock3, FileText } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Link } from '@/i18n/navigation'
import type { DatasetReport } from '@/types'
import type { CoverageRow, ReportFinding } from '../types'
import { findingSeverityLabel, retrievalAuditFailureText, retrievalAuditKgRecommendationText, retrievalAuditStatusLabel, retrievalAuditTone, safeNumber } from '../report-format'
import { reportAuditRows, reportCoverage } from '../report-overview-model'
import { cn } from '@/lib/utils'
import styles from '../reports.module.css'

export function CoverageRows({rows}:{rows:CoverageRow[]}) {
  return <div className={styles.coverageRows}>{rows.map(row=><div key={row.label} className={styles.coverageRow}><span>{row.label.replace(/覆盖$/,'')}</span><i aria-hidden="true"><i style={{width:row.max>0?`${Math.max(0,Math.min(100,row.value/row.max*100))}%`:'0%'}}/></i><strong>{row.max>0?`${row.value} / ${row.max}`:'—'}</strong><small>{reportCoverage(row.value,row.max)}</small></div>)}</div>
}

export function AuditPanel({report,full=false,onExpand}:{report:DatasetReport;full?:boolean;onExpand?:()=>void}) {
  const audit=report.retrieval_audit
  const rows=reportAuditRows(audit)
  const gates=audit?.gates||[]
  const visible=full?rows:rows.slice(0,5)
  const tone=retrievalAuditTone(audit?.status)
  return <section className={styles.auditPanel} aria-label="召回审计结果">
    <div className={styles.sectionHeading}><h2>召回审计</h2><span className={cn(styles.stateLabel,styles[tone])}>{tone==='rose'?<AlertCircle/>:tone==='green'?<CheckCircle2/>:<Clock3/>}{retrievalAuditStatusLabel(audit?.status)}</span>{gates.length>0&&<small>{gates.length} 项门禁</small>}</div>
    {visible.length?<div className={styles.localTable}><table className={styles.auditTable} aria-label="召回门禁指标"><thead><tr><th>观测指标</th><th>当前值</th><th>所属门禁</th></tr></thead><tbody>{visible.map(row=><tr key={row.key}><th scope="row">{row.label}</th><td>{row.value}</td><td><span title={`${row.gate} · ${retrievalAuditStatusLabel(row.status)}`}>{row.gate}</span></td></tr>)}</tbody></table></div>:<div className={styles.auditEmpty}><p>{gates.length?'当前门禁没有摘要指标，可展开门禁详情。':'暂无召回门禁指标'}</p>{!gates.length&&<Link href={`/evaluations?tab=regression&dataset_id=${encodeURIComponent(report.dataset_id)}`}>前往评测<ChevronRight/></Link>}</div>}
    {!full&&onExpand&&(rows.length>0||gates.length>0||audit?.status==='failed')&&<button type="button" className={styles.quietLink} onClick={onExpand}>{rows.length>5?`查看全部 ${rows.length} 项指标`:'查看审计详情'}<ChevronRight/></button>}
    {full&&<>
      <div className={styles.auditFacts}><div><span>失败归因</span><strong>{audit?retrievalAuditFailureText(audit):'待评估'}</strong></div><div><span>图谱建议</span><strong>{retrievalAuditKgRecommendationText(audit)}</strong></div><div><span>插件引用</span><strong>{audit?.plugin_refs?.join('、')||'未绑定'}</strong></div></div>
      {gates.map((gate,index)=><details key={`${gate.name}:${index}`} className={styles.gateDetails} open={gate.failed_conditions.length>0}><summary><span>{gate.name}</span><small>{retrievalAuditStatusLabel(gate.status)}</small></summary>{gate.failed_conditions.length>0&&<ul className={styles.failedConditions}>{gate.failed_conditions.map((condition,i)=><li key={i}>{condition}</li>)}</ul>}<dl><dt>记录来源</dt><dd>{gate.source||'未记录'}</dd><dt>生成时间</dt><dd>{gate.generated_at||'未记录'}</dd></dl><details className={styles.rawDetails}><summary>原始门禁指标</summary><pre>{JSON.stringify(gate.metrics,null,2)}</pre></details></details>)}
      {audit?.recommended_next_action&&<p className={styles.auditAction}>{audit.recommended_next_action}</p>}
      {Boolean(audit?.plugin_package_hashes?.length)&&<details className={styles.rawDetails}><summary>插件包版本</summary><pre>{audit?.plugin_package_hashes.join('\n')}</pre></details>}
    </>}
  </section>
}

export function FindingsTable({rows,onlyIssues,onOnlyIssuesChange,datasetName,scope,compact=false,onExpand,runErrors=0,onViewRuns}:{rows:ReportFinding[];onlyIssues:boolean;onOnlyIssuesChange:(checked:boolean)=>void;datasetName:string;scope:string;compact?:boolean;onExpand?:()=>void;runErrors?:number;onViewRuns?:()=>void}) {
  const [selectedKey,setSelectedKey]=useState('')
  const trigger=useRef<HTMLButtonElement|null>(null)
  const selected=rows.find(row=>row.key===selectedKey)
  const visible=compact?rows.slice(0,5):rows
  const hits=rows.reduce((sum,row)=>sum+safeNumber(row.count),0)
  return <section className={styles.findingsSection}>
    <div className={styles.findingsHeading}><h2>质量规则命中</h2><small>{rows.length} 类 · {hits} 次命中</small>{runErrors>0&&<button type="button" className={styles.runWarningLink} onClick={onViewRuns}><AlertCircle/>{runErrors} 条运行异常<ChevronRight/></button>}<label><Checkbox checked={onlyIssues} onCheckedChange={value=>onOnlyIssuesChange(value===true)} aria-label="只看异常"/>只看异常</label></div>
    <div className={styles.localTable}><table className={styles.findingsTable} aria-label="质量规则命中"><colgroup><col className={styles.levelColumn}/><col className={styles.ruleColumn}/><col className={styles.countColumn}/><col/><col className={styles.actionColumn}/></colgroup><thead><tr><th>级别</th><th>命中规则</th><th>数量</th><th>说明</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{visible.map(row=><tr key={row.key}><td><span className={cn(styles.level,styles[row.severity])}>{row.severity==='info'?<FileText/>:<AlertCircle/>}{findingSeverityLabel(row.severity)}</span></td><th scope="row">{row.label||row.key}</th><td className={styles.count}>{row.count}</td><td className={styles.findingDescription}>{row.description||'—'}</td><td><Button variant="ghost" aria-label={`查看${row.label||row.key}`} onClick={event=>{trigger.current=event.currentTarget;setSelectedKey(row.key)}}><ChevronRight/><span>查看</span></Button></td></tr>)}</tbody></table></div>
    {!visible.length&&<div className={styles.inlineEmpty}>{onlyIssues?'当前报告没有异常规则命中':'当前报告没有规则命中记录'}</div>}
    {compact&&rows.length>5&&<button type="button" className={styles.moreRows} onClick={onExpand}>查看全部 {rows.length} 类规则<ChevronRight/></button>}
    {!compact&&rows.length>0&&<p className={styles.tableNote}>按规则统计，命中数未按文档去重。</p>}
    <Dialog open={Boolean(selected)} onOpenChange={open=>{if(!open)setSelectedKey('')}}><DialogContent className={styles.findingDialog} onCloseAutoFocus={event=>{event.preventDefault();trigger.current?.focus()}}><DialogHeader><DialogTitle>{selected?.label||selected?.key}</DialogTitle><DialogDescription>{selected?.description||'该条目为质量扫描返回的聚合规则命中。'}</DialogDescription></DialogHeader><dl><dt>命中次数</dt><dd>{selected?.count??'—'}</dd><dt>数据集</dt><dd>{datasetName}</dd><dt>处理范围</dt><dd>{scope}</dd><dt>规则标识</dt><dd>{selected?.key}</dd></dl><p>同一文档可能命中多条规则。</p></DialogContent></Dialog>
  </section>
}
