import * as React from 'react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { normalizeTags } from '@/lib/document-user-tags'

export function DocumentTags({
  tags,
  max = 4,
  className,
  dense = false,
}: {
  tags: unknown
  max?: number
  className?: string
  dense?: boolean
}) {
  const normalized = React.useMemo(() => normalizeTags(tags), [tags])
  const cap = Math.max(0, Math.min(50, Number(max || 0)))
  if (!normalized.length) return null

  const visible = cap ? normalized.slice(0, cap) : normalized
  const hidden = cap ? Math.max(0, normalized.length - visible.length) : 0

  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)}>
      {visible.map((t) => (
        <Badge key={t} variant="soft" className={cn('max-w-[12rem] truncate', dense ? 'px-2 py-0 text-[11px]' : null)}>
          {t}
        </Badge>
      ))}
      {hidden ? (
        <Badge variant="outline" className={cn(dense ? 'px-2 py-0 text-[11px]' : null)}>
          +{hidden}
        </Badge>
      ) : null}
    </div>
  )
}

