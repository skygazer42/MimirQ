'use client'

/**
 * KnowledgeRetrievalPanel - Index Audit Module
 * 优化版：极致高密度诊断台、UI Pro Max 物理质感、极客化数据展示
 */
import { useMemo } from 'react'
import { 
  BarChart3, 
  Loader2, 
  RefreshCw, 
  ShieldCheck, 
  Fingerprint, 
  Activity,
  AlertTriangle,
  ChevronRight,
  Database,
  Search,
  Scan,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'

import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { useIndexAudit } from '@/hooks/use-index-audit'
import { cn, detachPromise } from '@/lib/utils'

type KnowledgeRetrievalPanelProps = {
  selectedDatasetId?: string
  compact?: boolean
}

export function KnowledgeRetrievalPanel({ selectedDatasetId, compact = false }: Readonly<KnowledgeRetrievalPanelProps>) {
  const t = useTranslations('KnowledgeRetrievalPanel')
  const { indexAudit, indexAuditError, indexAuditLoading, runIndexAudit } = useIndexAudit({ selectedDatasetId })
  
  const metricCards = useMemo(() => indexAudit
    ? [
        { key: 'vectorBackend', value: indexAudit.vector_backend || '-', color: 'text-primary' },
        { key: 'activeDocuments', value: indexAudit.active_documents, color: 'text-foreground' },
        { key: 'activeChunks', value: indexAudit.active_chunks, color: 'text-foreground' },
        { key: 'vectorIdMissing', value: indexAudit.vector_id_missing, color: indexAudit.vector_id_missing > 0 ? 'text-destructive' : 'text-emerald-500' },
        { key: 'checkedIds', value: indexAudit.vector_ids_checked, color: 'text-foreground/70' },
        { key: 'missingInBackend', value: indexAudit.vector_ids_missing_in_backend, color: indexAudit.vector_ids_missing_in_backend > 0 ? 'text-destructive' : 'text-emerald-500' },
        { key: 'milvusSampled', value: indexAudit.milvus_ids_sampled, color: 'text-foreground/70' },
        { key: 'orphanSample', value: (indexAudit.milvus_orphan_ids_sample || []).length, color: (indexAudit.milvus_orphan_ids_sample || []).length > 0 ? 'text-warning' : 'text-emerald-500' },
      ]
    : [], [indexAudit])

  const renderDiagnosticHeader = () => (
    <div className="flex items-start justify-between gap-4 mb-6">
      <div className="flex items-center gap-3">
        <div className={cn(
          "flex size-10 items-center justify-center rounded-xl border transition-all duration-500",
          indexAuditLoading ? "bg-primary/10 border-primary/40 shadow-[0_0_15px_-5px_rgba(var(--primary),0.5)]" : "bg-muted/30 border-border/40"
        )}>
          {indexAuditLoading ? <Scan className="size-5 text-primary animate-pulse" /> : <ShieldCheck className="size-5 text-muted-foreground/60" />}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-black uppercase tracking-[0.2em] text-primary/40 leading-none">{t("header.badge")}</span>
            <div className={cn("size-1 rounded-full", selectedDatasetId ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]" : "bg-muted-foreground/20")} />
          </div>
          <h4 className="text-sm font-bold text-foreground tracking-tight mt-1">{t("header.title")}</h4>
        </div>
      </div>

      <Button
        type="button"
        variant={indexAuditLoading ? "secondary" : "outline"}
        className={cn(
          "h-9 rounded-xl border-border/60 bg-background/50 px-4 text-xs font-black uppercase tracking-tight transition-all active:scale-[0.98]",
          indexAuditLoading && "border-primary/30 text-primary"
        )}
        onClick={() => detachPromise(runIndexAudit())}
        disabled={!selectedDatasetId || indexAuditLoading}
      >
        {indexAuditLoading ? (
          <Loader2 className="mr-2 size-3.5 animate-spin" />
        ) : (
          <RefreshCw className="mr-2 size-3.5" />
        )}
        {indexAuditLoading ? t("actions.running") : t("actions.run")}
      </Button>
    </div>
  )

  const renderCompactHeader = () => (
    <div className="border-b border-border/40 bg-background/40 px-5 py-4 backdrop-blur-xl">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary border border-primary/20">
            <Fingerprint className="size-4" />
          </div>
          <div className="min-w-0">
            <h4 className="text-[13px] font-bold text-foreground leading-none">{t("header.title")}</h4>
            <div className="flex items-center gap-1.5 mt-1.5 min-w-0">
              <span className="text-[9px] font-bold text-muted-foreground/40 uppercase tracking-tighter shrink-0">{t("header.currentDataset")}</span>
              <span className="text-[10px] font-bold font-mono text-muted-foreground/80 truncate px-1.5 py-0.5 rounded bg-muted/40">
                {selectedDatasetId || t("header.noneSelected")}
              </span>
            </div>
          </div>
        </div>
        <IconButton
          label={t("actions.run")}
          variant="outline"
          size="sm"
          className={cn("size-8 rounded-lg", indexAuditLoading && "text-primary border-primary/20")}
          onClick={() => detachPromise(runIndexAudit())}
          disabled={!selectedDatasetId || indexAuditLoading}
        >
          {indexAuditLoading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
        </IconButton>
      </div>
    </div>
  )

  if (compact) {
    return (
      <div className="flex h-full flex-col bg-background/30">
        {renderCompactHeader()}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 no-scrollbar">
          {indexAuditError && (
            <div className="p-3 rounded-xl border border-destructive/20 bg-destructive/5 text-[11px] font-medium text-destructive leading-relaxed">
              <AlertTriangle className="size-3.5 mb-1.5" />
              {indexAuditError}
            </div>
          )}

          {indexAudit ? (
            <div className="space-y-2">
               {metricCards.map(item => (
                 <div key={item.key} className="flex items-center justify-between p-3 rounded-xl border border-border/40 bg-background/40 hover:bg-background/60 transition-colors">
                   <span className="text-[11px] font-bold text-muted-foreground/50 uppercase tracking-tight">{t(`metrics.${item.key}`)}</span>
                   <span className={cn("text-xs font-black font-mono tabular-nums", item.color)}>{item.value}</span>
                 </div>
               ))}
               <AnimatePresence>
                 {(indexAudit.milvus_orphan_ids_sample || []).length > 0 && (
                   <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} className="mt-4 pt-4 border-t border-border/40">
                      <div className="text-[10px] font-black text-warning uppercase tracking-widest mb-2 flex items-center gap-1.5">
                        <Activity className="size-3" />
                        {t("samples.orphanIds")}
                      </div>
                      <div className="p-3 rounded-xl bg-zinc-950/90 font-mono text-[10px] text-zinc-400 max-h-32 overflow-y-auto leading-relaxed border border-white/5">
                        {indexAudit.milvus_orphan_ids_sample.join('\n')}
                      </div>
                   </motion.div>
                 )}
               </AnimatePresence>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center opacity-30 px-4">
              <div className="size-16 rounded-[2rem] border-2 border-dashed border-border flex items-center justify-center mb-4">
                <ShieldCheck className="size-8" />
              </div>
              <p className="text-[11px] font-bold uppercase tracking-widest leading-relaxed">{t("empty.title")}<br/>{t("empty.description")}</p>
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto w-full p-6 animate-in fade-in slide-in-from-bottom-3 duration-500">
      <Panel padding="none" className="overflow-hidden rounded-[2.5rem] border border-border/60 bg-background/80 shadow-strong backdrop-blur-2xl relative">
        {/* Dynamic Scanning Glow */}
        {indexAuditLoading && (
          <motion.div 
            initial={{ left: '-100%' }}
            animate={{ left: '100%' }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
            className="absolute top-0 h-0.5 w-1/3 bg-gradient-to-r from-transparent via-primary/50 to-transparent z-20"
          />
        )}
        
        <div className="p-8">
          {renderDiagnosticHeader()}

          {indexAuditError ? (
            <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="mb-6 p-4 rounded-2xl border border-destructive/20 bg-destructive/5 flex gap-3 items-start">
              <AlertTriangle className="size-4 text-destructive shrink-0 mt-0.5" />
              <div className="space-y-1">
                <div className="text-xs font-bold text-destructive">审计执行中断</div>
                <p className="text-[11px] text-destructive/80 leading-relaxed font-medium">{indexAuditError}</p>
              </div>
            </motion.div>
          ) : null}

          {indexAudit ? (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {metricCards.map((item) => (
                  <div key={item.key} className="p-4 rounded-2xl border border-border/40 bg-background/40 hover:border-primary/20 transition-all group/metric shadow-inner-soft">
                    <div className="text-[10px] font-black uppercase tracking-widest text-muted-foreground/40 mb-2 group-hover/metric:text-primary/60 transition-colors">
                      {t(`metrics.${item.key}`)}
                    </div>
                    <div className={cn("text-xl font-black font-mono tabular-nums tracking-tighter", item.color)}>
                      {item.value}
                    </div>
                  </div>
                ))}
              </div>

              <div className="grid gap-6 md:grid-cols-2 mt-8">
                {(indexAudit.vector_ids_missing_in_backend_sample || []).length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-destructive">
                      <div className="size-1.5 rounded-full bg-destructive animate-pulse" />
                      {t("samples.missingInBackend")}
                    </div>
                    <pre className="max-h-56 overflow-auto rounded-[1.5rem] border border-destructive/10 bg-destructive/[0.02] p-4 text-[11px] font-mono leading-loose text-destructive/70 no-scrollbar">
                      {(indexAudit.vector_ids_missing_in_backend_sample || []).join('\n')}
                    </pre>
                  </div>
                )}

                {(indexAudit.milvus_orphan_ids_sample || []).length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-warning">
                      <div className="size-1.5 rounded-full bg-warning animate-pulse" />
                      {t("samples.orphanIds")}
                    </div>
                    <pre className="max-h-56 overflow-auto rounded-[1.5rem] border border-warning/10 bg-warning/[0.02] p-4 text-[11px] font-mono leading-loose text-warning/70 no-scrollbar">
                      {(indexAudit.milvus_orphan_ids_sample || []).join('\n')}
                    </pre>
                  </div>
                )}
              </div>
            </motion.div>
          ) : (
            <div className="flex flex-col items-center justify-center py-20 text-center space-y-6">
              <div className="relative">
                <div className="absolute inset-0 bg-primary/10 rounded-full blur-3xl opacity-20 scale-150" />
                <div className="relative size-20 rounded-[2.5rem] border-2 border-dashed border-border/60 flex items-center justify-center bg-background/50">
                  <Scan className="size-8 text-muted-foreground/20" />
                </div>
              </div>
              <div className="max-w-xs space-y-2">
                <h5 className="text-sm font-bold text-foreground/80">就绪审计座舱</h5>
                <p className="text-xs text-muted-foreground/50 leading-relaxed font-medium">
                  运行一次审计后，这里会通过像素级扫描，展示当前数据集的向量索引一致性和异常样本。
                </p>
              </div>
              {selectedDatasetId ? (
                <Button 
                  onClick={() => detachPromise(runIndexAudit())}
                  className="rounded-full bg-primary/10 text-primary hover:bg-primary/20 border border-primary/20 shadow-none px-6 text-xs font-bold"
                >
                  <Activity className="size-3.5 mr-2" />
                  立即初始化审计
                </Button>
              ) : (
                <div className="text-[10px] font-black uppercase tracking-[0.15em] text-warning/60 bg-warning/5 px-3 py-1 rounded-full border border-warning/10">
                  {t("empty.waitingForDataset")}
                </div>
              )}
            </div>
          )}
        </div>
      </Panel>
    </div>
  )
}
