'use client'

import { useEffect,useRef } from 'react'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Tabs,TabsContent,TabsList,TabsTrigger } from '@/components/ui/tabs'
import { Copy,Code,RefreshCw,Search,BarChart3,ShieldCheck,Loader2 } from '@/components/icons'
import { useDiagnostics } from './use-diagnostics'
import { ScopeControls,QueryControl,MetricControls,ServiceDependencies,Status } from './diagnostics-controls'
import { RetrievalChain } from './retrieval-chain'
import { DriftProbe,PerformanceProbe } from './diagnostic-probes'
import { DiagnosticsDialogs } from './diagnostics-dialogs'
import { driftVerdict,perfVerdict,record,timestamp } from './diagnostics-model'
import styles from './diagnostics.module.css'

export default function DiagnosticsPageClient() {
  const c=useDiagnostics(),drift=driftVerdict(c.drift.result?.data),perf=perfVerdict(c.perf.result?.data)
  const resultsRef=useRef<HTMLDivElement>(null)
  const finishedAt=c.preview.result?.finishedAt
  useEffect(()=>{
    if(!finishedAt)return
    const result=resultsRef.current
    const surface=result?.parentElement
    if(result&&surface&&getComputedStyle(surface).display==='block'){
      const frame=requestAnimationFrame(()=>{
        surface.scrollTo({top:surface.scrollTop+result.getBoundingClientRect().top-surface.getBoundingClientRect().top,behavior:'instant'})
        result.querySelector<HTMLElement>('h2')?.focus({preventScroll:true})
      })
      return ()=>cancelAnimationFrame(frame)
    }
  },[finishedAt])
  return <AppFrame><section className={styles.workspace} data-diagnostics-flow data-diagnostics-layout="workbench">
    <header className={styles.header}>
      <div className={styles.heading}><PageTitleIcon name="diagnostics"/><h1>诊断</h1></div>
      <div className={styles.headerActions}>
        <Button variant="ghost" data-diag-details-trigger aria-label="查看原始响应" onClick={event=>c.openDetails(event.currentTarget)}><Code/><span>原始响应</span></Button>
        <Button variant="ghost" aria-label="复制诊断摘要" onClick={()=>{void c.copySummary()}}><Copy/><span>复制摘要</span></Button>
        <Button variant="outline" aria-label="刷新诊断状态" disabled={c.statusRefreshing} onClick={()=>{void c.refreshStatus()}}>{c.statusRefreshing?<Loader2 className="animate-spin"/>:<RefreshCw/>}<span>刷新状态</span></Button>
      </div>
    </header>
    <div className={styles.healthBar}>
      <button data-diag-services-trigger onClick={event=>c.openServices(event.currentTarget)} aria-label="打开服务检查"><Status {...c.systemState}/></button>
      <span>{c.ready.isError?'就绪状态未取得':record(c.ready.data).ok===true?'必需依赖已就绪':'就绪状态待确认'}</span>
      <span>向量后端 <strong>{c.vectorBackend??'未知'}</strong></span><span className={styles.spacer}/>
      <span className={styles.onlineBadge}>在线评估 · {c.online.isError?'未取得':c.online.isPending?'检查中':c.online.data?.enabled?'已启用':'未启用'}</span>
      <time>{timestamp(Math.max(c.health.dataUpdatedAt,c.ready.dataUpdatedAt)||null)}</time>
    </div>
    <Tabs value={c.tab} onValueChange={c.setTab} className={styles.tabsRoot}>
      <TabsList aria-label="诊断探针" className={styles.tabs}><TabsTrigger className={styles.tab} value="retrieval"><Search/>检索预览</TabsTrigger><TabsTrigger className={styles.tab} value="drift"><BarChart3/>向量漂移<Status label={c.drift.status==='running'?'检查中':c.drift.status==='error'?'请求失败':drift.label} tone="neutral"/></TabsTrigger><TabsTrigger className={styles.tab} value="performance"><ShieldCheck/>性能门禁<Status label={c.perf.status==='running'?'运行中':c.perf.status==='error'?'请求失败':perf.label} tone="neutral"/></TabsTrigger></TabsList>
      <TabsContent value="retrieval" className={styles.workbench}>
        <aside className={styles.configuration} aria-label="查询与范围">
          <h2 className={styles.sidebarHeading}>查询与范围</h2>
          <ScopeControls controller={c} stacked/>
          <QueryControl controller={c}/>
          <MetricControls controller={c}/>
          <ServiceDependencies controller={c}/>
        </aside>
        <div className={styles.workbenchResults} ref={resultsRef}>
          <div className={styles.retrievalBody}><RetrievalChain controller={c}/></div>
          <div className={styles.probeShortcuts} aria-label="其他诊断检查">
            <Button variant="ghost" onClick={()=>c.setTab('drift')}><BarChart3/>向量漂移<Status {...drift}/></Button>
            <Button variant="ghost" onClick={()=>c.setTab('performance')}><ShieldCheck/>性能门禁<Status {...perf}/></Button>
            <span className={styles.spacer}/><span>各探针独立执行</span>
          </div>
        </div>
      </TabsContent>
      <TabsContent value="drift" className={styles.tabBody}><ScopeControls controller={c}/><DriftProbe controller={c}/></TabsContent>
      <TabsContent value="performance" className={styles.tabBody}><ScopeControls controller={c}/><PerformanceProbe controller={c}/></TabsContent>
    </Tabs>
    <footer className={styles.footer}><span>检索预览 · {c.preview.status==='running'?'运行中':c.preview.status==='error'?'请求失败':c.preview.result?'已返回':'待执行'}</span>{c.preview.result?<time>{timestamp(c.preview.result.finishedAt)}</time>:null}<span className={styles.spacer}/><span>漂移 · {drift.label}</span><span>门禁 · {perf.label}</span></footer>
    <DiagnosticsDialogs controller={c}/>
  </section></AppFrame>
}
