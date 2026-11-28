'use client'

import { useEffect, useRef } from 'react'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Copy, Code, RefreshCw, Search, BarChart3, ShieldCheck, Loader2 } from '@/components/icons'
import { useDiagnostics } from './use-diagnostics'
import { ScopeControls, QueryControl, MetricControls, ServiceDependencies, Status } from './diagnostics-controls'
import { RetrievalChain } from './retrieval-chain'
import { DriftProbe, PerformanceProbe } from './diagnostic-probes'
import { DiagnosticsDialogs } from './diagnostics-dialogs'
import { currentProbeVerdict, driftVerdict, perfVerdict, timestamp } from './diagnostics-model'
import styles from './diagnostics.module.css'

export default function DiagnosticsPageClient() {
  const c = useDiagnostics()
  const drift = currentProbeVerdict(c.drift.status, '检查中', driftVerdict(c.drift.result?.data))
  const perf = currentProbeVerdict(c.perf.status, '运行中', perfVerdict(c.perf.result?.data))
  const previewState = currentProbeVerdict(
    c.preview.status,
    '运行中',
    c.preview.result?.partialErrors.length
      ? { label: '部分信息未取得', tone: 'warning' }
      : { label: '已返回', tone: 'success' },
  )
  const healthUpdatedAt = Math.max(c.health.dataUpdatedAt, c.ready.dataUpdatedAt)
  const resultsRef = useRef<HTMLDivElement>(null)
  const finishedAt = c.preview.result?.finishedAt
  useEffect(() => {
    if (!finishedAt) return
    const result = resultsRef.current
    const surface = result?.parentElement
    if (result && surface && getComputedStyle(surface).display === 'block') {
      const frame = requestAnimationFrame(() => {
        surface.scrollTo({
          top: surface.scrollTop + result.getBoundingClientRect().top - surface.getBoundingClientRect().top,
          behavior: 'instant',
        })
        result.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true })
      })
      return () => cancelAnimationFrame(frame)
    }
  }, [finishedAt])
  return (
    <AppFrame>
      <section className={styles.workspace} data-diagnostics-flow data-diagnostics-layout="workbench">
        <Tabs value={c.tab} onValueChange={c.setTab} className={styles.tabsRoot}>
          <header className={styles.header}>
            <div className={styles.heading}>
              <PageTitleIcon name="diagnostics" />
              <h1>诊断</h1>
            </div>
            <TabsList aria-label="诊断探针" className={styles.tabs}>
              <TabsTrigger className={styles.tab} value="retrieval">
                <Search />
                检索预览
                {c.preview.status !== 'idle' ? (
                  <i
                    className={styles.tabSignal}
                    data-tone={previewState.tone}
                    aria-hidden="true"
                    title={previewState.label}
                  />
                ) : null}
              </TabsTrigger>
              <TabsTrigger className={styles.tab} value="drift">
                <BarChart3 />
                向量漂移
                {c.drift.status !== 'idle' ? (
                  <i className={styles.tabSignal} data-tone={drift.tone} aria-hidden="true" title={drift.label} />
                ) : null}
              </TabsTrigger>
              <TabsTrigger className={styles.tab} value="performance">
                <ShieldCheck />
                性能门禁
                {c.perf.status !== 'idle' ? (
                  <i className={styles.tabSignal} data-tone={perf.tone} aria-hidden="true" title={perf.label} />
                ) : null}
              </TabsTrigger>
            </TabsList>
            <div className={styles.headerActions}>
              <Button
                variant="ghost"
                className={styles.healthTrigger}
                data-diag-services-trigger
                onClick={(event) => c.openServices(event.currentTarget)}
                aria-label="打开服务检查"
                title={`${c.systemState.label} · 向量 ${c.vectorBackend ?? '未知'}`}
              >
                <Status {...c.systemState} />
                <span className={styles.vectorLabel}>
                  向量 <strong>{c.vectorBackend ?? '未知'}</strong>
                </span>
              </Button>
              <Button
                variant="outline"
                aria-label="刷新诊断状态"
                title="刷新状态"
                disabled={c.statusRefreshing}
                onClick={() => {
                  void c.refreshStatus()
                }}
              >
                {c.statusRefreshing ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <RefreshCw />}
                <span className={styles.refreshLabel}>刷新状态</span>
              </Button>
              <Button
                variant="ghost"
                data-diag-details-trigger
                aria-label="查看原始响应"
                title="查看原始响应"
                size="icon"
                onClick={(event) => c.openDetails(event.currentTarget)}
              >
                <Code />
              </Button>
              <Button
                variant="ghost"
                aria-label="复制诊断摘要"
                title="复制诊断摘要"
                size="icon"
                onClick={() => {
                  void c.copySummary()
                }}
              >
                <Copy />
              </Button>
            </div>
          </header>
          <TabsContent value="retrieval" className={styles.workbench}>
            <aside className={styles.configuration} aria-label="查询与范围">
              <h2 className={styles.sidebarHeading}>查询与范围</h2>
              <ScopeControls controller={c} stacked />
              <QueryControl controller={c} />
              <MetricControls controller={c} />
              <ServiceDependencies controller={c} />
            </aside>
            <div className={styles.workbenchResults} ref={resultsRef}>
              <div className={styles.retrievalBody}>
                <RetrievalChain controller={c} />
              </div>
            </div>
          </TabsContent>
          <TabsContent value="drift" className={styles.tabBody}>
            <DriftProbe controller={c} />
          </TabsContent>
          <TabsContent value="performance" className={styles.tabBody}>
            <PerformanceProbe controller={c} />
          </TabsContent>
        </Tabs>
        <footer className={styles.footer}>
          <span>
            检索预览 ·{' '}
            {c.preview.status === 'running'
              ? '运行中'
              : c.preview.status === 'error'
                ? '请求失败'
                : c.preview.result
                  ? '已返回'
                  : '输入查询后运行'}
          </span>
          {c.preview.result ? <time>{timestamp(c.preview.result.finishedAt)}</time> : null}
          <span className={styles.spacer} />
          <span>各探针独立执行</span>
          <time>状态更新 {timestamp(healthUpdatedAt === 0 ? null : healthUpdatedAt)}</time>
        </footer>
        <DiagnosticsDialogs controller={c} />
      </section>
    </AppFrame>
  )
}
