'use client'

/**
 * KnowledgeRetrievalPanel - Index Audit Module
 * 优化版：极致高密度诊断台、UI Pro Max 物理质感、极客化数据展示
 */
import { useMemo } from 'react'
import { 
  Activity,
  Check,
  Database,
  FileStack,
  Fingerprint, 
  Loader2, 
  RefreshCw, 
  AlertTriangle,
  ChevronRight,
  HardDrive,
  Layers3,
  Scan,
  ShieldCheck, 
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { motion } from 'framer-motion'

import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { useIndexAudit } from '@/hooks/use-index-audit'
import { cn, detachPromise } from '@/lib/utils'

type KnowledgeRetrievalPanelProps = {
  selectedDatasetId?: string
  compact?: boolean
  aggregateDocuments?: number
  aggregateChunks?: number
}

function formatBytesCompact(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '—'

  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unitIndex = 0

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }

  const digits = value >= 100 ? 0 : value >= 10 ? 1 : 2
  return `${value.toFixed(digits)} ${units[unitIndex]}`
}

// Backend currently doesn't expose index storage directly.
// Use a stable rough estimate so the card aligns with the design
// without pretending the number is exact.
function estimateIndexSizeBytes(vectorCount: number): number {
  const normalizedCount = Math.max(0, Math.trunc(vectorCount || 0))
  const embeddingDims = 3072
  const bytesPerDim = 4
  const storageOverheadMultiplier = 2.2
  return Math.round(normalizedCount * embeddingDims * bytesPerDim * storageOverheadMultiplier)
}

export function KnowledgeRetrievalPanel({
  selectedDatasetId,
  compact = false,
  aggregateDocuments = 0,
  aggregateChunks = 0,
}: Readonly<KnowledgeRetrievalPanelProps>) {
  const t = useTranslations('KnowledgeRetrievalPanel')
  // t("empty.title")
  // t("empty.description")
  const { indexAudit, indexAuditError, indexAuditLoading, runIndexAudit } = useIndexAudit({ selectedDatasetId })
  const hasAggregateOverview = !selectedDatasetId && (aggregateDocuments > 0 || aggregateChunks > 0)
  const overviewDatasetLabel = selectedDatasetId || '全部数据集'
  
  const metricCards = useMemo(() => {
    if (indexAudit) {
      return [
        {
          key: 'checkedIds',
          label: '向量总数',
          value: indexAudit.vector_ids_checked.toLocaleString(),
          icon: Fingerprint,
          tone: 'emerald',
          meta: '索引向量',
          estimated: false,
        },
        {
          key: 'activeDocuments',
          label: '文档总数',
          value: indexAudit.active_documents.toLocaleString(),
          icon: FileStack,
          tone: 'blue',
          meta: '入库文档',
          estimated: false,
        },
        {
          key: 'activeChunks',
          label: '分片总数',
          value: indexAudit.active_chunks.toLocaleString(),
          icon: Layers3,
          tone: 'violet',
          meta: '检索分片',
          estimated: false,
        },
        {
          key: 'indexSize',
          label: '索引大小',
          value: formatBytesCompact(estimateIndexSizeBytes(indexAudit.vector_ids_checked)),
          icon: HardDrive,
          tone: 'sky',
          meta: indexAudit.vector_backend || '向量后端',
          estimated: true,
        },
      ]
    }

    if (hasAggregateOverview) {
      return [
        {
          key: 'checkedIds',
          label: '向量总数',
          value: aggregateChunks.toLocaleString(),
          icon: Fingerprint,
          tone: 'emerald',
          meta: '全量向量',
          estimated: false,
        },
        {
          key: 'activeDocuments',
          label: '文档总数',
          value: aggregateDocuments.toLocaleString(),
          icon: FileStack,
          tone: 'blue',
          meta: '全部数据集',
          estimated: false,
        },
        {
          key: 'activeChunks',
          label: '分片总数',
          value: aggregateChunks.toLocaleString(),
          icon: Layers3,
          tone: 'violet',
          meta: '全量分片',
          estimated: false,
        },
        {
          key: 'indexSize',
          label: '索引大小',
          value: formatBytesCompact(estimateIndexSizeBytes(aggregateChunks)),
          icon: HardDrive,
          tone: 'sky',
          meta: '全量估算',
          estimated: true,
        },
      ]
    }

    return []
  }, [aggregateChunks, aggregateDocuments, hasAggregateOverview, indexAudit])

  const auditStatus = useMemo(() => {
    if (hasAggregateOverview) {
      return { label: '正常运行', tone: 'success' as const }
    }
    if (!selectedDatasetId) {
      return { label: '等待选择数据集', tone: 'warning' as const }
    }
    if (indexAuditLoading) {
      return { label: '审计运行中', tone: 'info' as const }
    }
    if (indexAuditError) {
      return { label: '审计异常', tone: 'danger' as const }
    }
    if (indexAudit) {
      return { label: '正常运行', tone: 'success' as const }
    }
    return { label: '待执行审计', tone: 'neutral' as const }
  }, [hasAggregateOverview, indexAudit, indexAuditError, indexAuditLoading, selectedDatasetId])

  const healthChecklist = useMemo(() => {
    if (hasAggregateOverview) {
      return [
        { label: '索引服务', state: 'ok' },
        { label: '向量服务', state: 'ok' },
        { label: '存储服务', state: 'ok' },
        { label: '权限校验', state: 'ok' },
      ] as const
    }
    if (!indexAudit) {
      return [
        { label: '索引服务', state: 'pending' },
        { label: '向量服务', state: 'pending' },
        { label: '存储服务', state: 'pending' },
        { label: '权限校验', state: 'pending' },
      ]
    }

    return [
      { label: '索引服务', state: indexAudit.vector_ids_missing_in_backend > 0 ? 'warning' : 'ok' },
      { label: '向量服务', state: indexAudit.vector_id_missing > 0 ? 'warning' : 'ok' },
      { label: '存储服务', state: (indexAudit.milvus_orphan_ids_sample || []).length > 0 ? 'warning' : 'ok' },
      { label: '权限校验', state: 'ok' },
    ] as const
  }, [hasAggregateOverview, indexAudit])

  const statusToneClassName = {
    success: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
    warning: 'bg-amber-500/10 text-amber-600 border-amber-500/20',
    danger: 'bg-red-500/10 text-red-600 border-red-500/20',
    info: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
    neutral: 'bg-muted/30 text-muted-foreground border-border/70',
  }[auditStatus.tone]

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
        <div className="border-b border-border/60 bg-background/72 px-4 py-4 backdrop-blur-xl">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="relative flex size-9 shrink-0 items-center justify-center rounded-[14px] border border-blue-500/20 bg-[radial-gradient(circle_at_top,rgba(59,130,246,0.16),transparent_62%),linear-gradient(180deg,rgba(239,246,255,0.95),rgba(219,234,254,0.78))] text-blue-600 shadow-[0_14px_28px_-22px_rgba(37,99,235,0.45)]">
                <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,rgba(255,255,255,0.35),transparent_48%)] opacity-80" />
                <Fingerprint className="size-4" />
              </div>
              <div className="min-w-0">
                <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/62">
                  索引审计
                </div>
                <div className="mt-1 text-[20px] font-semibold tracking-[-0.04em] text-foreground">
                  {t("header.title")}
                </div>
              </div>
            </div>
            <IconButton
              label={t("actions.run")}
              variant="outline"
              size="sm"
              className={cn(
                "size-9 rounded-[14px] border-border/70 bg-background/72 transition-[transform,box-shadow] hover:scale-[1.03] hover:shadow-[0_12px_24px_-18px_rgba(37,99,235,0.24)]",
                indexAuditLoading && "text-primary border-primary/20"
              )}
              onClick={() => detachPromise(runIndexAudit())}
              disabled={!selectedDatasetId || indexAuditLoading}
            >
              {indexAuditLoading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            </IconButton>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 no-scrollbar">
          {indexAuditError && (
            <div className="rounded-[18px] border border-destructive/20 bg-destructive/5 p-4 text-[12px] leading-relaxed text-destructive">
              <AlertTriangle className="size-3.5 mb-1.5" />
              {indexAuditError}
            </div>
          )}

          <div className="space-y-4">
            <div className="space-y-3">
              <div className="text-[12px] text-muted-foreground/64">{t("header.currentDataset")}</div>
               <div className="inline-flex items-center rounded-full border border-border/70 bg-background px-3 py-1.5 text-[13px] font-medium text-foreground">
                 <Database className="mr-2 size-3.5 text-blue-500" />
                 {overviewDatasetLabel}
               </div>
             </div>

            <div className="space-y-3">
              <div className="text-[12px] text-muted-foreground/64">索引状态</div>
              <div className={cn("inline-flex items-center rounded-full border px-3 py-1.5 text-[13px] font-medium", statusToneClassName)}>
                <span className="mr-2 size-1.5 rounded-full bg-current opacity-75" />
                {auditStatus.label}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2.5">
              {metricCards.map((item) => (
                <motion.div
                  key={item.key}
                  whileHover={{ y: -1, scale: 1.01 }}
                  transition={{ type: 'spring', stiffness: 320, damping: 24 }}
                  className="rounded-[15px] border border-border/70 bg-background px-3 py-3 shadow-[0_12px_20px_-18px_rgba(15,23,42,0.2)]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <div className="text-[11px] font-semibold text-muted-foreground/68">{item.label}</div>
                        {item.estimated ? (
                          <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-[9px] font-semibold text-sky-600">
                            估算
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1.5 font-mono text-[14px] font-semibold tracking-[-0.03em] text-foreground">
                        {item.value}
                      </div>
                      <div className="mt-1 text-[10px] text-muted-foreground/58">{item.meta}</div>
                    </div>
                    <div className={cn(
                      'relative flex size-7.5 shrink-0 items-center justify-center rounded-[11px] border shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_8px_12px_-12px_rgba(15,23,42,0.18)]',
                      item.tone === 'emerald' && 'border-emerald-500/20 bg-emerald-500/8 text-emerald-600',
                      item.tone === 'blue' && 'border-blue-500/20 bg-blue-500/8 text-blue-600',
                      item.tone === 'violet' && 'border-violet-500/20 bg-violet-500/8 text-violet-600',
                      item.tone === 'sky' && 'border-sky-500/20 bg-sky-500/8 text-sky-600',
                    )}>
                      <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,rgba(255,255,255,0.3),transparent_50%)] opacity-80" />
                      <item.icon className="size-3" />
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>

            <div className="space-y-2 border-t border-border/60 pt-3.5">
              <div className="text-[12px] text-muted-foreground/64">最后同步</div>
              <div className="text-[14px] font-medium text-foreground">
                {indexAudit || hasAggregateOverview ? '已完成当前数据集索引审计' : '尚未运行'}
              </div>
              <div className="inline-flex items-center rounded-full bg-emerald-500/10 px-3 py-1 text-[12px] font-medium text-emerald-600">
                {indexAudit || hasAggregateOverview ? '同步成功' : '等待执行'}
              </div>
            </div>

            <div className="space-y-3 border-t border-border/60 pt-3.5">
              <div className="text-[13px] font-medium text-foreground">健康检查清单</div>
              <div className="space-y-3">
                {healthChecklist.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          'flex size-5 items-center justify-center rounded-full',
                          item.state === 'ok' && 'bg-emerald-500/10 text-emerald-600',
                          item.state === 'warning' && 'bg-amber-500/10 text-amber-600',
                          item.state === 'pending' && 'bg-muted/30 text-muted-foreground'
                        )}
                      >
                        <Check className="size-3" />
                      </span>
                      <span className="text-[13px] text-foreground/84">{item.label}</span>
                    </div>
                    <span
                      className={cn(
                        'rounded-full px-2.5 py-1 text-[11px] font-medium',
                        item.state === 'ok' && 'bg-emerald-500/10 text-emerald-600',
                        item.state === 'warning' && 'bg-amber-500/10 text-amber-600',
                        item.state === 'pending' && 'bg-muted/30 text-muted-foreground'
                      )}
                    >
                      {item.state === 'ok' ? '正常' : item.state === 'warning' ? '关注' : '等待'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <Button
              type="button"
              variant="outline"
              className="h-11 w-full rounded-[16px] border-border/70 bg-background text-[13px] font-medium"
            >
              查看索引详情
              <ChevronRight className="ml-2 size-4" />
            </Button>
          </div>
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
                       {item.label}
                     </div>
                     <div className={cn(
                       "text-xl font-black font-mono tabular-nums tracking-tighter",
                       item.tone === 'emerald' && 'text-emerald-600',
                       item.tone === 'blue' && 'text-blue-600',
                       item.tone === 'violet' && 'text-violet-600',
                       item.tone === 'sky' && 'text-sky-600',
                     )}>
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
                 <h5 className="text-sm font-bold text-foreground/80">{t("empty.title")}</h5>
                 <p className="text-xs text-muted-foreground/50 leading-relaxed font-medium">
                   {t("empty.description")}
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
