type JsonRecord = Record<string, unknown>

export type DiagnosticDecision = 'disabled' | 'marked'

export interface SimilarityDiagnosticsNode {
  id: string
  axis: 'x' | 'y'
  label: string
  color: string
  x: number
  y: number
  z: number
  averageSimilarity: number
  peakSimilarity: number
  supportCount: number
  isOutlier: boolean
  isMarked: boolean
  isDisabled: boolean
}

export interface SimilarityDiagnosticsLink {
  id: string
  source: string
  target: string
  sourceLabel: string
  targetLabel: string
  similarity: number
  lexicalOverlap: number
  isOutlier: boolean
  isMarked: boolean
}

export interface SimilarityDiagnosticsOutlier {
  id: string
  xId: string
  yId: string
  xLabel: string
  yLabel: string
  similarity: number
  lexicalOverlap: number
  score: number
  reason: string
  decision: DiagnosticDecision | null
}

export interface SimilarityDiagnosticsSummary {
  nodeCount: number
  totalNodes: number
  linkCount: number
  totalLinks: number
  candidateCount: number
  activeOutlierCount: number
  markedCount: number
  disabledCount: number
}

export interface SimilarityDiagnosticsResult {
  nodes: SimilarityDiagnosticsNode[]
  links: SimilarityDiagnosticsLink[]
  outliers: SimilarityDiagnosticsOutlier[]
  summary: SimilarityDiagnosticsSummary
}

export type SimilarityDiagnosticNode = SimilarityDiagnosticsNode
export type SimilarityDiagnosticLink = SimilarityDiagnosticsLink
export type SimilarityDiagnosticOutlier = SimilarityDiagnosticsOutlier
export type SimilarityDiagnosticsModel = SimilarityDiagnosticsResult

interface BuildSimilarityDiagnosticsInput {
  matrix: Array<Array<number | null>>
  xItems: JsonRecord[]
  yItems: JsonRecord[]
  xLabels: string[]
  yLabels: string[]
  decisions?: Record<string, DiagnosticDecision>
  linkTopK?: number
  minLinkSimilarity?: number
  outlierMinSimilarity?: number
}

type AxisStats = {
  average: number
  peak: number
  supportCount: number
  topIndex: number
  topGap: number
}

const DEFAULT_LINK_TOP_K = 2
const DEFAULT_MIN_LINK_SIMILARITY = 0.45
const DEFAULT_OUTLIER_SIMILARITY = 0.82
const SUPPORT_THRESHOLD = 0.72

function toFiniteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function sanitizeId(raw: unknown, fallback: string): string {
  const value = typeof raw === 'string' || typeof raw === 'number' ? String(raw).trim() : ''
  return value || fallback
}

function axisStats(values: Array<number | null>): AxisStats {
  const finite = values.map(toFiniteNumber).filter((value): value is number => value !== null)
  if (finite.length === 0) {
    return {
      average: 0,
      peak: 0,
      supportCount: 0,
      topIndex: 0,
      topGap: 0,
    }
  }

  const ranked = values
    .map((value, index) => ({ index, value: toFiniteNumber(value) }))
    .filter((entry): entry is { index: number; value: number } => entry.value !== null)
    .sort((left, right) => right.value - left.value)

  return {
    average: finite.reduce((sum, value) => sum + value, 0) / finite.length,
    peak: ranked[0]?.value ?? 0,
    supportCount: finite.filter((value) => value >= SUPPORT_THRESHOLD).length,
    topIndex: ranked[0]?.index ?? 0,
    topGap: (ranked[0]?.value ?? 0) - (ranked[1]?.value ?? 0),
  }
}

function columnAt(matrix: Array<Array<number | null>>, columnIndex: number, rowCount: number): Array<number | null> {
  return Array.from({ length: rowCount }, (_, rowIndex) => matrix[rowIndex]?.[columnIndex] ?? null)
}

function extractComparableText(item: JsonRecord): string {
  const fragments: string[] = []
  const append = (value: unknown) => {
    if (typeof value === 'string' && value.trim()) {
      fragments.push(value.trim())
      return
    }
    if (Array.isArray(value)) {
      for (const entry of value) append(entry)
    }
  }

  append(item.text)
  append(item.document)
  append(item.name)
  append(item.title)
  append(item.expected_answer)
  append(item.tags)

  return fragments.join(' ')
}

function tokenize(text: string): Set<string> {
  const tokens = new Set<string>()
  const parts = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []
  for (const part of parts) {
    if (!part) continue
    tokens.add(part)
    if (/[\u3400-\u9fff]/u.test(part) && part.length > 1) {
      for (let index = 0; index < part.length - 1; index += 1) {
        tokens.add(part.slice(index, index + 2))
      }
    }
  }
  return tokens
}

function lexicalOverlap(left: JsonRecord, right: JsonRecord): number {
  const leftTokens = tokenize(extractComparableText(left))
  const rightTokens = tokenize(extractComparableText(right))
  if (leftTokens.size === 0 || rightTokens.size === 0) return 0

  let shared = 0
  for (const token of leftTokens) {
    if (rightTokens.has(token)) shared += 1
  }

  const union = new Set([...leftTokens, ...rightTokens]).size
  return union > 0 ? shared / union : 0
}

function pickTopNeighbors(values: Array<number | null>, topK: number, minSimilarity: number) {
  const ranked = values
    .map((value, index) => ({ index, value: toFiniteNumber(value) }))
    .filter((entry): entry is { index: number; value: number } => entry.value !== null)
    .sort((left, right) => right.value - left.value)

  const selected = ranked.filter((entry) => entry.value >= minSimilarity).slice(0, topK)
  if (selected.length > 0) return selected
  return ranked.slice(0, Math.min(1, topK))
}

function buildReason(lexicalScore: number, xSupport: number, ySupport: number, topGap: number): string {
  const reasons: string[] = []
  reasons.push(lexicalScore < 0.08 ? '词面重叠偏低' : '词面支撑偏弱')
  if (xSupport <= 1 || ySupport <= 1) reasons.push('邻域支持不足')
  if (topGap >= 0.35) reasons.push('单点得分异常尖锐')
  return reasons.join('，')
}

function outlierScore(similarity: number, lexicalScore: number, xSupport: number, ySupport: number, topGap: number) {
  const overlapPenalty = 1 - lexicalScore
  const supportPenalty = 1 / (1 + Math.max(xSupport + ySupport - 2, 0) * 0.35)
  return similarity * overlapPenalty * (1 + topGap) * supportPenalty
}

export function buildSimilarityDiagnostics({
  matrix,
  xItems,
  yItems,
  xLabels,
  yLabels,
  decisions = {},
  linkTopK = DEFAULT_LINK_TOP_K,
  minLinkSimilarity = DEFAULT_MIN_LINK_SIMILARITY,
  outlierMinSimilarity = DEFAULT_OUTLIER_SIMILARITY,
}: BuildSimilarityDiagnosticsInput): SimilarityDiagnosticsResult {
  const safeRowCount = Math.min(matrix.length, yItems.length, yLabels.length)
  const safeColCount = safeRowCount > 0 ? Math.min(matrix[0]?.length || 0, xItems.length, xLabels.length) : 0

  const yStats = Array.from({ length: safeRowCount }, (_, rowIndex) => axisStats((matrix[rowIndex] ?? []).slice(0, safeColCount)))
  const xStats = Array.from({ length: safeColCount }, (_, columnIndex) => axisStats(columnAt(matrix, columnIndex, safeRowCount)))

  const outliers: SimilarityDiagnosticsOutlier[] = []
  const activeOutlierNodeIds = new Set<string>()
  const markedNodeIds = new Set<string>()
  const disabledNodeIds = new Set<string>()

  for (let rowIndex = 0; rowIndex < safeRowCount; rowIndex += 1) {
    for (let columnIndex = 0; columnIndex < safeColCount; columnIndex += 1) {
      const similarity = toFiniteNumber(matrix[rowIndex]?.[columnIndex])
      if (similarity === null || similarity < outlierMinSimilarity) continue

      const xItem = xItems[columnIndex] ?? {}
      const yItem = yItems[rowIndex] ?? {}
      const lexicalScore = lexicalOverlap(xItem, yItem)
      if (lexicalScore > 0.18) continue

      const xAxis = xStats[columnIndex]
      const yAxis = yStats[rowIndex]
      if (xAxis.supportCount > 2 && yAxis.supportCount > 2) continue

      const xRawId = sanitizeId(xItem.id, `x-${columnIndex + 1}`)
      const yRawId = sanitizeId(yItem.id, `y-${rowIndex + 1}`)
      const candidateId = `${xRawId}::${yRawId}`
      const decision = decisions[candidateId] ?? null

      outliers.push({
        id: candidateId,
        xId: xRawId,
        yId: yRawId,
        xLabel: xLabels[columnIndex] || `X ${columnIndex + 1}`,
        yLabel: yLabels[rowIndex] || `Y ${rowIndex + 1}`,
        similarity,
        lexicalOverlap: lexicalScore,
        score: outlierScore(similarity, lexicalScore, xAxis.supportCount, yAxis.supportCount, Math.max(xAxis.topGap, yAxis.topGap)),
        reason: buildReason(lexicalScore, xAxis.supportCount, yAxis.supportCount, Math.max(xAxis.topGap, yAxis.topGap)),
        decision,
      })

      const xNodeId = `x:${xRawId}`
      const yNodeId = `y:${yRawId}`

      if (decision === 'disabled') {
        disabledNodeIds.add(xNodeId)
        disabledNodeIds.add(yNodeId)
        continue
      }

      activeOutlierNodeIds.add(xNodeId)
      activeOutlierNodeIds.add(yNodeId)

      if (decision === 'marked') {
        markedNodeIds.add(xNodeId)
        markedNodeIds.add(yNodeId)
      }
    }
  }

  outliers.sort((left, right) => right.score - left.score)

  const linksById = new Map<string, SimilarityDiagnosticsLink>()

  const addLink = (rowIndex: number, columnIndex: number) => {
    const similarity = toFiniteNumber(matrix[rowIndex]?.[columnIndex])
    if (similarity === null) return

    const xItem = xItems[columnIndex] ?? {}
    const yItem = yItems[rowIndex] ?? {}
    const xRawId = sanitizeId(xItem.id, `x-${columnIndex + 1}`)
    const yRawId = sanitizeId(yItem.id, `y-${rowIndex + 1}`)
    const linkId = `${xRawId}::${yRawId}`
    const decision = decisions[linkId] ?? null
    if (decision === 'disabled') return

    linksById.set(linkId, {
      id: linkId,
      source: `x:${xRawId}`,
      target: `y:${yRawId}`,
      sourceLabel: xLabels[columnIndex] || `X ${columnIndex + 1}`,
      targetLabel: yLabels[rowIndex] || `Y ${rowIndex + 1}`,
      similarity,
      lexicalOverlap: lexicalOverlap(xItem, yItem),
      isOutlier: outliers.some((candidate) => candidate.id === linkId && candidate.decision !== 'disabled'),
      isMarked: decision === 'marked',
    })
  }

  for (let rowIndex = 0; rowIndex < safeRowCount; rowIndex += 1) {
    for (const neighbor of pickTopNeighbors((matrix[rowIndex] ?? []).slice(0, safeColCount), linkTopK, minLinkSimilarity)) {
      addLink(rowIndex, neighbor.index)
    }
  }

  for (let columnIndex = 0; columnIndex < safeColCount; columnIndex += 1) {
    for (const neighbor of pickTopNeighbors(columnAt(matrix, columnIndex, safeRowCount), linkTopK, minLinkSimilarity)) {
      addLink(neighbor.index, columnIndex)
    }
  }

  const nodes: SimilarityDiagnosticsNode[] = [
    ...xItems.slice(0, safeColCount).map((item, index) => {
      const rawId = sanitizeId(item.id, `x-${index + 1}`)
      const nodeId = `x:${rawId}`
      const stats = xStats[index] ?? axisStats([])
      const axisPosition = safeRowCount > 1 ? stats.topIndex / (safeRowCount - 1) - 0.5 : 0
      const isDisabled = disabledNodeIds.has(nodeId) && !activeOutlierNodeIds.has(nodeId)
      const isMarked = markedNodeIds.has(nodeId)
      const isOutlier = activeOutlierNodeIds.has(nodeId)
      return {
        id: nodeId,
        axis: 'x' as const,
        label: xLabels[index] || `X ${index + 1}`,
        x: -56 + stats.average * 30,
        y: axisPosition * 120,
        z: (stats.peak - stats.average) * 180 - 32,
        averageSimilarity: stats.average,
        peakSimilarity: stats.peak,
        supportCount: stats.supportCount,
        isOutlier,
        isMarked,
        isDisabled,
        color: isDisabled ? '#94a3b8' : isMarked ? '#f59e0b' : isOutlier ? '#f97316' : '#38bdf8',
      }
    }),
    ...yItems.slice(0, safeRowCount).map((item, index) => {
      const rawId = sanitizeId(item.id, `y-${index + 1}`)
      const nodeId = `y:${rawId}`
      const stats = yStats[index] ?? axisStats([])
      const axisPosition = safeColCount > 1 ? stats.topIndex / (safeColCount - 1) - 0.5 : 0
      const isDisabled = disabledNodeIds.has(nodeId) && !activeOutlierNodeIds.has(nodeId)
      const isMarked = markedNodeIds.has(nodeId)
      const isOutlier = activeOutlierNodeIds.has(nodeId)
      return {
        id: nodeId,
        axis: 'y' as const,
        label: yLabels[index] || `Y ${index + 1}`,
        x: 56 - stats.average * 30,
        y: axisPosition * 120,
        z: (stats.peak - stats.average) * 180 + 32,
        averageSimilarity: stats.average,
        peakSimilarity: stats.peak,
        supportCount: stats.supportCount,
        isOutlier,
        isMarked,
        isDisabled,
        color: isDisabled ? '#94a3b8' : isMarked ? '#f59e0b' : isOutlier ? '#f97316' : '#34d399',
      }
    }),
  ]

  const links = Array.from(linksById.values()).sort((left, right) => right.similarity - left.similarity)

  return {
    nodes,
    links,
    outliers,
    summary: {
      nodeCount: nodes.length,
      totalNodes: nodes.length,
      linkCount: links.length,
      totalLinks: links.length,
      candidateCount: outliers.length,
      activeOutlierCount: outliers.filter((candidate) => candidate.decision !== 'disabled').length,
      markedCount: outliers.filter((candidate) => candidate.decision === 'marked').length,
      disabledCount: outliers.filter((candidate) => candidate.decision === 'disabled').length,
    },
  }
}
