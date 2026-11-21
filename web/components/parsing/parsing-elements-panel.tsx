'use client'

import { useMemo, useState } from 'react'

import { AuthImage } from '@/components/auth-image'
import type { ParsingElement } from '@/lib/api/parsing'
import { cn } from '@/lib/utils'
import {
  formatParsingPages,
  getParsingElementImageSource,
  getParsingElementVisualKind,
  getParsingPages,
} from '@/lib/parsing-elements'
import { getParsingLayoutMeta } from '@/lib/parsing-layout'

type ParsingElementsPanelProps = {
  elements: ParsingElement[]
  onSelectElement: (element: ParsingElement) => void
  className?: string
}

function kindLabel(kind: ParsingElement['kind']): string {
  return kind === 'unknown' ? '未知类型' : getParsingLayoutMeta(kind).label
}

function formatBbox(value: NonNullable<ParsingElement['bbox']>): string {
  return `${value.x0},${value.y0},${value.x1},${value.y1}`
}

function formatCrossPageMergePages(attributes: ParsingElement['attributes']): string | null {
  const raw = attributes?.cross_page_merge_pages
  if (!Array.isArray(raw)) return null
  const numericPages: number[] = []
  for (const value of raw) {
    if (typeof value === 'number') numericPages.push(value)
    else if (typeof value === 'string' && value.trim().length > 0) numericPages.push(Number(value))
  }
  const pages = getParsingPages({ pages: numericPages })
  return pages.length < 2 ? null : formatParsingPages(pages)
}

export function ParsingElementsPanel({ elements, onSelectElement, className }: Readonly<ParsingElementsPanelProps>) {
  const [collapsed, setCollapsed] = useState<boolean>()
  const [selectedKind, setSelectedKind] = useState<ParsingElement['kind'] | 'all'>()
  const [selectedVisualKind, setSelectedVisualKind] = useState<string | null>(null)
  const filterKinds = useMemo(() => {
    const kinds = new Set<ParsingElement['kind'] | 'all'>(['all'])
    for (const element of elements) {
      kinds.add(element.kind)
    }
    return Array.from(kinds)
  }, [elements])
  const hasImageElements = filterKinds.includes('image')
  const isCollapsed = collapsed ?? !hasImageElements
  const filterKind =
    selectedKind !== undefined && filterKinds.includes(selectedKind) ? selectedKind : hasImageElements ? 'image' : 'all'

  const visualKindOptions = useMemo<Array<{ value: string | null; label: string }>>(() => {
    const visualKinds = new Set<string>()
    for (const element of elements) {
      const visualKind = getParsingElementVisualKind(element)
      if (visualKind !== null && visualKind.length > 0) visualKinds.add(visualKind)
    }
    return [
      { value: null, label: '全部图片子类' },
      ...Array.from(visualKinds).map((kind) => ({ value: kind, label: kind })),
    ]
  }, [elements])
  const filterVisualKind = visualKindOptions.some((option) => option.value === selectedVisualKind)
    ? selectedVisualKind
    : null
  const visibleElements = useMemo(() => {
    return elements.filter((element) => {
      if (filterKind !== 'all' && element.kind !== filterKind) return false
      if (filterVisualKind === null) return true
      const visualKind = getParsingElementVisualKind(element)
      return visualKind === filterVisualKind
    })
  }, [elements, filterKind, filterVisualKind])

  if (elements.length === 0) return null

  return (
    <div className={cn('border-b border-border/60 bg-card px-5 py-2.5', className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
              结构元素列表
            </div>
            <span className="rounded-full border border-border/60 bg-card px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
              {elements.length} items
            </span>
          </div>
          {isCollapsed ? null : (
            <div className="mt-1 text-[12px] leading-5 text-muted-foreground/80">
              直接筛选并审阅印章、公式、表格、图片等结构元素。
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {isCollapsed
            ? null
            : filterKinds.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={filterKind === kind}
                  onClick={() => {
                    setSelectedKind(kind)
                    if (kind !== 'image') setSelectedVisualKind(null)
                  }}
                  className={cn(
                    'rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                    filterKind === kind
                      ? 'border-primary/40 bg-primary/10 text-foreground'
                      : 'border-border/60 bg-card text-muted-foreground hover:text-foreground/80',
                  )}
                >
                  {kind === 'all' ? '全部' : kindLabel(kind)}
                </button>
              ))}
          <button
            type="button"
            aria-expanded={!isCollapsed}
            onClick={() => setCollapsed(!isCollapsed)}
            className="rounded-full border border-border/60 bg-card px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground/80"
          >
            {isCollapsed ? '展开' : '收起'}
          </button>
        </div>
      </div>

      {!isCollapsed && (filterKind === 'all' || filterKind === 'image') && visualKindOptions.length > 1 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {visualKindOptions.map((option) => (
            <button
              key={JSON.stringify(option.value)}
              type="button"
              aria-pressed={filterVisualKind === option.value}
              onClick={() => setSelectedVisualKind(option.value)}
              className={cn(
                'rounded-full border px-2.5 py-1 text-[11px] transition-colors',
                filterVisualKind === option.value
                  ? 'border-primary/40 bg-primary/10 text-foreground'
                  : 'border-border/60 bg-card text-muted-foreground hover:text-foreground/80',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}

      {isCollapsed ? null : (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {visibleElements.map((element) => {
            const attributes = element.attributes
            const pages = getParsingPages(element)
            const pageLabel = formatParsingPages(pages)
            const crossPageLabel = pages.length < 2 ? formatCrossPageMergePages(attributes) : null
            const visualKind = getParsingElementVisualKind(element)
            const imageSrc = getParsingElementImageSource(element)

            return (
              <button
                key={element.id}
                type="button"
                onClick={() => onSelectElement(element)}
                className="rounded-xl border border-border/60 bg-card px-3 py-2 text-left transition-colors hover:border-primary/35 hover:bg-primary/5"
              >
                {imageSrc !== null ? (
                  <div className="mb-2 overflow-hidden rounded-lg border border-border/60 bg-muted/35">
                    <AuthImage
                      src={imageSrc}
                      alt={element.text ?? element.id}
                      width={360}
                      height={240}
                      unoptimized
                      className="h-28 w-full object-contain p-1.5"
                    />
                  </div>
                ) : null}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] font-medium text-foreground">{kindLabel(element.kind)}</span>
                  {pageLabel ? <span className="font-mono text-[11px] text-muted-foreground">{pageLabel}</span> : null}
                  <span className="font-mono text-[11px] text-muted-foreground">{element.id}</span>
                  {typeof attributes?.source_content_type === 'string' ? (
                    <span className="rounded-full border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                      {attributes.source_content_type}
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
                  <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                    bbox {formatBbox(element.bbox)}
                  </div>
                ) : null}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
