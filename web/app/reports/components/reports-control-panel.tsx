'use client'

import { Archive, BarChart3, ChevronDown, Clock3, Download, FileText, Loader2, RefreshCw, ShieldCheck } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { DatasetReport } from '@/types'
import { formatDate } from '@/lib/utils'
import { DEFAULT_PIPELINE_VERSION_VALUE } from '../report-tokens'
import { reportDataSourceLabel, shortPipelineHash } from '../report-format'
import type { DatasetOption, PipelineVersionOption } from '../types'
import styles from '../reports.module.css'

export function ReportsControlPanel(props: Readonly<{
  datasetId:string;datasets:DatasetOption[];isLoadingDatasets:boolean;pipelineVersionSelectValue:string;pipelineVersionOptions:PipelineVersionOption[];connectorRunsLimit:number;redact:boolean;
  isExportingJson:boolean;isExportingHtml:boolean;isExportingRagAuditHtml:boolean;isExportingBundle:boolean;report:DatasetReport|null;isLoadingReport:boolean;
  onDatasetChange:(value:string)=>void;onPipelineHashChange:(value:string)=>void;onConnectorRunsLimitChange:(value:number)=>void;onRedactChange:(value:boolean)=>void;
  onExportJson:()=>void;onExportCompleteJson:()=>void;onExportChartsJson:()=>void;onExportRagAuditHtml:()=>void;onExportBundleZip:()=>void;onExportHtml:()=>void;onRefresh:()=>void;
}>) {
  const exporting=props.isExportingJson||props.isExportingHtml||props.isExportingRagAuditHtml||props.isExportingBundle
  const disabled=!props.datasetId||!props.report||props.isLoadingReport||exporting
  const selectedVersion=props.pipelineVersionOptions.find(version=>version.pipeline_hash===props.pipelineVersionSelectValue)
  const versionLabel=props.pipelineVersionSelectValue===DEFAULT_PIPELINE_VERSION_VALUE?'全部处理版本':shortPipelineHash(props.pipelineVersionSelectValue)
  return <>
    <header className={styles.header}><div className={styles.heading}><PageTitleIcon name="report-export"/><h1>数据报告</h1></div><div className={styles.headerActions}>
      <Button variant="ghost" onClick={props.onRefresh} disabled={props.isLoadingReport||props.isLoadingDatasets} aria-label="刷新报告"><RefreshCw className={props.isLoadingReport?'animate-spin motion-reduce:animate-none':undefined}/><span>刷新报告</span></Button>
      <DropdownMenu><DropdownMenuTrigger asChild><Button className={styles.primary} disabled={disabled} aria-label="导出报告" aria-busy={exporting}>{exporting?<Loader2 className="animate-spin motion-reduce:animate-none"/>:<Download/>}<span>{exporting?'导出中…':'导出报告'}</span><ChevronDown/></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className={styles.exportMenu}>
        <DropdownMenuLabel>阅读与审计</DropdownMenuLabel>
        <DropdownMenuItem disabled={disabled} onSelect={props.onExportHtml} aria-label="导出 HTML"><FileText/>HTML 阅读版</DropdownMenuItem>
        <DropdownMenuItem disabled={disabled} onSelect={props.onExportRagAuditHtml} aria-label="导出 RAG 审计报告"><ShieldCheck/>RAG 审计报告</DropdownMenuItem>
        <DropdownMenuItem disabled={disabled} onSelect={props.onExportBundleZip} aria-label="导出数据包 ZIP"><Archive/>Bundle ZIP 归档</DropdownMenuItem>
        <DropdownMenuSeparator/>
        <DropdownMenuCheckboxItem checked={props.redact} onCheckedChange={props.onRedactChange} onSelect={event=>event.preventDefault()} aria-label="HTML／ZIP 脱敏">HTML／ZIP 脱敏</DropdownMenuCheckboxItem>
        <DropdownMenuSeparator/><DropdownMenuLabel>原始数据</DropdownMenuLabel>
        <DropdownMenuItem disabled={disabled} onSelect={props.onExportJson} aria-label="导出 JSON"><Download/>标准 JSON 报告</DropdownMenuItem>
        <DropdownMenuItem disabled={disabled} onSelect={props.onExportCompleteJson} aria-label="导出完整 JSON"><Archive/>完整 JSON 快照</DropdownMenuItem>
        <DropdownMenuItem disabled={disabled} onSelect={props.onExportChartsJson} aria-label="导出 RAG 统计"><BarChart3/>RAG 统计数据</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu>
    </div></header>
    <div className={styles.scopeBar}>
      <label><span>数据集</span><Select value={props.datasetId} onValueChange={props.onDatasetChange} disabled={props.isLoadingDatasets&&!props.datasets.length}><SelectTrigger aria-label="数据集" className={styles.datasetSelect}><SelectValue placeholder={props.isLoadingDatasets?'加载中…':'选择数据集'}/></SelectTrigger><SelectContent>{props.datasets.map(dataset=><SelectItem key={dataset.id} value={dataset.id}>{dataset.name||dataset.id}</SelectItem>)}</SelectContent></Select></label>
      <label><span>处理版本</span><Select value={props.pipelineVersionSelectValue} onValueChange={props.onPipelineHashChange} disabled={!props.datasetId}><SelectTrigger aria-label="处理版本" className={styles.versionSelect}><SelectValue>{versionLabel}</SelectValue></SelectTrigger><SelectContent><SelectItem value={DEFAULT_PIPELINE_VERSION_VALUE}>全部处理版本</SelectItem>{!selectedVersion&&props.pipelineVersionSelectValue!==DEFAULT_PIPELINE_VERSION_VALUE&&<SelectItem value={props.pipelineVersionSelectValue}>{versionLabel}</SelectItem>}{props.pipelineVersionOptions.map(version=><SelectItem key={version.pipeline_hash} value={version.pipeline_hash}>{shortPipelineHash(version.pipeline_hash)} · {version.documents} 个文档</SelectItem>)}</SelectContent></Select></label>
      <label><span>附带运行</span><Select value={String(props.connectorRunsLimit)} onValueChange={value=>props.onConnectorRunsLimitChange(Number(value))} disabled={!props.datasetId}><SelectTrigger aria-label="附带运行记录" className={styles.runSelect}><SelectValue/></SelectTrigger><SelectContent>{[0,10,20,50,100].map(value=><SelectItem key={value} value={String(value)}>{value===0?'不附带记录':`${value} 条记录`}</SelectItem>)}</SelectContent></Select></label>
      <Popover><PopoverTrigger asChild><button className={styles.reportTime} type="button" aria-label="查看报告信息"><Clock3/><span>{props.isLoadingReport?'正在更新…':props.report?`生成于 ${formatDate(props.report.generated_at)}`:'等待报告'}</span></button></PopoverTrigger><PopoverContent align="end" className={styles.reportInfo}><h2>报告信息</h2><dl><dt>数据来源</dt><dd>{reportDataSourceLabel(props.report?.data_provenance)}</dd><dt>生成时间</dt><dd>{props.report?.generated_at?formatDate(props.report.generated_at):'—'}</dd><dt>数据集标识</dt><dd>{props.datasetId||'—'}</dd></dl></PopoverContent></Popover>
    </div>
  </>
}
