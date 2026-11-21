import { toTrimmedPrimitiveString } from './primitive-text'

type EndpointLike = string | number | { id?: string | number | null } | null | undefined
type LinkRecord = Record<string, unknown>
type LinkDisplayDatum = Partial<GraphLinkDisplayHints> & {
  source?: EndpointLike
  target?: EndpointLike
  meta?: LinkRecord | null
  kind?: unknown
  predicate?: unknown
  label?: unknown
  confidence?: unknown
}

type GraphLinkDisplayHints = {
  curvature: number
  curveRotation: number
  parallelGroupKey: string
  parallelIndex: number
  parallelTotal: number
  isSelfLoop: boolean
}

function endpointId(value: EndpointLike): string {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  const id = value?.id
  return typeof id === 'string' || typeof id === 'number' ? String(id) : ''
}

function linkSortKey(link: LinkDisplayDatum): string {
  // Keep this intentionally compact and deterministic; do not use JSON.stringify(link).
  const kind = toTrimmedPrimitiveString(link.meta?.kind ?? link.kind)
  const pred = toTrimmedPrimitiveString(link.meta?.predicate ?? link.predicate ?? link.label)
  const conf = toTrimmedPrimitiveString(link.meta?.confidence ?? link.confidence)
  return `${kind}::${pred}::${conf}`
}

function curvatureForParallel(index: number, total: number): number {
  if (total <= 1) return 0
  const maxCurvature = Math.min(0.9, 0.25 + 0.05 * (total - 2))
  const step = (2 * maxCurvature) / (total - 1)
  return -maxCurvature + step * index
}

/**
 * Decorate links with deterministic curvature / rotation hints so ForceGraph can render:
 * - multiple edges between the same two endpoints without complete overlap
 * - self-loops as actual loops, not degenerate 0-length lines
 *
 * This mutates the provided link objects (expected to be clones).
 */
export function decorateLinksForDisplay(links: LinkDisplayDatum[]): void {
  const groups = new Map<string, Array<{ link: LinkDisplayDatum; index: number; sortKey: string }>>()

  for (const [index, link] of links.entries()) {
    const sourceId = endpointId(link.source)
    const targetId = endpointId(link.target)
    const isSelf = sourceId !== '' && sourceId === targetId
    const groupKey = isSelf
      ? `self:${sourceId}`
      : `pair:${[sourceId, targetId].sort((a, b) => a.localeCompare(b)).join('::')}`

    const entry = { link, index, sortKey: linkSortKey(link) }
    const bucket = groups.get(groupKey)
    if (bucket) bucket.push(entry)
    else groups.set(groupKey, [entry])
  }

  for (const [groupKey, entries] of groups.entries()) {
    const total = entries.length
    // Stable ordering: semantic-ish key first, then original index (so we don't oscillate between renders).
    entries.sort((a, b) => a.sortKey.localeCompare(b.sortKey) || a.index - b.index)

    const isSelfLoopGroup = groupKey.startsWith('self:')
    for (let i = 0; i < entries.length; i += 1) {
      const { link } = entries[i]
      const hints: GraphLinkDisplayHints = {
        curvature: isSelfLoopGroup ? 0.6 : curvatureForParallel(i, total),
        curveRotation: isSelfLoopGroup ? (2 * Math.PI * i) / total : 0,
        parallelGroupKey: groupKey,
        parallelIndex: i,
        parallelTotal: total,
        isSelfLoop: isSelfLoopGroup,
      }

      Object.assign(link, hints)
    }
  }
}
