import { toTrimmedPrimitiveString } from './primitive-text'

type EndpointLike = string | number | { id?: string | number | null } | null | undefined
type LinkRecord = Record<string, unknown>
type LinkDisplayDatum = LinkRecord & {
  source?: EndpointLike
  target?: EndpointLike
  meta?: LinkRecord | null
  kind?: unknown
  predicate?: unknown
  label?: unknown
  confidence?: unknown
  __display?: GraphLinkDisplayHints
  curvature?: number
  curveRotation?: number
  parallelGroupKey?: string
  parallelIndex?: number
  parallelTotal?: number
  isSelfLoop?: boolean
}

export type GraphLinkDisplayHints = {
  curvature: number
  curveRotation: number
  parallelGroupKey: string
  parallelIndex: number
  parallelTotal: number
  isSelfLoop: boolean
}

function endpointId(value: EndpointLike): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (typeof value === 'object' && value && 'id' in value) {
    const id = value.id
    if (typeof id === 'string' || typeof id === 'number') return String(id)
  }
  return ''
}

function stableLinkKind(link: LinkDisplayDatum): string {
  return toTrimmedPrimitiveString(link.meta?.kind ?? link.kind)
}

function stableLinkPredicate(link: LinkDisplayDatum): string {
  // Prefer KG triple predicate if present; otherwise fall back to label.
  return toTrimmedPrimitiveString(link.meta?.predicate ?? link.predicate ?? link.label)
}

function stableLinkConfidence(link: LinkDisplayDatum): string {
  // Keep as string to avoid floating point surprises in sort keys.
  return toTrimmedPrimitiveString(link.meta?.confidence ?? link.confidence)
}

function linkSortKey(link: LinkDisplayDatum): string {
  // Keep this intentionally compact and deterministic; do not use JSON.stringify(link).
  const kind = stableLinkKind(link)
  const pred = stableLinkPredicate(link)
  const conf = stableLinkConfidence(link)
  return `${kind}::${pred}::${conf}`
}

function maxCurvatureForParallel(total: number): number {
  // Curvature is a visual hack: keep it bounded so large parallel sets don't become illegible.
  // 2 edges: ±0.25, 3: ±0.30, 6: ±0.45, 10: ±0.65 (cap at 0.9)
  return Math.min(0.9, 0.25 + 0.05 * Math.max(0, total - 2))
}

function curvatureForParallel(index: number, total: number): number {
  if (total <= 1) return 0
  const maxCurv = maxCurvatureForParallel(total)
  const step = (2 * maxCurv) / Math.max(1, total - 1)
  return -maxCurv + step * index
}

function loopRotation(index: number, total: number): number {
  if (total <= 0) return 0
  // Evenly spread rotations so multiple self-loops are visible.
  return (2 * Math.PI * index) / total
}

/**
 * Decorate links with deterministic curvature / rotation hints so ForceGraph can render:
 * - multiple edges between the same two endpoints without complete overlap
 * - self-loops as actual loops, not degenerate 0-length lines
 *
 * This mutates the provided link objects (expected to be clones).
 */
export function decorateLinksForDisplay<T extends LinkDisplayDatum>(links: T[]): T[] {
  const groups = new Map<string, Array<{ link: T; idx: number; sortKey: string; src: string; dst: string }>>()

  for (let i = 0; i < links.length; i += 1) {
    const link = links[i]
    const src = endpointId(link.source)
    const dst = endpointId(link.target)
    const isSelf = src !== '' && src === dst
    const groupKey = isSelf
      ? `self:${src}`
      : `pair:${[src, dst].sort((a, b) => a.localeCompare(b)).join('::')}`

    const entry = { link, idx: i, sortKey: linkSortKey(link), src, dst }
    const bucket = groups.get(groupKey)
    if (bucket) bucket.push(entry)
    else groups.set(groupKey, [entry])
  }

  for (const [groupKey, entries] of groups.entries()) {
    const total = entries.length
    // Stable ordering: semantic-ish key first, then original index (so we don't oscillate between renders).
    entries.sort((a, b) => a.sortKey.localeCompare(b.sortKey) || a.idx - b.idx)

    const isSelfLoopGroup = groupKey.startsWith('self:')
    for (let i = 0; i < entries.length; i += 1) {
      const { link } = entries[i]
      const hints: GraphLinkDisplayHints = {
        curvature: isSelfLoopGroup ? 0.6 : curvatureForParallel(i, total),
        curveRotation: isSelfLoopGroup ? loopRotation(i, total) : 0,
        parallelGroupKey: groupKey,
        parallelIndex: i,
        parallelTotal: total,
        isSelfLoop: isSelfLoopGroup,
      }

      link.__display = hints
      // Also assign direct fields to keep accessors simple and avoid deep optional chaining per-frame.
      link.curvature = hints.curvature
      link.curveRotation = hints.curveRotation
      link.isSelfLoop = hints.isSelfLoop
      link.parallelGroupKey = hints.parallelGroupKey
      link.parallelIndex = hints.parallelIndex
      link.parallelTotal = hints.parallelTotal
    }
  }

  return links
}
