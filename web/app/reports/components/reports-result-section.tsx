'use client'

import { AlertCircle, Loader2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Link } from '@/i18n/navigation'
import type { DatasetReport } from '@/types'
import { ReportsDashboard, type ReportsDashboardProps } from './reports-dashboard'
import styles from '../reports.module.css'

type Props=Omit<ReportsDashboardProps,'report'> & {report:DatasetReport|null;datasetId:string;isLoadingReport:boolean;reportErrorMessage:string;onRetry:()=>void;datasetsErrorMessage:string;isLoadingDatasets:boolean;onRetryDatasets:()=>void}
export function ReportsResultSection({datasetId,isLoadingReport,reportErrorMessage,onRetry,datasetsErrorMessage,isLoadingDatasets,onRetryDatasets,...props}:Readonly<Props>) {
  if(!props.report) {
    const error=reportErrorMessage||datasetsErrorMessage
    if(error)return <div className={styles.pageState} role="alert"><AlertCircle/><h2>{datasetsErrorMessage?'数据集加载失败':'报告加载失败'}</h2><p>{error}</p><Button variant="outline" aria-label="重试报告" onClick={datasetsErrorMessage?onRetryDatasets:onRetry}>重试</Button></div>
    if(isLoadingReport||isLoadingDatasets)return <div className={styles.pageState} role="status"><Loader2 className="animate-spin motion-reduce:animate-none"/><p>正在加载报告…</p></div>
    return <div className={styles.pageState}><h2>{datasetId?'暂无报告':'先选择数据集'}</h2><p>{datasetId?'刷新报告后查看当前快照。':'在数据集中导入文档后，可以在这里查看报告。'}</p><Link href="/datasets">查看数据集</Link></div>
  }
  return <>{reportErrorMessage&&<div className={styles.loadNotice} role="alert"><span>更新失败，当前显示上次报告：{reportErrorMessage}</span><Button variant="ghost" aria-label="重试报告" onClick={onRetry}>重试</Button></div>}<ReportsDashboard {...props} report={props.report}/></>
}
