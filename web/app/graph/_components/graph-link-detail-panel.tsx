'use client'

import { Button } from '@/components/ui/button'

import { ChevronDown, ChevronUp, FileText, GitBranch, X } from '@/components/icons'

import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { cn } from '@/lib/utils'

import {
  bucketConfidence,
  getGraphLinkConfidence,
  getGraphLinkEndpointId,
  getGraphLinkKind,
  getGraphLinkPredicate,
  type GraphLinkLike,
} from '../graph-page-utils'
import styles from './graph-workspace.module.css'

type GraphLinkDetailPanelProps = Readonly<{
  open: boolean
  selectedLink: GraphLinkLike | null
  graphLinks: GraphLinkLike[]
  selfLoopGroupExpanded: boolean
  onToggleSelfLoopGroup: () => void
  onOntologyEdit?: () => void
  onClose: () => void
}>

function getEndpointLabel(endpoint: GraphLinkLike['source']): string {
  if (typeof endpoint === 'object' && endpoint) {
    return toTrimmedPrimitiveString(endpoint.label ?? endpoint.id)
  }
  return toTrimmedPrimitiveString(endpoint)
}

function getGraphLinkKindLabel(kind: string): string {
  if (kind === 'entity_relation') return 'Relation (triple)'
  if (kind === 'event_entity') return 'Evidence (event → entity)'
  if (kind === 'entity_entity') return 'Co-occurrence (entity ↔ entity)'
  return kind || 'Link'
}

function getGraphLinkEpisodesLabel(episodesRaw: unknown): string {
  if (Array.isArray(episodesRaw)) return String(episodesRaw.length)
  return toTrimmedPrimitiveString(episodesRaw)
}

function getConfidenceClass(confidence: number): string {
  const bucket = bucketConfidence(confidence)
  if (bucket === 'high') return 'bg-success'
  if (bucket === 'medium') return 'bg-warning'
  return 'bg-destructive'
}

export function GraphLinkDetailPanel({
  open,
  selectedLink,
  graphLinks,
  selfLoopGroupExpanded,
  onToggleSelfLoopGroup,
  onOntologyEdit,
  onClose,
}: GraphLinkDetailPanelProps) {
  let detailContent: React.ReactNode = null

  if (selectedLink) {
    const srcObj = selectedLink.source
    const tgtObj = selectedLink.target
    const srcLabel = getEndpointLabel(srcObj)
    const tgtLabel = getEndpointLabel(tgtObj)
    const srcId = getGraphLinkEndpointId(srcObj)
    const tgtId = getGraphLinkEndpointId(tgtObj)
    const isSelfLoop = Boolean(srcId) && srcId === tgtId
    const kind = getGraphLinkKind(selectedLink)
    const predicate = getGraphLinkPredicate(selectedLink)
    const confidence = getGraphLinkConfidence(selectedLink)
    const metadata = selectedLink.meta
    const docId = toTrimmedPrimitiveString(metadata?.document_id)
    const chunkId = toTrimmedPrimitiveString(metadata?.chunk_id)
    const eventId = toTrimmedPrimitiveString(metadata?.event_id)
    const page = toTrimmedPrimitiveString(metadata?.page ?? metadata?.page_number)
    const sharedEvents = toTrimmedPrimitiveString(metadata?.shared_events)
    const fact = toTrimmedPrimitiveString(metadata?.fact ?? metadata?.quote ?? metadata?.text)
    const selfLoopLinks = isSelfLoop
      ? graphLinks.filter((link) => {
          const sourceId = getGraphLinkEndpointId(link.source)
          const targetId = getGraphLinkEndpointId(link.target)
          return Boolean(sourceId) && sourceId === targetId && sourceId === srcId
        })
      : []
    const showSelfLoopGroup = isSelfLoop && selfLoopLinks.length > 1
    const kindLabel = getGraphLinkKindLabel(kind)

    let selfLoopGroupSection: React.ReactNode = null
    if (showSelfLoopGroup) {
      let selfLoopDetails: React.ReactNode = null
      if (selfLoopGroupExpanded) {
        selfLoopDetails = (
          <div className="mt-3 space-y-2">
            {selfLoopLinks.slice(0, 12).map((link, idx) => {
              const edgeMetadata = link.meta
              const edgeId = toTrimmedPrimitiveString(link.id ?? edgeMetadata?.id)
              const edgeKind = getGraphLinkKind(link)
              const edgePredicate = getGraphLinkPredicate(link)
              const createdAt = toTrimmedPrimitiveString(edgeMetadata?.created_at ?? edgeMetadata?.created)
              const episodesRaw = edgeMetadata?.episodes ?? edgeMetadata?.episode_ids ?? edgeMetadata?.episode_count
              const episodes = getGraphLinkEpisodesLabel(episodesRaw)
              const fact = toTrimmedPrimitiveString(edgeMetadata?.fact ?? edgeMetadata?.quote ?? edgeMetadata?.text)
              const secondary = [edgeKind, edgePredicate].filter(Boolean).join(' · ')

              let edgeMeta: React.ReactNode = null
              if (createdAt || episodes || fact) {
                edgeMeta = (
                  <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                    {createdAt ? (
                      <div className="truncate" title={createdAt}>
                        <span className="opacity-70">Created</span>: {createdAt}
                      </div>
                    ) : null}
                    {episodes ? (
                      <div className="truncate" title={episodes}>
                        <span className="opacity-70">Episodes</span>: {episodes}
                      </div>
                    ) : null}
                    {fact ? (
                      <div className="col-span-2 truncate" title={fact}>
                        <span className="opacity-70">Fact</span>: {fact}
                      </div>
                    ) : null}
                  </div>
                )
              }

              return (
                <div
                  key={edgeId || `${edgePredicate}-${idx}`}
                  className="rounded-lg border border-border bg-background/60 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-foreground truncate">
                        {edgePredicate || edgeKind || 'self-loop'}
                      </div>
                      {secondary ? <div className="text-[11px] text-muted-foreground truncate">{secondary}</div> : null}
                    </div>
                    {edgeId ? (
                      <div className="text-[11px] font-mono text-muted-foreground">{edgeId.slice(0, 8)}</div>
                    ) : null}
                  </div>
                  {edgeMeta}
                </div>
              )
            })}

            {selfLoopLinks.length > 12 ? (
              <div className="text-[11px] text-muted-foreground">仅显示前 12 条（共 {selfLoopLinks.length} 条）</div>
            ) : null}
          </div>
        )
      }

      selfLoopGroupSection = (
        <div className={styles.propertyCard}>
          <button
            type="button"
            onClick={onToggleSelfLoopGroup}
            className="w-full flex items-center justify-between gap-2 text-left"
            aria-expanded={selfLoopGroupExpanded}
          >
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-muted-foreground mb-1">Self-loop Group</div>
              <div className="text-sm font-medium text-foreground truncate">{srcLabel || srcId}</div>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-[11px] font-mono text-muted-foreground">{selfLoopLinks.length}</span>
              {selfLoopGroupExpanded ? (
                <ChevronUp className="w-4 h-4 text-muted-foreground" />
              ) : (
                <ChevronDown className="w-4 h-4 text-muted-foreground" />
              )}
            </div>
          </button>
          {selfLoopDetails}
        </div>
      )
    }

    let provenanceSection: React.ReactNode = null
    if (docId || chunkId || eventId || page) {
      provenanceSection = (
        <div>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-3 flex items-center gap-2">
            <FileText className="w-3 h-3" />
            Provenance
          </h3>
          <div className="space-y-3">
            {docId ? (
              <div className={styles.propertyCard}>
                <span className="block text-[11px] font-medium text-muted-foreground mb-1">Document</span>
                <span className="block text-xs font-mono text-foreground break-all">{docId}</span>
              </div>
            ) : null}
            {eventId ? (
              <div className={styles.propertyCard}>
                <span className="block text-[11px] font-medium text-muted-foreground mb-1">Event</span>
                <span className="block text-xs font-mono text-foreground break-all">{eventId}</span>
              </div>
            ) : null}
            {chunkId ? (
              <div className={styles.propertyCard}>
                <span className="block text-[11px] font-medium text-muted-foreground mb-1">Chunk</span>
                <span className="block text-xs font-mono text-foreground break-all">{chunkId}</span>
              </div>
            ) : null}
            {page ? (
              <div className={styles.propertyCard}>
                <span className="block text-[11px] font-medium text-muted-foreground mb-1">Page</span>
                <span className="block text-sm text-foreground">{page}</span>
              </div>
            ) : null}
          </div>
        </div>
      )
    }

    detailContent = (
      <>
        <div className={cn(styles.inspectorHeader, 'p-5 flex items-start justify-between')}>
          <div className="flex-1 min-w-0">
            <h2 className="flex items-center gap-2 font-medium text-sm text-foreground mb-2">
              <i className={styles.iconTray} aria-hidden="true">
                <GitBranch />
              </i>
              Relationship
            </h2>
            <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted rounded-lg p-2.5 border border-border">
              <span className="truncate font-medium text-foreground" title={srcLabel}>
                {srcLabel}
              </span>
              <span className="text-primary font-semibold flex-shrink-0">→</span>
              <span className="truncate text-primary font-medium" title={predicate}>
                {predicate === '' ? kindLabel : predicate}
              </span>
              <span className="text-primary font-semibold flex-shrink-0">→</span>
              <span className="truncate font-medium text-foreground" title={tgtLabel}>
                {tgtLabel}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭边详情面板"
            className="text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg p-1 transition-colors ml-2 flex-shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-5 space-y-4">
          {onOntologyEdit && (
            <Button type="button" variant="outline" size="sm" onClick={onOntologyEdit}>
              查看与修正关系
            </Button>
          )}
          <div className="space-y-3">
            {selfLoopGroupSection}

            <div className={styles.propertyCard}>
              <span className="block text-[11px] font-medium text-muted-foreground mb-1">Type</span>
              <span className={styles.typeBadge}>{kindLabel}</span>
            </div>

            {predicate ? (
              <div className={styles.propertyCard}>
                <span className="block text-[11px] font-medium text-muted-foreground mb-1">Predicate</span>
                <span className="block text-sm text-foreground">{predicate}</span>
              </div>
            ) : null}

            {confidence !== null ? (
              <div className={styles.propertyCard}>
                <span className="block text-[11px] font-medium text-muted-foreground mb-1">Confidence</span>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-border rounded-full overflow-hidden" aria-hidden="true">
                    <div
                      className={cn('h-full rounded-full', getConfidenceClass(confidence))}
                      style={{ width: `${Math.round(confidence * 100)}%` }}
                    />
                  </div>
                  <span className="text-xs font-mono text-foreground">{confidence.toFixed(3)}</span>
                </div>
              </div>
            ) : null}

            {sharedEvents !== '' ? (
              <div className={styles.propertyCard}>
                <span className="block text-[11px] font-medium text-muted-foreground mb-1">Shared Events</span>
                <span className="block text-sm text-foreground">{sharedEvents}</span>
              </div>
            ) : null}
          </div>

          {fact ? <blockquote className={styles.evidenceQuote}>{fact}</blockquote> : null}
          {provenanceSection}
        </div>
      </>
    )
  }

  return (
    <div
      className={cn(
        styles.linkInspector,
        'absolute top-4 right-4 bottom-24 z-20 flex w-80 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-none transition-transform duration-200 ease-out',
        open && selectedLink ? 'translate-x-0' : 'translate-x-[120%]',
      )}
    >
      {detailContent}
    </div>
  )
}
