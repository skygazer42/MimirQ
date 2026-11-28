'use client'

import { Copy, Parsing, Chunking, DataGovernance } from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import { useTranslations } from 'next-intl'
import type { ReactNode } from 'react'

import { IconButton } from '@/components/ui/icon-button'
import { Panel } from '@/components/ui/panel'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { getParserLabel } from '@/lib/parser-options'
import { cn } from '@/lib/utils'
import type { Document } from '@/types/documents'

type DocumentDetailSummaryCardsProps = Readonly<{
  document: Pick<Document, 'pipeline' | 'governance'>
  viewingPipelineHash: string | null | undefined
  activePipelineHash: string | null | undefined
  onCopyPipelineHash: (hash: string) => void
}>

type SummaryValue = string | number | boolean | null | undefined

type SummaryRowProps = {
  label: string
  value: SummaryValue
  mono?: boolean
}

function formatSummaryValue(value: SummaryValue, t: ReturnType<typeof useTranslations<'DocumentDetailDialog'>>) {
  if (value === null || value === undefined) return t('cards.notProvided')
  if (value === '') return t('cards.emptyValue')
  if (typeof value === 'boolean') return value ? t('cards.enabledValue') : t('cards.disabledValue')
  return String(value)
}

function SummaryRow({ label, value, mono }: Readonly<SummaryRowProps>) {
  const t = useTranslations('DocumentDetailDialog')
  const display = formatSummaryValue(value, t)

  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className={cn('min-w-0 truncate text-foreground', mono ? 'font-mono' : null)} title={display}>
        {display}
      </dd>
    </div>
  )
}

function SummaryCard({
  title,
  subtitle,
  icon: Icon,
  iconSurface,
  aside,
  children,
}: Readonly<{
  title: string
  subtitle: ReactNode
  icon: PlatformIcon
  iconSurface: 'icon-surface-process' | 'icon-surface-governance'
  aside?: ReactNode
  children: ReactNode
}>) {
  return (
    <Panel className="rounded-2xl">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className={cn('grid size-10 shrink-0 place-items-center rounded-2xl border', iconSurface)}>
            <Icon appearance="color" className="size-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground">{title}</h3>
            <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
          </div>
        </div>
        {aside}
      </div>
      <dl className="mt-3 space-y-1.5">{children}</dl>
    </Panel>
  )
}

export function DocumentDetailSummaryCards({
  document,
  viewingPipelineHash,
  activePipelineHash,
  onCopyPipelineHash,
}: DocumentDetailSummaryCardsProps) {
  const t = useTranslations('DocumentDetailDialog')
  const { pipeline, governance } = document
  const parserBackend = pipeline?.parser_backend
  const chunkStrategy = pipeline?.chunk_strategy
  const rulePacks = pipeline?.governance_rule_packs
  const analytics = pipeline?.analytics_raw
  const effectivePipeline = pipeline?.pipeline_effective
  const governanceStatusLabel =
    governance === undefined
      ? t('cards.notProvided')
      : t(governance.enabled ? 'cards.governance.enabled' : 'cards.governance.disabled')

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <SummaryCard
        title={t('cards.parse.title')}
        subtitle={formatSummaryValue(parserBackend ? getParserLabel(parserBackend) : parserBackend, t)}
        icon={Parsing}
        iconSurface="icon-surface-process"
      >
        <SummaryRow label={t('cards.fields.parser')} value={parserBackend} mono />
        <SummaryRow label={t('cards.fields.requestedParser')} value={pipeline?.parser_backend_requested} mono />
        <SummaryRow label={t('cards.fields.charCount')} value={analytics?.char_count} mono />
        <SummaryRow label={t('cards.fields.pageCount')} value={analytics?.page_count} mono />
        <SummaryRow label={t('cards.fields.tableCount')} value={analytics?.table_count} mono />
        <SummaryRow label={t('cards.fields.imageCount')} value={analytics?.image_count} mono />
      </SummaryCard>

      <SummaryCard
        title={t('cards.governance.title')}
        subtitle={governanceStatusLabel}
        icon={DataGovernance}
        iconSurface="icon-surface-governance"
        aside={
          rulePacks !== undefined && rulePacks.length > 0 ? (
            <span className="shrink-0 rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-[11px] text-muted-foreground">
              {t('cards.governance.packsCount', { count: rulePacks.length })}
            </span>
          ) : null
        }
      >
        <SummaryRow label={t('cards.fields.rulesApplied')} value={governance?.rules_applied} mono />
        <SummaryRow label={t('cards.fields.changedDocuments')} value={governance?.changed_documents} mono />
        <SummaryRow label={t('cards.fields.droppedDocuments')} value={governance?.dropped_documents} mono />
        <SummaryRow label={t('cards.fields.rulePacks')} value={rulePacks?.join(', ')} />
      </SummaryCard>

      <SummaryCard
        title={t('cards.chunking.title')}
        subtitle={
          <span title={chunkStrategy === null ? undefined : chunkStrategy}>
            {formatSummaryValue(chunkStrategy ? getChunkStrategyLabel(chunkStrategy) : chunkStrategy, t)}
          </span>
        }
        icon={Chunking}
        iconSurface="icon-surface-process"
        aside={
          viewingPipelineHash ? (
            <IconButton
              label={t('cards.chunking.copyPipelineHash')}
              variant="ghost"
              className="h-9 w-9 text-muted-foreground hover:text-foreground"
              onClick={() => onCopyPipelineHash(viewingPipelineHash)}
            >
              <Copy className="h-4 w-4" aria-hidden="true" />
            </IconButton>
          ) : null
        }
      >
        <SummaryRow label={t('cards.fields.viewingVersion')} value={viewingPipelineHash} mono />
        <SummaryRow label={t('cards.fields.activeVersion')} value={activePipelineHash} mono />
        <SummaryRow label={t('cards.fields.lastVersion')} value={pipeline?.pipeline_hash} mono />
        <SummaryRow label={t('cards.fields.chunkSize')} value={effectivePipeline?.chunk_size} mono />
        <SummaryRow label={t('cards.fields.chunkOverlap')} value={effectivePipeline?.chunk_overlap} mono />
        <SummaryRow label={t('cards.fields.vectorEnabled')} value={effectivePipeline?.chunk_vector_enabled} />
        <SummaryRow label={t('cards.fields.bm25Enabled')} value={effectivePipeline?.bm25_index_enabled} />
      </SummaryCard>
    </div>
  )
}
