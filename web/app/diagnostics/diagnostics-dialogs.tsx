'use client'

import { Button } from '@/components/ui/button'
import { Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription } from '@/components/ui/dialog'
import { formatApiError } from '@/lib/api-errors'
import { timestamp } from './diagnostics-model'
import { Status } from './diagnostics-controls'
import type { DiagnosticsController } from './use-diagnostics'
import styles from './diagnostics.module.css'

export function DiagnosticsDialogs({controller:c}:{controller:DiagnosticsController}) {
  return <>
    <Dialog open={c.detailsOpen} onOpenChange={c.setDetailsOpen}><DialogContent className={styles.rawDialog} onCloseAutoFocus={event=>c.restoreDialogFocus('details',event)}><DialogHeader><DialogTitle>原始响应</DialogTitle><DialogDescription>各探针的结果与作用范围</DialogDescription></DialogHeader><div className={styles.dialogBody}><pre className={styles.rawContent}>{JSON.stringify(c.rawSummary,null,2)}</pre></div><div className={styles.dialogFooter}><Button variant="outline" onClick={()=>c.setDetailsOpen(false)}>关闭</Button><Button className={styles.primary} onClick={()=>{void c.copySummary()}}>复制摘要</Button></div></DialogContent></Dialog>
    <Dialog open={c.servicesOpen} onOpenChange={c.setServicesOpen}><DialogContent className={styles.rawDialog} onCloseAutoFocus={event=>c.restoreDialogFocus('services',event)}><DialogHeader><DialogTitle>服务检查</DialogTitle><DialogDescription>快照更新于 {timestamp(Math.max(c.ready.dataUpdatedAt,c.deps.dataUpdatedAt,c.health.dataUpdatedAt)||null)}</DialogDescription></DialogHeader><div className={styles.dialogBody}><div className={styles.serviceDetails}>{c.services.map(service=><div key={service.key}><span>{service.name}</span><Status label={service.label} tone={service.tone}/></div>)}</div>{c.ready.isError||c.deps.isError||c.health.isError?<p className={styles.domainError} role="alert">{[c.ready.error,c.deps.error,c.health.error].filter(Boolean).map(error=>formatApiError(error,'服务状态获取失败')).join('；')}</p>:null}<details className={styles.serviceRaw}><summary>就绪探针</summary><pre className={styles.rawContent}>{JSON.stringify(c.ready.data??null,null,2)}</pre></details><details className={styles.serviceRaw}><summary>依赖连接详情</summary><pre className={styles.rawContent}>{JSON.stringify(c.deps.data??null,null,2)}</pre></details><details className={styles.serviceRaw}><summary>服务元信息</summary><pre className={styles.rawContent}>{JSON.stringify({health:c.health.data?.payload??null,meta:c.meta.data??null,online_quality:c.online.data??null},null,2)}</pre></details></div><div className={styles.dialogFooter}><Button variant="outline" onClick={()=>c.setServicesOpen(false)}>关闭</Button><Button disabled={c.statusRefreshing} className={styles.primary} onClick={()=>{void c.refreshStatus()}}>{c.statusRefreshing?'检查中':'刷新检查'}</Button></div></DialogContent></Dialog>
  </>
}
