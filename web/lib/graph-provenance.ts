import { toTrimmedPrimitiveString } from './primitive-text'

function escapeHtml(raw: string): string {
  return raw
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function shortId(value: string, head = 8, tail = 4): string {
  if (value.length <= head + tail + 3) return value
  return `${value.slice(0, head)}…${value.slice(-tail)}`
}

function formatConfidence(value: unknown): string {
  const confidence = typeof value === 'string' && value.trim() !== '' ? Number(value) : value
  return typeof confidence === 'number' && Number.isFinite(confidence) ? confidence.toFixed(3) : ''
}

function tooltipRow(label: string, value: string): string {
  if (value === '') return ''
  return `<div><span style="opacity:.72">${escapeHtml(label)}:</span> <span style="font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace">${escapeHtml(
    value,
  )}</span></div>`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readEndpointLabel(value: unknown): string {
  if (!isRecord(value)) return toTrimmedPrimitiveString(value)
  const label = toTrimmedPrimitiveString(value.label)
  return label === '' ? toTrimmedPrimitiveString(value.id) : label
}

export function buildGraphLinkProvenanceTooltipHtml(link: unknown): string {
  if (!isRecord(link)) return ''
  const meta = isRecord(link.meta) ? link.meta : undefined

  const kind = toTrimmedPrimitiveString(meta?.kind ?? link.kind)
  const label = toTrimmedPrimitiveString(meta?.predicate ?? link.predicate ?? link.label)
  const confidence = formatConfidence(meta?.confidence ?? link.confidence ?? link.weight)
  const source = readEndpointLabel(link.source)
  const target = readEndpointLabel(link.target)

  const docId = toTrimmedPrimitiveString(meta?.document_id)
  const chunkId = toTrimmedPrimitiveString(meta?.chunk_id)
  const eventId = toTrimmedPrimitiveString(meta?.event_id)

  const page = toTrimmedPrimitiveString(meta?.page ?? meta?.page_number)
  const chunkIndex = toTrimmedPrimitiveString(meta?.chunk_index)
  const sharedEvents = toTrimmedPrimitiveString(meta?.shared_events)
  const contentHash = toTrimmedPrimitiveString(meta?.content_hash)

  const title = (() => {
    if (kind === 'entity_relation') {
      return 'Relation (triple)'
    } else if (kind === 'event_entity') {
      return 'Evidence (event → entity)'
    } else if (kind === 'entity_entity') {
      return 'Co-occurrence (entity ↔ entity)'
    } else if (kind) {
      return `Link (${kind})`
    } else {
      return 'Link'
    }
  })()

  const bodyLines = [
    tooltipRow('label', label),
    source === '' || target === '' ? '' : tooltipRow('edge', `${shortId(source)} → ${shortId(target)}`),
    tooltipRow('confidence', confidence),
    tooltipRow('shared_events', sharedEvents),
    tooltipRow('document', shortId(docId)),
    tooltipRow('event', shortId(eventId)),
    tooltipRow('chunk', shortId(chunkId)),
    tooltipRow('chunk_index', chunkIndex),
    tooltipRow('page', page),
    tooltipRow('content_hash', shortId(contentHash, 10, 6)),
  ].join('')

  if (!bodyLines) {
    return `<div style="font-size:12px;line-height:1.2"><div style="font-weight:600;margin-bottom:4px">${escapeHtml(
      title,
    )}</div></div>`
  }

  return `<div style="font-size:12px;line-height:1.25;max-width:360px"><div style="font-weight:600;margin-bottom:4px">${escapeHtml(
    title,
  )}</div>${bodyLines}</div>`
}
