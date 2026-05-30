'use client'

import { useMemo } from 'react'
import { ChevronRight } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Link, usePathname } from '@/i18n/navigation'
import { cn } from '@/lib/utils'

/* ------------------------------------------------------------------ */
/*  Route segment → human-readable label                              */
/* ------------------------------------------------------------------ */

const ROUTE_LABEL_KEYS: Record<string, string> = {
  datasets: 'datasets',
  knowledge: 'knowledge',
  settings: 'settings',
  graph: 'graph',
  evaluations: 'evaluations',
  history: 'history',
  prompts: 'prompts',
  profile: 'profile',
  ingestion: 'ingestion',
  precheck: 'precheck',
  workflow: 'workflow',
  kg: 'kg',
  tables: 'tables',
  health: 'health',
  evidence: 'evidence',
  'db-catalog': 'dbCatalog',
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
  const t = useTranslations('CommonUi')
  if (items.length === 0) return null

  return (
    <nav aria-label={t("breadcrumb.navLabel")} className={cn('flex items-center gap-1.5 text-sm', className)}>
      {items.map((item, i) => {
        const isLast = i === items.length - 1
        return (
          <span key={item.href ?? item.label} className="group flex items-center gap-1.5">
            {i > 0 && <ChevronRight className="size-3 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" />}
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
function segmentLabel(segment: string, t: ReturnType<typeof useTranslations<'CommonUi'>>): string {
  const routeKey = ROUTE_LABEL_KEYS[segment]
  return routeKey ? t(`breadcrumb.routes.${routeKey}`) : segment
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
  const t = useTranslations('CommonUi')

  return useMemo(() => {
    const segments = pathname.split('/').filter(Boolean)
    const items: BreadcrumbItem[] = []
    let href = ''

    for (const segment of segments) {
      href += `/${segment}`

      if (isDynamicSegment(segment)) continue

      items.push({ label: segmentLabel(segment, t), href })
    }

    // The last item represents the current page – drop its href.
    const lastItem = items.at(-1)
    if (lastItem) {
      items.splice(-1, 1, { label: lastItem.label })
    }

    return items
  }, [pathname, t])
}
