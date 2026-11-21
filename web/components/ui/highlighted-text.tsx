import type { ReactNode } from 'react'

import { findCaseInsensitiveTextRanges } from '@/lib/text-offsets'

type HighlightedTextProps = Readonly<{
  content: string
  query: string
  maxMatches?: number
  markClassName?: string
}>

export function HighlightedText({
  content,
  query,
  maxMatches = 50,
  markClassName = 'rounded bg-warning/15 px-0.5 text-foreground',
}: HighlightedTextProps) {
  const ranges = findCaseInsensitiveTextRanges(content, query.trim(), maxMatches)
  if (ranges.length === 0) return <>{content}</>

  const nodes: ReactNode[] = []
  let cursor = 0
  for (const { start, end } of ranges) {
    if (start > cursor) nodes.push(content.slice(cursor, start))
    nodes.push(
      <mark key={`${start}-${end}`} className={markClassName}>
        {content.slice(start, end)}
      </mark>,
    )
    cursor = end
  }
  nodes.push(content.slice(cursor))
  return <>{nodes}</>
}
