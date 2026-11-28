import type { ChunkOverrides } from '@/components/chunk-preview/types'
import {
  findChunkParent,
  getChunkParentIdentity,
  getChunkRole,
  getParentIdentities,
  type ChunkIdentity,
} from '@/components/chunk-preview/utils/metadata'
import { getChunkSectionPath } from '@/components/chunk-preview/utils/sections'
import type { ChunkPreviewItem, ChunkPreviewResponse, ChunkPreviewReviewSignals } from '@/types'

export const SECTION_ALL_VALUE = '__mimirq_section_all__'
export const SECTION_NONE_VALUE = '__mimirq_section_none__'

export type ChunkListEntry = { chunk: ChunkPreviewItem; position: number }

type ChunkRowBase = { key: string; chunk: ChunkPreviewItem; position: number }
type ChunkItemRow = ChunkRowBase & { kind: 'chunk'; indent: 0 | 1; groupKey?: string }
type ChunkParentRow = ChunkRowBase & {
  kind: 'parent'
  indent: 0
  groupKey: string
  childCountTotal: number
  childCountVisible: number
  isContext: boolean
  collapsed: boolean
  forceExpanded: boolean
}
type ChunkListRow = ChunkItemRow | ChunkParentRow | { kind: 'section'; key: string; label: string; count: number }

type LengthBounds =
  | { valid: true; minimum: number | undefined; maximum: number | undefined }
  | { valid: false; minimumInvalid: boolean; maximumInvalid: boolean }

export function parseLengthBounds(minimum: string, maximum: string): LengthBounds {
  const minimumValue = minimum.trim() === '' ? undefined : Number(minimum)
  const maximumValue = maximum.trim() === '' ? undefined : Number(maximum)
  const minimumInvalid = minimumValue !== undefined && (!Number.isSafeInteger(minimumValue) || minimumValue < 0)
  const maximumInvalid = maximumValue !== undefined && (!Number.isSafeInteger(maximumValue) || maximumValue < 0)
  if (minimumInvalid || maximumInvalid) {
    return { valid: false, minimumInvalid, maximumInvalid }
  }
  if (minimumValue !== undefined && maximumValue !== undefined && minimumValue > maximumValue) {
    return { valid: false, minimumInvalid: true, maximumInvalid: true }
  }
  return { valid: true, minimum: minimumValue, maximum: maximumValue }
}

export function getSectionFilterValue(section: string | null): string {
  return section === null ? SECTION_NONE_VALUE : `section:${section}`
}

/** 正文影响短块/重复标记；只有 parent_child 的角色变化影响子块覆盖标记。 */
export function getApplicableReviewSignals(
  preview: ChunkPreviewResponse | null,
  overrides: ChunkOverrides,
): ChunkPreviewReviewSignals | undefined {
  const signals = preview?.review_signals
  if (preview === null || signals === null || signals === undefined) return undefined
  const bodyChanged = preview.chunks.some((chunk) => {
    const content = overrides[chunk.index]?.content
    return content !== undefined && content !== chunk.content
  })
  const coverageChanged =
    preview.chunk_strategy === 'parent_child' &&
    preview.chunks.some((chunk) => {
      const metadata = overrides[chunk.index]?.metadata
      return metadata !== undefined && metadata.chunk_role !== chunk.metadata?.chunk_role
    })
  if (!bodyChanged && !coverageChanged) return signals
  return {
    ...signals,
    short_indices: bodyChanged ? undefined : signals.short_indices,
    duplicate_indices: bodyChanged ? undefined : signals.duplicate_indices,
    basis: coverageChanged ? undefined : signals.basis,
    gap_indices: coverageChanged ? undefined : signals.gap_indices,
    overlap_indices: coverageChanged ? undefined : signals.overlap_indices,
    gap_before_by_index: coverageChanged ? undefined : signals.gap_before_by_index,
    overlap_prev_by_index: coverageChanged ? undefined : signals.overlap_prev_by_index,
  }
}

function createChunkRow({ chunk, position }: ChunkListEntry, indent: 0 | 1): ChunkItemRow {
  return { kind: 'chunk', key: `chunk:${chunk.index}`, chunk, position, indent }
}

function buildSectionRows(
  entries: readonly ChunkListEntry[],
  collapsedGroups: ReadonlySet<string>,
  noSectionLabel: string,
): ChunkListRow[] {
  const groups = new Map<string | null, ChunkListEntry[]>()
  for (const entry of entries) {
    const section = getChunkSectionPath(entry.chunk)
    let group = groups.get(section)
    if (group === undefined) {
      group = []
      groups.set(section, group)
    }
    group.push(entry)
  }
  const rows: ChunkListRow[] = []
  for (const [section, group] of groups) {
    const key = getSectionFilterValue(section)
    rows.push({ kind: 'section', key, label: section === null ? noSectionLabel : section, count: group.length })
    if (!collapsedGroups.has(key)) rows.push(...group.map((entry) => ({ ...createChunkRow(entry, 1), groupKey: key })))
  }
  return rows
}

function buildHierarchyRows(
  chunks: readonly ChunkPreviewItem[],
  filtered: readonly ChunkListEntry[],
  collapsedGroups: ReadonlySet<string>,
  forceExpand: boolean,
): ChunkListRow[] {
  const entries = chunks.map((chunk, position) => ({ chunk, position }))
  // 父块先按原样身份建索引，0 与字符串 "0" 保持不同。
  const parentsByIdentity = new Map<ChunkIdentity, ChunkPreviewItem[]>()
  for (const { chunk } of entries) {
    if (getChunkRole(chunk) !== 'parent') continue
    for (const identity of getParentIdentities(chunk)) {
      let parents = parentsByIdentity.get(identity)
      if (parents === undefined) {
        parents = []
        parentsByIdentity.set(identity, parents)
      }
      parents.push(chunk)
    }
  }
  const childrenByParent = new Map<number, ChunkListEntry[]>()
  const linkedChildren = new Set<number>()
  // 只有唯一且包含原跨度的真实父块才能承接子块。
  for (const entry of entries) {
    if (getChunkRole(entry.chunk) !== 'child') continue
    const identity = getChunkParentIdentity(entry.chunk)
    if (identity === undefined) continue
    const candidates = parentsByIdentity.get(identity)
    if (candidates === undefined) continue
    const parent = findChunkParent(entry.chunk, candidates)
    if (parent === undefined) continue
    let children = childrenByParent.get(parent.index)
    if (children === undefined) {
      children = []
      childrenByParent.set(parent.index, children)
    }
    children.push(entry)
    linkedChildren.add(entry.chunk.index)
  }
  const matched = new Set(filtered.map(({ chunk }) => chunk.index))
  const rows: ChunkListRow[] = []
  // 只改显示顺序，position 始终保留源数组位置。
  for (const entry of entries) {
    if (linkedChildren.has(entry.chunk.index)) continue
    const children = childrenByParent.get(entry.chunk.index)
    if (children === undefined) {
      if (matched.has(entry.chunk.index)) rows.push(createChunkRow(entry, 0))
      continue
    }
    const visibleChildren = children.filter(({ chunk }) => matched.has(chunk.index))
    if (!matched.has(entry.chunk.index) && visibleChildren.length === 0) continue
    const key = `parent:${entry.chunk.index}`
    const forceExpanded = forceExpand && visibleChildren.length > 0
    const collapsed = collapsedGroups.has(key) && !forceExpanded
    rows.push({
      ...createChunkRow(entry, 0),
      kind: 'parent',
      indent: 0,
      groupKey: key,
      childCountTotal: children.length,
      childCountVisible: visibleChildren.length,
      isContext: !matched.has(entry.chunk.index),
      collapsed,
      forceExpanded,
    })
    if (!collapsed) {
      rows.push(...visibleChildren.map((child) => ({ ...createChunkRow(child, 1), groupKey: key })))
    }
  }
  return rows
}

export function buildChunkListRows(
  chunks: readonly ChunkPreviewItem[],
  filtered: readonly ChunkListEntry[],
  options: {
    view: 'flat' | 'section' | 'hierarchy'
    collapsedGroups: ReadonlySet<string>
    forceExpand: boolean
    noSectionLabel: string
  },
): ChunkListRow[] {
  if (filtered.length === 0) return []
  if (options.view === 'section') return buildSectionRows(filtered, options.collapsedGroups, options.noSectionLabel)
  if (options.view === 'hierarchy')
    return buildHierarchyRows(chunks, filtered, options.collapsedGroups, options.forceExpand)
  return filtered.map((entry) => createChunkRow(entry, 0))
}
