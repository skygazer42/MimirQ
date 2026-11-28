'use client'

import { useState, useSyncExternalStore, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { Virtualizer } from '@tanstack/react-virtual'
import {
  Ban,
  Calendar,
  CheckCircle2,
  Copy,
  FileText,
  GitBranch,
  Loader2,
  Pencil,
  RefreshCw,
  Save,
  Search,
  X,
} from '@/components/icons'
import { useTranslations } from 'next-intl'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { HighlightedText } from '@/components/ui/highlighted-text'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { lineageApi } from '@/lib/api/lineage'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { cn, formatDate } from '@/lib/utils'
import type { Document, DocumentTimelineItem, DocumentVersionList } from '@/types/documents'
import type { DocumentChunk } from '@/types/processing'

const ACTIVE_PIPELINE_VALUE = '__active__'

type DocumentDetailVirtualizer = Pick<
  Virtualizer<HTMLDivElement, Element>,
  'getTotalSize' | 'getVirtualItems' | 'measureElement'
>

type DocumentDetailActivityPanelProps = Readonly<{
  activeView: 'chunks' | 'timeline'
  onActiveViewChange: (next: 'chunks' | 'timeline') => void
  chunksTabId: string
  timelineTabId: string
  chunksPanelId: string
  timelinePanelId: string
  scrollParentRef: RefObject<HTMLDivElement | null>
  onViewTabKeyDown: (event: ReactKeyboardEvent<HTMLButtonElement>) => void
  chunkQuery: string
  onChunkQueryChange: (next: string) => void
  versions: DocumentVersionList | null
  viewPipelineHash: string
  onViewPipelineHashChange: (next: string) => void
  chunks: DocumentChunk[]
  chunksTotal: number
  isLoadingDoc: boolean
  detail: Document | null
  isLoadingChunks: boolean
  loadError: string | null
  onRetryChunks: () => void
  onClose: () => void
  isSearching: boolean
  chunkError: string | null
  chunkRowVirtualizer: DocumentDetailVirtualizer
  canMutateChunks: boolean
  pendingChunkIds: ReadonlySet<string>
  onBeginEditChunk: (chunk: DocumentChunk) => void
  onToggleChunkDisabled: (chunk: DocumentChunk) => void
  onReembedChunk: (chunk: DocumentChunk) => void
  onCopyText: (text: string) => void
  editingChunkId: string | null
  editingChunkContent: string
  onEditingChunkContentChange: (next: string) => void
  onCancelEditChunk: () => void
  onSaveEditChunk: () => void
  canLoadMoreChunks: boolean
  onLoadMoreChunks: () => void
  timelineItems: DocumentTimelineItem[]
  timelineTotal: number
  isLoadingTimeline: boolean
  timelineError: string | null
  onLoadTimeline: () => void
  timelineRowVirtualizer: DocumentDetailVirtualizer
}>

type ChunkLineageButtonProps = {
  chunkId: string
}

function ChunkLineageButton({ chunkId }: Readonly<ChunkLineageButtonProps>) {
  const [open, setOpen] = useState(false)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <IconButton
          label="查看切片血缘"
          variant="ghost"
          className="h-9 w-9 text-muted-foreground hover:text-foreground"
        >
          <GitBranch className="size-4" aria-hidden="true" />
        </IconButton>
      </DialogTrigger>
      {open && <ChunkLineageDialog key={chunkId} chunkId={chunkId} />}
    </Dialog>
  )
}

function ChunkLineageDialog({ chunkId }: Readonly<ChunkLineageButtonProps>) {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const lineageQuery = useQuery({
    queryKey: [...queryKeys.lineage.chunk(chunkId), sessionKey],
    queryFn: ({ signal }) => lineageApi.getChunkLineage(chunkId, { signal }),
  })
  const reading = lineageQuery.fetchStatus !== 'idle'

  return (
    <DialogContent className="flex max-h-[90dvh] max-w-3xl flex-col overflow-hidden border-border bg-background/95 shadow-strong sm:rounded-2xl">
      <DialogHeader className="min-w-0 shrink-0 pr-8">
        <DialogTitle className="flex items-center gap-2">
          <GitBranch className="size-4 text-info" aria-hidden="true" />
          切片血缘
        </DialogTitle>
        <DialogDescription className="font-mono text-xs [overflow-wrap:anywhere]">切片 ID：{chunkId}</DialogDescription>
      </DialogHeader>
      {reading && (
        <p role="status" className="text-sm text-muted-foreground">
          {lineageQuery.isPaused
            ? '血缘读取已暂停'
            : lineageQuery.isLoading
              ? '正在读取血缘信息…'
              : '正在刷新血缘信息…'}
        </p>
      )}
      {lineageQuery.isError && !reading && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {formatApiError(lineageQuery.error, '加载切片血缘失败')}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void lineageQuery.refetch({ cancelRefetch: false })}
          >
            重新加载
          </Button>
        </div>
      )}
      {lineageQuery.data !== undefined && (
        <pre className="min-h-0 max-h-[520px] overflow-auto whitespace-pre-wrap rounded-lg border border-border/60 bg-muted/20 p-3 text-xs [overflow-wrap:anywhere]">
          {JSON.stringify(lineageQuery.data, null, 2)}
        </pre>
      )}
    </DialogContent>
  )
}

function ActivityListSkeleton({ label }: Readonly<{ label: string }>) {
  return (
    <div role="status" className="space-y-3">
      <span className="sr-only">{label}</span>
      {[0, 1, 2].map((index) => (
        <div key={index} aria-hidden="true" className="rounded-xl border border-border/60 bg-card p-4">
          <div className="flex gap-2">
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-40" />
          </div>
          <Skeleton className="mt-3 h-3 w-full" />
          <Skeleton className="mt-2 h-3 w-2/3" />
        </div>
      ))}
    </div>
  )
}

type TimelineEventCardProps = Readonly<{
  event: DocumentTimelineItem
  onCopyText: (text: string) => void
}>

function TimelineEventCard({ event, onCopyText }: TimelineEventCardProps) {
  const t = useTranslations('DocumentDetailDialog')
  const fields = [
    { key: 'stage', label: t('timeline.meta.stage'), value: event.stage },
    { key: 'status', label: t('timeline.meta.status'), value: event.status },
    {
      key: 'progress',
      label: t('timeline.meta.progress'),
      value: event.progress === null || event.progress === undefined ? null : `${event.progress}%`,
    },
    { key: 'request_id', label: t('timeline.meta.requestId'), value: event.request_id },
    { key: 'actor_id', label: t('timeline.meta.actorId'), value: event.actor_id },
  ]
  const details = event.details === undefined ? [] : Object.entries(event.details)

  return (
    <div className="rounded-xl border border-border/60 bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
              {formatDate(event.created_at)}
            </span>
            <span className="break-all font-mono text-xs text-foreground/90">{event.action}</span>
            {event.source === 'synthetic' ? (
              <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-xs text-muted-foreground">
                {t('timeline.synthetic')}
              </span>
            ) : null}
          </div>
          <dl className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
            {fields.map(({ key, label, value }) =>
              value === null || value === undefined || value.length === 0 ? null : (
                <div key={key} className="flex min-w-0 gap-1 break-all">
                  <dt>{label}:</dt>
                  <dd>{value}</dd>
                </div>
              ),
            )}
          </dl>
        </div>
        <IconButton
          label={t('timeline.actions.copyEvent')}
          variant="ghost"
          className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground"
          onClick={() => onCopyText(JSON.stringify(event, null, 2))}
        >
          <Copy className="h-4 w-4" aria-hidden="true" />
        </IconButton>
      </div>
      {details.length > 0 ? (
        <dl className="mt-3 flex flex-wrap gap-2">
          {details.map(([key, value]) => {
            const text = typeof value === 'string' ? value : JSON.stringify(value)
            return (
              <div
                key={key}
                className="min-w-0 max-w-full rounded-md border border-border/60 bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground"
              >
                <dt className="break-all font-medium">{key}</dt>
                <dd className="whitespace-pre-wrap break-all">{text}</dd>
              </div>
            )
          })}
        </dl>
      ) : null}
    </div>
  )
}

export function DocumentDetailActivityPanel({
  activeView,
  onActiveViewChange,
  chunksTabId,
  timelineTabId,
  chunksPanelId,
  timelinePanelId,
  scrollParentRef,
  onViewTabKeyDown,
  chunkQuery,
  onChunkQueryChange,
  versions,
  viewPipelineHash,
  onViewPipelineHashChange,
  chunks,
  chunksTotal,
  isLoadingDoc,
  detail,
  isLoadingChunks,
  loadError,
  onRetryChunks,
  onClose,
  isSearching,
  chunkError,
  chunkRowVirtualizer,
  canMutateChunks,
  pendingChunkIds,
  onBeginEditChunk,
  onToggleChunkDisabled,
  onReembedChunk,
  onCopyText,
  editingChunkId,
  editingChunkContent,
  onEditingChunkContentChange,
  onCancelEditChunk,
  onSaveEditChunk,
  canLoadMoreChunks,
  onLoadMoreChunks,
  timelineItems,
  timelineTotal,
  isLoadingTimeline,
  timelineError,
  onLoadTimeline,
  timelineRowVirtualizer,
}: DocumentDetailActivityPanelProps) {
  const commonT = useTranslations('Common')
  const documentsT = useTranslations('Documents')
  const t = useTranslations('DocumentDetailDialog')
  const versionItems = versions?.items

  function renderChunksContent() {
    if ((isLoadingDoc && detail === null) || (isLoadingChunks && chunks.length === 0)) {
      return <ActivityListSkeleton label={documentsT('loadingChunks')} />
    }

    if (loadError && chunks.length === 0) {
      return (
        <div className="mx-auto max-w-2xl py-10">
          <Alert variant="destructive">
            <AlertTitle>{t('alerts.loadFailedTitle')}</AlertTitle>
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
          <div className="mt-4 flex items-center justify-end gap-2">
            <Button variant="outline" onClick={onRetryChunks}>
              {commonT('retry')}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              {commonT('close')}
            </Button>
          </div>
        </div>
      )
    }

    if (chunksTotal === 0 && !isSearching) {
      return (
        <EmptyState
          icon={FileText}
          title={documentsT('emptyChunks')}
          description={t('chunks.emptyDescription')}
          className="min-h-[320px]"
        />
      )
    }

    if (chunksTotal === 0 && isSearching) {
      return (
        <EmptyState
          icon={Search}
          title={t('chunks.searchEmptyTitle')}
          description={<span>{t('chunks.searchEmptyDescription')}</span>}
          className="min-h-[320px]"
        >
          <Button variant="outline" onClick={() => onChunkQueryChange('')}>
            {t('chunks.clearFilter')}
          </Button>
        </EmptyState>
      )
    }

    return (
      <div className="pb-6 space-y-3">
        {chunkError && chunks.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>{t('alerts.loadChunksFailedTitle')}</AlertTitle>
            <AlertDescription>{chunkError}</AlertDescription>
          </Alert>
        ) : null}

        <ul
          aria-label={t('chunks.listAriaLabel')}
          className="m-0 list-none p-0"
          style={{ height: `${chunkRowVirtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}
        >
          {chunkRowVirtualizer.getVirtualItems().map((virtualRow) => {
            const chunk = chunks[virtualRow.index]
            if (chunk === undefined) return null

            return (
              <li
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={chunkRowVirtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                className="pb-3"
              >
                <div
                  className={cn(
                    'group rounded-xl border border-border/60 bg-card p-4 transition-colors',
                    'hover:border-primary/25 hover:shadow-soft/30',
                    chunk.disabled_at ? 'opacity-70' : null,
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono font-medium text-muted-foreground">
                        #{chunk.chunk_index}
                      </span>
                      {typeof chunk.page_number === 'number' ? (
                        <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
                          P.{chunk.page_number}
                        </span>
                      ) : null}
                      <span className="text-muted-foreground">
                        {t('chunks.charCount', { count: chunk.content.length })}
                      </span>
                      {chunk.disabled_at ? (
                        <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
                          {t('chunks.disabledBadge')}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-1">
                      <IconButton
                        label={canMutateChunks ? t('chunks.actions.edit') : t('chunks.actions.editDisabled')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onBeginEditChunk(chunk)}
                        disabled={!canMutateChunks || pendingChunkIds.has(chunk.id)}
                      >
                        <Pencil className="h-4 w-4" />
                      </IconButton>
                      <IconButton
                        label={chunk.disabled_at ? t('chunks.actions.enable') : t('chunks.actions.disable')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onToggleChunkDisabled(chunk)}
                        disabled={!canMutateChunks || pendingChunkIds.has(chunk.id)}
                      >
                        {chunk.disabled_at ? <CheckCircle2 className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
                      </IconButton>
                      <IconButton
                        label={chunk.disabled_at ? t('chunks.actions.reembedDisabled') : t('chunks.actions.reembed')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onReembedChunk(chunk)}
                        disabled={!canMutateChunks || Boolean(chunk.disabled_at) || pendingChunkIds.has(chunk.id)}
                      >
                        <RefreshCw className="h-4 w-4" />
                      </IconButton>
                      <ChunkLineageButton chunkId={chunk.id} />
                      <IconButton
                        label={t('chunks.actions.copy')}
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onCopyText(chunk.content)}
                        disabled={pendingChunkIds.has(chunk.id)}
                      >
                        <Copy className="h-4 w-4" />
                      </IconButton>
                    </div>
                  </div>

                  {editingChunkId === chunk.id ? (
                    <div className="mt-3 space-y-2">
                      <Textarea
                        aria-label={t('chunks.editContentLabel', { index: chunk.chunk_index })}
                        value={editingChunkContent}
                        onChange={(e) => onEditingChunkContentChange(e.target.value)}
                        className="min-h-[140px] font-mono text-xs"
                        disabled={!canMutateChunks || pendingChunkIds.has(chunk.id)}
                      />
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={onCancelEditChunk}
                          disabled={pendingChunkIds.has(chunk.id)}
                        >
                          {commonT('cancel')}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          onClick={onSaveEditChunk}
                          disabled={!canMutateChunks || pendingChunkIds.has(chunk.id)}
                          className="gap-2"
                        >
                          {pendingChunkIds.has(chunk.id) ? (
                            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                          ) : (
                            <Save className="h-4 w-4" />
                          )}
                          {commonT('save')}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/90">
                      <HighlightedText
                        content={chunk.content}
                        query={chunkQuery}
                        maxMatches={Number.POSITIVE_INFINITY}
                        markClassName="rounded bg-primary/15 px-0.5 text-foreground"
                      />
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ul>

        {canLoadMoreChunks ? (
          <div className="flex justify-center pt-2">
            <Button variant="outline" onClick={onLoadMoreChunks} disabled={isLoadingChunks} className="gap-2">
              {isLoadingChunks ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
              {t('chunks.loadMore')}
            </Button>
          </div>
        ) : null}
      </div>
    )
  }

  function renderTimelineContent() {
    if (isLoadingTimeline && timelineItems.length === 0) {
      return <ActivityListSkeleton label={documentsT('loadingTimeline')} />
    }

    if (timelineError !== null && timelineItems.length === 0) {
      return (
        <div className="mx-auto max-w-2xl py-10">
          <Alert variant="destructive">
            <AlertTitle>{t('alerts.loadFailedTitle')}</AlertTitle>
            <AlertDescription>{timelineError}</AlertDescription>
          </Alert>
          <div className="mt-4 flex items-center justify-end gap-2">
            <Button variant="outline" onClick={onLoadTimeline}>
              {commonT('retry')}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              {commonT('close')}
            </Button>
          </div>
        </div>
      )
    }

    if (timelineItems.length === 0) {
      return (
        <EmptyState
          icon={Calendar}
          title={documentsT('emptyTimeline')}
          description={t('timeline.emptyDescription')}
          className="min-h-[320px]"
        />
      )
    }

    return (
      <div className="pb-6 space-y-3">
        {timelineError ? (
          <Alert variant="destructive">
            <AlertTitle>{t('alerts.loadTimelineFailedTitle')}</AlertTitle>
            <AlertDescription>{timelineError}</AlertDescription>
          </Alert>
        ) : null}

        <ul
          aria-label={t('timeline.listAriaLabel')}
          className="m-0 list-none p-0"
          style={{ height: `${timelineRowVirtualizer.getTotalSize()}px`, width: '100%', position: 'relative' }}
        >
          {timelineRowVirtualizer.getVirtualItems().map((virtualRow) => {
            const timelineEvent = timelineItems[virtualRow.index]
            if (timelineEvent === undefined) return null

            return (
              <li
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={timelineRowVirtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                className="pb-3"
              >
                <TimelineEventCard event={timelineEvent} onCopyText={onCopyText} />
              </li>
            )
          })}
        </ul>
      </div>
    )
  }

  return (
    <Panel padding="none" className="flex-1 min-h-0 overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center gap-3 border-b border-border/60 bg-background/40 px-4 py-3">
        <div
          className="inline-flex h-10 items-center rounded-md bg-muted p-1 text-muted-foreground"
          role="tablist"
          aria-label={t('views.ariaLabel')}
        >
          <button
            type="button"
            id={chunksTabId}
            role="tab"
            aria-controls={chunksPanelId}
            aria-selected={activeView === 'chunks'}
            tabIndex={activeView === 'chunks' ? 0 : -1}
            className={cn(
              'inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none',
              activeView === 'chunks' ? 'bg-background text-foreground shadow-sm' : 'hover:text-foreground',
            )}
            onClick={() => onActiveViewChange('chunks')}
            onKeyDown={onViewTabKeyDown}
          >
            {t('views.chunks')}
          </button>
          <button
            type="button"
            id={timelineTabId}
            role="tab"
            aria-controls={timelinePanelId}
            aria-selected={activeView === 'timeline'}
            tabIndex={activeView === 'timeline' ? 0 : -1}
            className={cn(
              'inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none',
              activeView === 'timeline' ? 'bg-background text-foreground shadow-sm' : 'hover:text-foreground',
            )}
            onClick={() => onActiveViewChange('timeline')}
            onKeyDown={onViewTabKeyDown}
          >
            {t('views.timeline')}
          </button>
        </div>

        {activeView === 'chunks' ? (
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={chunkQuery}
              aria-label={t('search.placeholder')}
              onChange={(e) => onChunkQueryChange(e.target.value)}
              placeholder={t('search.placeholder')}
              className="h-10 pl-9"
            />
          </div>
        ) : (
          <div className="flex-1 text-sm text-muted-foreground">{t('timeline.description')}</div>
        )}

        {activeView === 'chunks' && versionItems !== undefined && versionItems.length > 0 ? (
          <Select value={viewPipelineHash} onValueChange={onViewPipelineHashChange}>
            <SelectTrigger aria-label={t('versions.selectPlaceholder')} className="h-10 w-full sm:w-[220px]">
              <SelectValue placeholder={t('versions.selectPlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ACTIVE_PIPELINE_VALUE}>{t('versions.active')}</SelectItem>
              {versionItems.map((version) => (
                <SelectItem key={version.pipeline_hash} value={version.pipeline_hash}>
                  {version.active ? t('versions.activeTag') : t('versions.historyTag')}{' '}
                  {version.pipeline_hash.slice(0, 10)}… · {t('versions.chunkCount', { count: version.chunk_count })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}

        <span className="hidden sm:inline-flex rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
          {activeView === 'chunks' ? `${chunks.length}/${chunksTotal}` : `${timelineItems.length}/${timelineTotal}`}
        </span>

        {activeView === 'chunks' ? (
          chunkQuery ? (
            <IconButton
              label={t('search.clear')}
              variant="ghost"
              className="h-10 w-10 text-muted-foreground hover:text-foreground"
              onClick={() => onChunkQueryChange('')}
            >
              <X className="h-4 w-4" />
            </IconButton>
          ) : null
        ) : (
          <IconButton
            label={t('timeline.refresh')}
            variant="ghost"
            className="h-10 w-10 text-muted-foreground hover:text-foreground"
            onClick={onLoadTimeline}
            disabled={isLoadingTimeline}
          >
            {isLoadingTimeline && timelineItems.length > 0 ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </IconButton>
        )}
      </div>

      <div
        ref={scrollParentRef}
        id={activeView === 'chunks' ? chunksPanelId : timelinePanelId}
        role="tabpanel"
        aria-labelledby={activeView === 'chunks' ? chunksTabId : timelineTabId}
        className="h-full overflow-y-auto overscroll-contain no-scrollbar p-4"
      >
        {activeView === 'chunks' ? renderChunksContent() : renderTimelineContent()}
      </div>
    </Panel>
  )
}
