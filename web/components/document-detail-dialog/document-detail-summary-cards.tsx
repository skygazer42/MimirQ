'use client'

import { Copy, FileText, Hash, Shield } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { IconButton } from '@/components/ui/icon-button'
import { Panel } from '@/components/ui/panel'
import { cn } from '@/lib/utils'

type AnalyticsLike = {
  char_count?: unknown
  page_count?: unknown
  table_count?: unknown
  image_count?: unknown
}

type PipelineEffectiveLike = {
  chunk_size?: unknown
  chunk_overlap?: unknown
  chunk_vector_enabled?: unknown
  bm25_index_enabled?: unknown
}

type DocumentDetailSummaryCardsProps = Readonly<{
  parserLabel: string | null
  parserBackend: string
  requestedParserBackend: string
  chunkStrategyLabel: string | null
  chunkStrategy: string
  analyticsRaw: AnalyticsLike
  governanceEnabled: boolean
  governanceRulesApplied: unknown
  governanceChangedDocuments: unknown
  governanceDroppedDocuments: unknown
  governanceRulePacks: string[]
  viewingPipelineHash: string
  activePipelineHash: string
  lastPipelineHash: string
  pipelineEffective: PipelineEffectiveLike
  onCopyPipelineHash: (hash: string) => void
}>

function TraceRow({ label, value, mono }: Readonly<{ label: string; value: string; mono?: boolean }>) {
  const display = value?.trim?.() ? value : '-'

  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn('min-w-0 truncate text-foreground', mono ? 'font-mono' : null)} title={display}>
        {display}
      </span>
    </div>
  )
}

export function DocumentDetailSummaryCards({
  parserLabel,
  parserBackend,
  requestedParserBackend,
  chunkStrategyLabel,
  chunkStrategy,
  analyticsRaw,
  governanceEnabled,
  governanceRulesApplied,
  governanceChangedDocuments,
  governanceDroppedDocuments,
  governanceRulePacks,
  viewingPipelineHash,
  activePipelineHash,
  lastPipelineHash,
  pipelineEffective,
  onCopyPipelineHash,
}: DocumentDetailSummaryCardsProps) {
  const t = useTranslations('DocumentDetailDialog')

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Panel className="rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-primary/10 text-primary">
              <FileText className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">{t('cards.parse.title')}</div>
              <div className="text-xs text-muted-foreground truncate">{parserLabel || parserBackend || '-'}</div>
            </div>
          </div>
        </div>
        <div className="mt-3 space-y-1.5">
          <TraceRow label="parser_backend" value={String(parserBackend || '-')} mono />
          <TraceRow label="requested" value={String(requestedParserBackend || '-')} mono />
          <TraceRow label="char_count" value={String(analyticsRaw?.char_count ?? '-')} mono />
          <TraceRow label="page_count" value={String(analyticsRaw?.page_count ?? '-')} mono />
          <TraceRow label="table_count" value={String(analyticsRaw?.table_count ?? '-')} mono />
          <TraceRow label="image_count" value={String(analyticsRaw?.image_count ?? '-')} mono />
        </div>
      </Panel>

      <Panel className="rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-success/10 text-success">
              <Shield className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">{t('cards.governance.title')}</div>
              <div className="text-xs text-muted-foreground truncate">
                {governanceEnabled ? t('cards.governance.enabled') : t('cards.governance.disabled')}
              </div>
            </div>
          </div>
          {governanceRulePacks.length ? (
            <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-[11px] text-muted-foreground">
              {t('cards.governance.packsCount', { count: governanceRulePacks.length })}
            </span>
          ) : null}
        </div>
        <div className="mt-3 space-y-1.5">
          <TraceRow label="rules_applied" value={String(governanceRulesApplied ?? '-')} mono />
          <TraceRow label="changed_docs" value={String(governanceChangedDocuments ?? '-')} mono />
          <TraceRow label="dropped_docs" value={String(governanceDroppedDocuments ?? '-')} mono />
          <TraceRow
            label="rule_packs"
            value={governanceRulePacks.length ? governanceRulePacks.slice(0, 4).join(', ') : '-'}
          />
        </div>
      </Panel>

      <Panel className="rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-info/10 text-info">
              <Hash className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">{t('cards.chunking.title')}</div>
              <div className="text-xs text-muted-foreground truncate">{chunkStrategyLabel || chunkStrategy || '-'}</div>
            </div>
          </div>
          {viewingPipelineHash ? (
            <IconButton
              label={t('cards.chunking.copyPipelineHash')}
              variant="ghost"
              className="h-9 w-9 text-muted-foreground hover:text-foreground"
              onClick={() => onCopyPipelineHash(String(viewingPipelineHash || ''))}
            >
              <Copy className="h-4 w-4" />
            </IconButton>
          ) : null}
        </div>
        <div className="mt-3 space-y-1.5">
          <TraceRow label="viewing_pipeline_hash" value={String(viewingPipelineHash || '-')} mono />
          <TraceRow label="active_pipeline_hash" value={String(activePipelineHash || '-')} mono />
          <TraceRow label="last_pipeline_hash" value={String(lastPipelineHash || '-')} mono />
          <TraceRow label="chunk_size" value={String(pipelineEffective?.chunk_size ?? '-')} mono />
          <TraceRow label="chunk_overlap" value={String(pipelineEffective?.chunk_overlap ?? '-')} mono />
          <TraceRow label="vector_enabled" value={pipelineEffective?.chunk_vector_enabled ? 'true' : 'false'} mono />
          <TraceRow label="bm25_enabled" value={pipelineEffective?.bm25_index_enabled ? 'true' : 'false'} mono />
        </div>
      </Panel>
    </div>
  )
}
