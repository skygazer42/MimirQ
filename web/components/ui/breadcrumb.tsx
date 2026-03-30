'use client'

import { useMemo } from 'react'
import { ChevronRight } from 'lucide-react'

import { Link, usePathname } from '@/i18n/navigation'
import { cn } from '@/lib/utils'

/* ------------------------------------------------------------------ */
/*  Route segment → human-readable label                              */
/* ------------------------------------------------------------------ */

const ROUTE_LABELS: Record<string, string> = {
  datasets: '数据集',
  knowledge: '知识库',
  settings: '设置',
  graph: '知识图谱',
  evaluations: '评测',
  history: '历史记录',
  prompts: '提示词',
  profile: '概览',
  ingestion: '数据导入',
  precheck: '预检查',
  workflow: '工作流',
  kg: '知识图谱',
  tables: '数据表',
  health: '健康检查',
  evidence: '溯源',
  'db-catalog': '数据目录',
}

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export type BreadcrumbItem = {
  label: string
  href?: string
}

type BreadcrumbProps = {
  items: BreadcrumbItem[]
  className?: string
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function Breadcrumb({ items, className }: Readonly<BreadcrumbProps>) {
  if (items.length === 0) return null

  return (
    <nav aria-label="Breadcrumb" className={cn('flex items-center gap-1.5 text-sm', className)}>
      {items.map((item, i) => {
        const isLast = i === items.length - 1
        return (
          <span key={item.href ?? item.label} className="flex items-center gap-1.5">
            {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" />}
            {isLast || !item.href ? (
              <span className="truncate font-medium text-foreground">{item.label}</span>
            ) : (
              <Link
                href={item.href}
                className="truncate text-muted-foreground transition-colors hover:text-foreground"
              >
                {item.label}
              </Link>
            )}
          </span>
        )
      })}
    </nav>
  )
}

/* ------------------------------------------------------------------ */
/*  Hook – auto-generate breadcrumbs from the current pathname        */
/* ------------------------------------------------------------------ */

/** Resolve a segment string to a human-readable label. */
function segmentLabel(segment: string): string {
  return ROUTE_LABELS[segment] ?? segment
}

/** Whether a segment looks like a dynamic id (UUID or similar). */
function isDynamicSegment(segment: string): boolean {
  return /^[0-9a-f-]{8,}$/i.test(segment)
}

/**
 * Derive breadcrumb items from the current Next.js pathname.
 *
 * Dynamic id segments are skipped (they don't add useful labels) while
 * static segments are mapped through `ROUTE_LABELS`.
 */
export function usePathBreadcrumbs(): BreadcrumbItem[] {
  const pathname = usePathname()

  return useMemo(() => {
    const segments = pathname.split('/').filter(Boolean)
    const items: BreadcrumbItem[] = []
    let href = ''

    for (const segment of segments) {
      href += `/${segment}`

      if (isDynamicSegment(segment)) continue

      items.push({ label: segmentLabel(segment), href })
    }

    // The last item represents the current page – drop its href.
    if (items.length > 0) {
      items[items.length - 1] = { label: items[items.length - 1].label }
    }

    return items
  }, [pathname])
}
