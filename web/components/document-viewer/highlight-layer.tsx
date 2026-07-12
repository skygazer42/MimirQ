'use client'

import * as React from 'react'

function escapeRegExp(value: string): string {
  return value.replaceAll(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`)
}

type HighlightLayerProps = {
  content: string
  query: string
}

export function HighlightLayer({ content, query }: Readonly<HighlightLayerProps>) {
  const q = query.trim()
  if (!q) return <>{content}</>

  const re = new RegExp(escapeRegExp(q), 'ig')
  const out: React.ReactNode[] = []
  let lastIndex = 0
  let matchCount = 0

  for (const match of content.matchAll(re)) {
    const idx = match.index
    if (idx == null) continue

    const matched = match[0] || ''
    if (!matched) continue

    if (idx > lastIndex) out.push(content.slice(lastIndex, idx))
    out.push(
      <mark
        key={`${idx}-${matched}`}
        className="rounded bg-warning/15 px-0.5 text-foreground"
      >
        {content.slice(idx, idx + matched.length)}
      </mark>
    )
    lastIndex = idx + matched.length
    matchCount += 1

    if (matchCount >= 50) break
  }

  if (lastIndex < content.length) out.push(content.slice(lastIndex))
  return out.length ? <>{out}</> : <>{content}</>
}
