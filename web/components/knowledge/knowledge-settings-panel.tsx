'use client'

/**
 * KnowledgeSettingsPanel & KnowledgeConnectorRunsPanel
 * 优化版：任务中心极致高密度、UI Pro Max 视觉增强
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  History,
  Info,
  Link2,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Settings,
  Terminal,
  Trash2,
  X,
  Shield,
  TriangleAlert,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Panel } from '@/components/ui/panel'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Switch } from '@/components/ui/switch'

import { connectorApi, datasetApi, settingsApi, type SystemSettings } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise, formatDate, formatDurationMs } from '@/lib/utils'
import type { ConnectorInfo, ConnectorRunOut, Dataset } from '@/types'

// --- 类型定义 ---
type KnowledgeSettingsConfig = Pick<SystemSettings, 'embedding' | 'rag'>
type ConnectorRunStatusFilter = 'all' | 'pending' | 'running' | 'failed' | 'completed' | 'cancelled'
type TranslateFn = (key: string, values?: Record<string, any>) => string

type KnowledgeSettingsPanelProps = {
  selectedDatasetId?: string
}

type KnowledgeConnectorRunsPanelProps = {
  selectedDatasetId?: string
  connectorRuns: ConnectorRunOut[]
  connectorRunsLoading: boolean
  onCancelConnectorRun: (id: string) => void | Promise<void>
  onResumeConnectorRun: (id: string) => void | Promise<void>
  onRetryFailedConnectorRun: (id: string) => void | Promise<void>
  onLoadConnectorRuns: (params: { datasetId?: string }) => void | Promise<void>
}

// --- 辅助函数 ---
function getConnectorRunBadge(status: string, t: any): { status: StatusBadgeStatus; label: string } {
  const s = String(status || '').toLowerCase()
  switch (s) {
    case 'completed': return { status: 'completed', label: t('runStatus.completed') }
    case 'failed': return { status: 'failed', label: t('runStatus.failed') }
    case 'running': return { status: 'processing', label: t('runStatus.running') }
    case 'pending': return { status: 'pending', label: t('runStatus.pending') }
    case 'cancelled': return { status: 'cancelled', label: t('runStatus.cancelled') }
    default: return { status: 'pending', label: s || 'Unknown' }
  }
}

function getConnectorRunProgress(stats: any) {
  const total = Number(stats?.total_items || stats?.items_total || stats?.total_urls || 0)
  const processed = Number(stats?.processed_items || stats?.items_processed || stats?.processed_urls || 0)
  return { total, processed }
}

const EMBEDDING_MODEL_OPTIONS = ['text-embedding-v3', 'text-embedding-3-small', 'bge-large-zh'] as const
const EMBEDDING_MODEL_META: Record<(typeof EMBEDDING_MODEL_OPTIONS)[number], { description: string; chips: string[] }> = {
  'text-embedding-v3': {
    description: '兼顾精度与成本，适合作为系统默认模型。',
    chips: ['推荐默认', '中英混合', '通用语义'],
  },
  'text-embedding-3-small': {
    description: '响应更轻量，适合成本敏感或高频检索场景。',
    chips: ['低成本', '响应快', 'OpenAI 兼容'],
  },
  'bge-large-zh': {
    description: '中文语义更强，适合中文知识库和条款型文本。',
    chips: ['中文增强', '本地可部署', '长文本友好'],
  },
}

// --- KnowledgeSettingsPanel 实现 ---
export function KnowledgeSettingsPanel({ selectedDatasetId }: Readonly<KnowledgeSettingsPanelProps>) {
  const t = useTranslations('KnowledgeSettingsPanel')
  const [draftConfig, setDraftConfig] = useState<KnowledgeSettingsConfig | null>(null)
  const [savedConfig, setSavedConfig] = useState<KnowledgeSettingsConfig | null>(null)
  const [settingsLoading, setSettingsLoading] = useState(true)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [confirmEmbeddingSaveOpen, setConfirmEmbeddingSaveOpen] = useState(false)

  const loadSettings = useCallback(async () => {
    setSettingsLoading(true)
    try {
      const settings = await settingsApi.get()
      const cfg = { embedding: settings.embedding, rag: settings.rag }
      setSavedConfig(cfg); setDraftConfig(JSON.parse(JSON.stringify(cfg)))
    } catch (err) { toast.error(formatApiError(err, t('toasts.loadFailed'))) } finally { setSettingsLoading(false) }
  }, [t])

  useEffect(() => { detachPromise(loadSettings()) }, [loadSettings])

  const isDirty = useMemo(() => JSON.stringify(savedConfig) !== JSON.stringify(draftConfig), [savedConfig, draftConfig])
  const handleResetDraft = useCallback(() => {
    setDraftConfig(savedConfig ? JSON.parse(JSON.stringify(savedConfig)) : null)
    setConfirmEmbeddingSaveOpen(false)
  }, [savedConfig])

  const handleSave = async () => {
    if (!draftConfig || isSavingSettings) return
    setIsSavingSettings(true)
    try {
      await settingsApi.update(draftConfig)
      setSavedConfig(JSON.parse(JSON.stringify(draftConfig)))
      toast.success(t('toasts.saveSuccess'))
    } catch (err) { toast.error(formatApiError(err, t('toasts.saveFailed'))) } finally { setIsSavingSettings(false); setConfirmEmbeddingSaveOpen(false) }
  }

  if (settingsLoading && !draftConfig) return <div className="p-8 space-y-4 animate-pulse"><div className="h-20 bg-muted/20 rounded-2xl" /><div className="h-40 bg-muted/20 rounded-2xl" /></div>

  return (
    <div className="flex flex-col h-full overflow-hidden bg-background/50">
      <div className="flex-1 overflow-y-auto p-6 space-y-8 no-scrollbar">
        {/* Embedding Section */}
        <section className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="size-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary border border-primary/20"><Database className="size-4" /></div>
            <div>
              <h3 className="text-sm font-bold text-foreground">嵌入模型配置 / Embedding</h3>
              <p className="text-[10px] text-muted-foreground/50 uppercase tracking-widest font-medium mt-0.5">Vector Dimension & Model Choice</p>
            </div>
          </div>
          
          <div className="grid gap-3">
            {EMBEDDING_MODEL_OPTIONS.map((model) => (
              <button 
                key={model} 
                onClick={() => setDraftConfig(prev => prev ? ({ ...prev, embedding: { ...prev.embedding, model } }) : null)}
                className={cn(
                  "relative text-left p-4 rounded-2xl border transition-all duration-300",
                  draftConfig?.embedding.model === model 
                    ? "border-primary/40 bg-primary/[0.03] shadow-inner-soft ring-1 ring-primary/20" 
                    : "border-border/40 bg-background/40 hover:border-border/80"
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[13px] font-bold text-foreground">{model}</span>
                  {draftConfig?.embedding.model === model && <div className="size-2 rounded-full bg-primary shadow-[0_0_8px_rgba(var(--primary),0.6)]" />}
                </div>
                <p className="text-xs text-muted-foreground/70 leading-relaxed mb-3">{EMBEDDING_MODEL_META[model].description}</p>
                <div className="flex flex-wrap gap-2">
                  {EMBEDDING_MODEL_META[model].chips.map(chip => (
                    <span key={chip} className="text-[9px] font-bold px-2 py-0.5 rounded-md bg-muted/50 text-muted-foreground/60 border border-border/20 uppercase tracking-tighter">{chip}</span>
                  ))}
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* RAG Section */}
        <section className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="size-8 rounded-lg bg-indigo-500/10 flex items-center justify-center text-indigo-500 border border-indigo-500/20"><Settings className="size-4" /></div>
            <div>
              <h3 className="text-sm font-bold text-foreground">检索策略 / Retrieval Strategy</h3>
              <p className="text-[10px] text-muted-foreground/50 uppercase tracking-widest font-medium mt-0.5">Top-K & Similarity Threshold</p>
            </div>
          </div>
          
          <div className="grid md:grid-cols-2 gap-4">
             <div className="p-5 rounded-[2rem] border border-border/40 bg-background/60 space-y-5 group/slider transition-all hover:border-primary/20 hover:shadow-soft">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="text-[11px] font-black text-foreground/80 uppercase tracking-widest leading-none">Top K</span>
                    <span className="text-[9px] text-muted-foreground/40 font-bold mt-1 uppercase">Results count</span>
                  </div>
                  <span className="text-[13px] font-black font-mono text-primary bg-primary/10 px-2.5 py-0.5 rounded-lg border border-primary/20 shadow-inner-soft tabular-nums">
                    {draftConfig?.rag.retrieval_top_k}
                  </span>
                </div>
                <div className="relative flex items-center px-1">
                  <input 
                    type="range" 
                    min="1" 
                    max="20" 
                    value={draftConfig?.rag.retrieval_top_k} 
                    onChange={e => setDraftConfig(prev => prev ? ({...prev, rag: { ...prev.rag, retrieval_top_k: Number(e.target.value) }}) : null)} 
                    className="w-full h-1.5 bg-muted/60 rounded-full appearance-none cursor-pointer accent-primary hover:accent-primary-hover transition-all [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-background [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:hover:scale-110 [&::-webkit-slider-thumb]:transition-transform" 
                  />
                </div>
             </div>
             <div className="p-5 rounded-[2rem] border border-border/40 bg-background/60 space-y-5 group/slider transition-all hover:border-primary/20 hover:shadow-soft">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="text-[11px] font-black text-foreground/80 uppercase tracking-widest leading-none">Similarity</span>
                    <span className="text-[9px] text-muted-foreground/40 font-bold mt-1 uppercase">Threshold Score</span>
                  </div>
                  <span className="text-[13px] font-black font-mono text-primary bg-primary/10 px-2.5 py-0.5 rounded-lg border border-primary/20 shadow-inner-soft tabular-nums">
                    {draftConfig?.rag.similarity_threshold.toFixed(2)}
                  </span>
                </div>
                <div className="relative flex items-center px-1">
                  <input 
                    type="range" 
                    min="0" 
                    max="1" 
                    step="0.05" 
                    value={draftConfig?.rag.similarity_threshold} 
                    onChange={e => setDraftConfig(prev => prev ? ({...prev, rag: { ...prev.rag, similarity_threshold: Number(e.target.value) }}) : null)} 
                    className="w-full h-1.5 bg-muted/60 rounded-full appearance-none cursor-pointer accent-primary hover:accent-primary-hover transition-all [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-background [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:hover:scale-110 [&::-webkit-slider-thumb]:transition-transform" 
                  />
                </div>
             </div>
          </div>
        </section>
      </div>

      {/* Footer Actions */}
      <AnimatePresence>
        {isDirty && (
          <motion.div initial={{ y: 50 }} animate={{ y: 0 }} exit={{ y: 50 }} className="p-4 border-t border-border/40 bg-muted/20 backdrop-blur-md flex items-center justify-between">
            <span className="text-[11px] font-bold text-primary px-3">检测到配置已修改，请及时保存</span>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" className="rounded-xl h-9 px-4 text-xs font-bold" onClick={handleResetDraft}>放弃修改</Button>
              <Button size="sm" className="rounded-xl h-9 px-6 text-xs font-bold shadow-md shadow-primary/20" onClick={() => (savedConfig?.embedding.model !== draftConfig?.embedding.model ? setConfirmEmbeddingSaveOpen(true) : handleSave())}>
                {isSavingSettings ? <Loader2 className="size-3.5 animate-spin mr-2" /> : <CheckCircle2 className="size-3.5 mr-2" />}
                应用全部修改
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Confirm Dialog */}
      <AlertDialog open={confirmEmbeddingSaveOpen} onOpenChange={setConfirmEmbeddingSaveOpen}>
        <AlertDialogContent className="sm:rounded-[2rem] border-border/40 shadow-strong backdrop-blur-xl bg-background/90">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-bold tracking-tight">确认更改嵌入模型？</AlertDialogTitle>
            <AlertDialogDescription className="text-sm font-medium leading-relaxed">
              更换模型将导致已有文档的向量失效，所有文档必须重新进入 Ingestion 管线进行向量化。这可能产生显著的 Token 消耗和处理耗时。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="h-10 rounded-xl">取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleSave} className="h-10 rounded-xl bg-primary text-primary-foreground shadow-md shadow-primary/20">确认重置并应用</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// --- KnowledgeConnectorRunsPanel 实现 ---
export function KnowledgeConnectorRunsPanel({
  selectedDatasetId,
  connectorRuns,
  connectorRunsLoading,
  onCancelConnectorRun,
  onResumeConnectorRun,
  onRetryFailedConnectorRun,
  onLoadConnectorRuns,
}: Readonly<KnowledgeConnectorRunsPanelProps>) {
  const t = useTranslations('KnowledgeSettingsPanel')
  const [runStatusFilter, setRunStatusFilter] = useState<ConnectorRunStatusFilter>('all')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  
  const stats = useMemo(() => ({
    total: connectorRuns.length,
    active: connectorRuns.filter(r => r.status === 'running' || r.status === 'pending').length,
    failed: connectorRuns.filter(r => r.status === 'failed').length,
    completed: connectorRuns.filter(r => r.status === 'completed').length,
  }), [connectorRuns])

  const visibleRuns = useMemo(() => {
    let list = runStatusFilter === 'all' 
      ? connectorRuns 
      : connectorRuns.filter(r => String(r.status).toLowerCase() === runStatusFilter)
    
    return [...list].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  }, [connectorRuns, runStatusFilter])

  useEffect(() => {
    if (!autoRefresh || stats.active === 0) return
    const id = setInterval(() => onLoadConnectorRuns({ datasetId: selectedDatasetId }), 5000)
    return () => clearInterval(id)
  }, [autoRefresh, stats.active, selectedDatasetId, onLoadConnectorRuns])

  return (
    <div className="flex flex-col h-full bg-background/50">
      {/* 头部：原子级操作岛 */}
      <div className="px-5 py-4 border-b border-border/40 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="size-3.5 text-primary/60" />
            <span className="text-[10px] font-black uppercase tracking-[0.2em] text-foreground/80">{t('connectorRuns.title')}</span>
          </div>
          
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-muted/30 border border-border/40">
              <div className={cn("size-1 rounded-full transition-all", autoRefresh ? "bg-emerald-500 animate-pulse shadow-[0_0_5px_rgba(16,185,129,0.4)]" : "bg-muted-foreground/30")} />
              <span className="text-[9px] font-bold text-foreground/50 uppercase tracking-tighter">{t('connectorRuns.liveBadge')}</span>
              <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} className="scale-[0.5] origin-right" />
            </div>
            <IconButton 
              label="刷新" 
              variant="ghost" 
              size="sm" 
              className="h-6 w-6 rounded-md text-muted-foreground hover:text-foreground" 
              onClick={() => onLoadConnectorRuns({ datasetId: selectedDatasetId })}
            >
              <RefreshCw className={cn("size-3", connectorRunsLoading && "animate-spin")} />
            </IconButton>
          </div>
        </div>

        {/* 高密度状态分段器 */}
        <div className="flex p-0.5 bg-muted/40 rounded-lg border border-border/40">
          {[
            { key: 'all', label: t('connectorRuns.summary.all'), count: stats.total, color: 'text-foreground' },
            { key: 'running', label: t('connectorRuns.summary.active'), count: stats.active, color: 'text-primary' },
            { key: 'failed', label: t('runStatus.failed'), count: stats.failed, color: 'text-destructive' },
            { key: 'completed', label: t('runStatus.completed'), count: stats.completed, color: 'text-emerald-500' },
          ].map((item) => (
            <button
              key={item.key}
              onClick={() => setRunStatusFilter(item.key as any)}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[10px] font-black transition-all duration-200",
                runStatusFilter === item.key 
                  ? "bg-background text-primary shadow-sm ring-1 ring-border/10 " + item.color
                  : "text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/40"
              )}
            >
              <span>{item.label}</span>
              <span className="tabular-nums opacity-40 text-[9px]">{item.count}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2.5 no-scrollbar">
        <AnimatePresence mode="popLayout">
          {visibleRuns.length === 0 ? (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col items-center justify-center py-24 text-center opacity-30">
              <History className="size-10 text-muted-foreground/10 mb-2" />
              <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/30">Quiet Environment</span>
            </motion.div>
          ) : (
            visibleRuns.map((run) => (
              <TaskCard 
                key={run.id} 
                run={run} 
                t={t}
                onCancel={onCancelConnectorRun}
                onResume={onResumeConnectorRun}
                onRetry={onRetryFailedConnectorRun}
                isExpanded={expandedRunId === run.id}
                onToggleExpand={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
              />
            ))
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function TaskCard({ run, t, onCancel, onRetry, isExpanded, onToggleExpand }: any) {
  const badge = getConnectorRunBadge(run.status, t)
  const { total, processed } = getConnectorRunProgress(run.stats || {})
  const progressPct = total > 0 ? Math.round((processed / total) * 100) : 0
  const isFailed = run.status === 'failed'
  const isRunning = run.status === 'running' || run.status === 'pending'
  
  return (
    <motion.div 
      layout
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className={cn(
        "group relative rounded-2xl border transition-all duration-300",
        isRunning ? "border-primary/30 bg-primary/[0.03]" : "border-border/40 bg-background/40 hover:border-border/80"
      )}
    >
      <div className="p-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className={cn("size-8 shrink-0 rounded-lg flex items-center justify-center border shadow-sm", 
              isFailed ? "bg-destructive/10 border-destructive/20 text-destructive" : 
              isRunning ? "bg-primary/10 border-primary/20 text-primary" : "bg-muted/40 border-border/40 text-muted-foreground")}>
              <Link2 className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-[12px] font-bold text-foreground truncate max-w-[140px] leading-none">{run.connector_id}</span>
                <div className={cn("size-1.5 rounded-full", 
                  isFailed ? "bg-destructive shadow-[0_0_6px_rgba(var(--destructive),0.5)]" : 
                  isRunning ? "bg-primary animate-pulse" : "bg-muted-foreground/30")} />
              </div>
              <div className="flex items-center gap-1.5 text-[9px] font-bold text-muted-foreground/40 tabular-nums mt-1 uppercase tracking-tighter">
                <span>{formatDate(run.created_at)}</span>
                <span>·</span>
                <span>{run.id.slice(0, 8)}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {isRunning && (
              <IconButton label="取消" variant="ghost" size="sm" className="h-7 w-7 rounded-md text-muted-foreground hover:text-destructive" onClick={() => onCancel(run.id)}>
                <X className="size-3.5" />
              </IconButton>
            )}
            {isFailed && (
              <IconButton label="重试" variant="ghost" size="sm" className="h-7 w-7 rounded-md text-muted-foreground hover:text-primary" onClick={() => onRetry(run.id)}>
                <RotateCcw className="size-3.5" />
              </IconButton>
            )}
            <IconButton label="复制" variant="ghost" size="sm" className="h-7 w-7 rounded-md text-muted-foreground" onClick={() => { navigator.clipboard.writeText(run.id); toast.success("Copied") }}>
              <Terminal className="size-3.5" />
            </IconButton>
          </div>
        </div>

        {total > 0 && (
          <div className="space-y-1.5">
            <div className="h-1 w-full bg-muted/40 rounded-full overflow-hidden">
               <motion.div initial={{ width: 0 }} animate={{ width: `${progressPct}%` }} className={cn("h-full transition-colors", isFailed ? "bg-destructive/60" : "bg-primary/70")} />
            </div>
            <div className="flex items-center justify-between px-0.5">
              <span className="text-[9px] font-black text-foreground/40 uppercase tracking-tighter">{progressPct}% Complete</span>
              <span className="text-[9px] font-bold text-muted-foreground/30 tabular-nums">{processed}/{total}</span>
            </div>
          </div>
        )}

        {isFailed && run.error_message && (
          <button onClick={onToggleExpand} className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-destructive/5 border border-destructive/10 text-destructive/80 hover:bg-destructive/10 transition-colors">
            <span className="text-[9px] font-bold truncate uppercase tracking-wider">Error Details</span>
            <ChevronDown className={cn("size-3 transition-transform", isExpanded && "rotate-180")} />
          </button>
        )}
      </div>

      <AnimatePresence>
        {isExpanded && isFailed && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden bg-zinc-950">
            <div className="p-3 border-t border-white/5 font-mono text-[9px] leading-relaxed text-zinc-500">
              <div className="text-rose-400/80 font-bold mb-1">ERR: {run.error_message}</div>
              {(run.stats?.errors || []).slice(0, 2).map((err: any, i: number) => (
                <div key={i} className="mt-1 opacity-60 truncate">! {err.error}</div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
