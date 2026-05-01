'use client'

import { useMemo, useState } from 'react'

import type { ParsingElement } from '@/lib/api/parsing'
import { cn } from '@/lib/utils'

type ParsingElementsPanelProps = {
  elements: ParsingElement[]
  onSelectElement?: (element: ParsingElement) => void
  className?: string
}

function kindLabel(kind: string): string {
  if (kind === 'seal') return '印章'
  if (kind === 'equation') return '公式'
  if (kind === 'table') return '表格'
  if (kind === 'image') return '图片'
  if (kind === 'heading') return '标题'
  if (kind === 'list') return '列表'
  return '正文'
}

function formatBbox(value: ParsingElement['bbox']): string {
  if (!value) return ''
  return `${value.x0},${value.y0},${value.x1},${value.y1}`
}

function formatPageLabel(element: ParsingElement): string {
  const pages = Array.isArray(element.pages)
    ? element.pages.filter((value) => Number.isInteger(value) && value > 0)
    : []
  if (pages.length >= 2) {
    if (pages.length === 2 && pages[1] === pages[0] + 1) {
      return `页 ${pages[0]}-${pages[1]}`
    }
    return `页 ${pages.join(',')}`
  }
  if (typeof element.page === 'number') {
    return `页 ${element.page}`
  }
  return ''
}

function formatCrossPageMergePages(attributes: ParsingElement['attributes']): string {
  const raw = (attributes as Record<string, unknown> | null)?.cross_page_merge_pages
  if (!Array.isArray(raw)) return ''
  const pages = raw
    .map((value) => (typeof value === 'number' ? value : Number(value)))
    .filter((value) => Number.isInteger(value) && value > 0)
  if (pages.length < 2) return ''
  if (pages.length === 2 && pages[1] === pages[0] + 1) {
    return `跨页 ${pages[0]}-${pages[1]}`
  }
  return `跨页 ${pages.join(',')}`
}

function formatPageSpan(element: ParsingElement): string {
  const pages = Array.isArray(element.pages)
    ? element.pages.filter((value) => Number.isInteger(value) && value > 0)
    : []
  if (pages.length >= 2) {
    if (pages.length === 2 && pages[1] === pages[0] + 1) {
      return `跨页 ${pages[0]}-${pages[1]}`
    }
    return `跨页 ${pages.join(',')}`
  }
  return formatCrossPageMergePages(element.attributes)
}

export function ParsingElementsPanel({
  elements,
  onSelectElement,
  className,
}: Readonly<ParsingElementsPanelProps>) {
  const [isCollapsed, setIsCollapsed] = useState(true)
  const [filterKind, setFilterKind] = useState<string>('all')
  const [filterVisualKind, setFilterVisualKind] = useState<string>('all')
  const filterKinds = useMemo(() => {
    const kinds = new Set<string>(['all'])
    for (const element of elements || []) {
      const kind = String(element.kind || '').trim()
      if (kind) kinds.add(kind)
    }
    return Array.from(kinds)
  }, [elements])
  const filterVisualKinds = useMemo(() => {
    const visualKinds = new Set<string>(['all'])
    for (const element of elements || []) {
      const visualKind = String(element.visual_kind || (element.attributes as Record<string, unknown> | null)?.visual_kind || '').trim()
      if (visualKind) visualKinds.add(visualKind)
    }
    return Array.from(visualKinds)
  }, [elements])
  const visibleElements = useMemo(() => {
    return (elements || []).filter((element) => {
      if (filterKind !== 'all' && element.kind !== filterKind) return false
      if (filterVisualKind === 'all') return true
      const visualKind = String(element.visual_kind || (element.attributes as Record<string, unknown> | null)?.visual_kind || '').trim()
      return visualKind === filterVisualKind
    })
  }, [elements, filterKind, filterVisualKind])

  if (!elements.length) return null

  return (
    <div className={cn('border-b border-border/60 bg-background/70 px-5 py-2.5', className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              结构元素列表
            </div>
            <span className="rounded-full border border-border/50 bg-background/80 px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
              {elements.length} items
            </span>
          </div>
          {!isCollapsed ? (
            <div className="mt-1 text-[12px] leading-5 text-muted-foreground/80">
              直接筛选并审阅印章、公式、表格、图片等结构元素。
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {!isCollapsed ? (
            filterKinds.map((kind) => (
              <button
                key={kind}
                type="button"
                onClick={() => {
                  setFilterKind(kind)
                  if (kind !== 'image') setFilterVisualKind('all')
                }}
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                  filterKind === kind
                    ? 'border-primary/40 bg-primary/10 text-foreground'
                    : 'border-border/60 bg-background/90 text-muted-foreground hover:text-foreground/80'
                )}
              >
                {kind === 'all' ? '全部' : kindLabel(kind)}
              </button>
            ))
          ) : null}
          <button
            type="button"
            onClick={() => setIsCollapsed((current) => !current)}
            className="rounded-full border border-border/60 bg-background/90 px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground/80"
          >
            {isCollapsed ? '展开' : '收起'}
          </button>
        </div>
      </div>

      {!isCollapsed && (filterKind === 'all' || filterKind === 'image') && filterVisualKinds.length > 1 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {filterVisualKinds.map((visualKind) => (
            <button
              key={visualKind}
              type="button"
              onClick={() => setFilterVisualKind(visualKind)}
              className={cn(
                'rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                filterVisualKind === visualKind
                  ? 'border-primary/40 bg-primary/10 text-foreground'
                  : 'border-border/60 bg-background/90 text-muted-foreground hover:text-foreground/80'
              )}
            >
              {visualKind === 'all' ? '全部图片子类' : visualKind}
            </button>
          ))}
        </div>
      ) : null}

      {!isCollapsed ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {visibleElements.map((element) => {
            const attributes = (element.attributes as Record<string, unknown> | null) ?? null
            const pageLabel = formatPageLabel(element)
            const crossPageLabel = formatPageSpan(element)
            const visualKind = typeof element.visual_kind === 'string' && element.visual_kind
              ? element.visual_kind
              : typeof attributes?.visual_kind === 'string'
                ? (attributes.visual_kind as string)
                : ''

            return (
              <button
                key={String(element.id)}
                type="button"
                onClick={() => onSelectElement?.(element)}
                className="rounded-xl border border-border/60 bg-background/92 px-3 py-2 text-left transition-colors hover:border-primary/35 hover:bg-primary/5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] font-semibold text-foreground">{kindLabel(String(element.kind || 'paragraph'))}</span>
                  {pageLabel ? <span className="font-mono text-[11px] text-muted-foreground">{pageLabel}</span> : null}
                  <span className="font-mono text-[11px] text-muted-foreground">{element.id}</span>
                  {typeof attributes?.source_content_type === 'string' ? (
                    <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                      {attributes.source_content_type as string}
                    </span>
                  ) : null}
                  {visualKind ? (
                    <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                      {visualKind}
                    </span>
                  ) : null}
                  {typeof element.confidence === 'number' ? (
                    <span className="font-mono text-[11px] text-muted-foreground">{element.confidence.toFixed(2)}</span>
                  ) : null}
                  {crossPageLabel ? (
                    <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                      {crossPageLabel}
                    </span>
                  ) : null}
                </div>
                {element.text ? <div className="mt-1 truncate text-sm text-foreground/85">{element.text}</div> : null}
                {element.bbox ? (
                  <div className="mt-1 font-mono text-[11px] text-muted-foreground">bbox {formatBbox(element.bbox)}</div>
                ) : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
