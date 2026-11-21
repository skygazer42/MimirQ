'use client'

import { useId, useState } from 'react'
import { useTranslations } from 'next-intl'

import { Check, ChevronDown, Dataset as Database, ArrowRight, Search } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { Link } from '@/i18n/navigation'
import { cn } from '@/lib/utils'
import type { Dataset } from '@/types/datasets'

function splitDatasetLabel(label: string) {
  const suffix = /^(.+)\s+\[([0-9a-f]{6,64})\]$/i.exec(label)
  return suffix === null ? { title: label, hash: null } : { title: suffix[1], hash: suffix[2] }
}

type DatasetScopePickerProps = Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  datasets: Dataset[]
  selectedId: string
  label: string
  documentScoped: boolean
  loading: boolean
  fetching: boolean
  error: Error | null
  onSelect: (datasetId: string) => void
  onRetry: () => void
}>

export function DatasetScopePicker({
  open,
  onOpenChange,
  datasets,
  selectedId,
  label,
  documentScoped,
  loading,
  fetching,
  error,
  onSelect,
  onRetry,
}: DatasetScopePickerProps) {
  const t = useTranslations('Chat')
  const panelId = useId()
  const [search, setSearch] = useState('')
  const datasetLabel = splitDatasetLabel(label)
  const keyword = search.trim().toLocaleLowerCase()
  const visibleDatasets = datasets.filter((dataset) =>
    `${dataset.name} ${dataset.id}`.toLocaleLowerCase().includes(keyword),
  )

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          className="h-11 max-w-full gap-1.5 rounded-lg border border-border/60 bg-muted/30 px-2 text-xs font-medium shadow-none hover:bg-muted/60 data-[state=open]:bg-ring/10 @min-[30rem]:h-8"
          aria-controls={panelId}
          aria-label={label}
          title={label}
          disabled={loading && !documentScoped}
        >
          {loading && !documentScoped ? (
            <span role="status" className="flex w-28 items-center gap-2">
              <span className="sr-only">{t('datasetScopeLoading')}</span>
              <Skeleton asChild className="size-3.5 shrink-0 rounded-full">
                <span />
              </Skeleton>
              <Skeleton asChild className="h-3 flex-1">
                <span />
              </Skeleton>
            </span>
          ) : (
            <>
              <Database className="size-4 shrink-0 text-ring" aria-hidden="true" />
              <span className="min-w-0 truncate font-sans font-medium">{datasetLabel.title}</span>
              {datasetLabel.hash !== null && (
                <span className="hidden max-w-20 shrink-0 truncate rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] font-normal text-muted-foreground @min-[30rem]:inline">
                  {datasetLabel.hash}
                </span>
              )}
            </>
          )}
          <ChevronDown
            className={cn(
              'hidden size-3.5 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none @min-[18rem]:inline',
              open && 'rotate-180',
            )}
            aria-hidden="true"
          />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        id={panelId}
        aria-label={t('datasetMenuTitle')}
        align="start"
        side="bottom"
        sideOffset={8}
        collisionPadding={16}
        className="flex max-h-[min(28rem,var(--radix-popover-content-available-height))] w-[360px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-xl p-2"
      >
        <div className="relative shrink-0">
          <Search
            className="pointer-events-none absolute left-3 top-3.5 size-4 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label={t('filterDatasets')}
            placeholder={t('filterDatasets')}
            className="h-11 border-transparent bg-muted/50 pl-9 text-sm shadow-none"
          />
        </div>
        {documentScoped && <p className="px-2 py-2 text-xs leading-5 text-muted-foreground">{t('datasetScopeHint')}</p>}
        {error !== null && (
          <div role="alert" className="flex items-start justify-between gap-2 px-2 py-2 text-xs text-muted-foreground">
            <p>{datasets.length > 0 ? t('datasetRefreshFailed') : t('datasetScopeFailed')}</p>
            <Button type="button" variant="ghost" size="sm" disabled={fetching} onClick={onRetry}>
              {t('retryDatasets')}
            </Button>
          </div>
        )}
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain py-1">
          {loading ? (
            <div role="status" className="space-y-3 px-2 py-3">
              <span className="sr-only">{t('datasetScopeLoading')}</span>
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-4 w-3/5" />
            </div>
          ) : (
            visibleDatasets.map((dataset) => {
              const name = dataset.name.trim() === '' ? dataset.id : dataset.name
              const datasetName = splitDatasetLabel(name)
              const description = dataset.description
              const summary = dataset.ingestion_summary
              return (
                <button
                  key={dataset.id}
                  type="button"
                  aria-pressed={selectedId === dataset.id}
                  onClick={() => {
                    onSelect(dataset.id)
                    onOpenChange(false)
                  }}
                  className={cn(
                    'flex w-full items-start gap-2 rounded-lg px-2.5 py-2.5 text-left transition-colors hover:bg-muted focus-ring',
                    selectedId === dataset.id && 'bg-ring/10',
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block break-words font-sans text-sm font-medium leading-5">
                      {datasetName.title}
                      {datasetName.hash !== null && (
                        <span className="ml-1.5 break-all rounded bg-muted px-1.5 font-mono text-[10px] font-normal text-muted-foreground">
                          {datasetName.hash}
                        </span>
                      )}
                    </span>
                    {description?.trim() && (
                      <span className="mt-1 block break-words text-xs leading-5 text-muted-foreground">
                        {description}
                      </span>
                    )}
                    <span className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] tabular-nums text-muted-foreground">
                      <span>
                        {t('datasetDocuments')} <span className="font-mono">{summary?.total_documents ?? '—'}</span>
                      </span>
                      <span>
                        {t('datasetChunks')} <span className="font-mono">{summary?.total_chunks ?? '—'}</span>
                      </span>
                    </span>
                  </span>
                  {selectedId === dataset.id && <Check className="mt-1 size-4 shrink-0 text-ring" aria-hidden="true" />}
                </button>
              )
            })
          )}
          {!loading && error === null && datasets.length === 0 && (
            <p className="px-2 py-3 text-sm text-muted-foreground">{t('datasetScopeEmpty')}</p>
          )}
          {!loading && datasets.length > 0 && visibleDatasets.length === 0 && (
            <p className="px-2 py-3 text-sm text-muted-foreground">{t('noMatchingDatasets')}</p>
          )}
        </div>
        <Link
          href="/datasets"
          onClick={() => onOpenChange(false)}
          className="mt-1 flex min-h-11 shrink-0 items-center justify-between rounded-lg border-t border-border px-2.5 text-xs text-muted-foreground hover:bg-muted focus-ring"
        >
          {t('manageDatasets')}
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
      </PopoverContent>
    </Popover>
  )
}
