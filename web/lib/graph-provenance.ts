import { toTrimmedPrimitiveString } from './primitive-text'

function escapeHtml(raw: string): string {
  return String(raw)
    .replaceAll("&", '&amp;')
    .replaceAll("<", '&lt;')
    .replaceAll(">", '&gt;')
    .replaceAll("\"", '&quot;')
    .replaceAll("'", '&#39;')
}

function coerceTrimmedString(value: unknown): string {
  return toTrimmedPrimitiveString(value)
}

function shortId(value: unknown, opts?: { head?: number; tail?: number }): string {
  const head = Math.max(0, opts?.head ?? 8)
  const tail = Math.max(0, opts?.tail ?? 4)
  const s = coerceTrimmedString(value)
  if (!s) return ''
  if (s.length <= head + tail + 3) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}

function formatConfidence(value: unknown): string {
  if (value == null) return ''
  const n = Number(value)
  if (!Number.isFinite(n)) return ''
  // Keep compact but stable, since this appears in hover tooltips.
  return n.toFixed(3)
}

function line(label: string, value: string): string {
  if (!value) return ''
  return `<div><span style="opacity:.72">${escapeHtml(label)}:</span> <span style="font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace">${escapeHtml(
    value
  )}</span></div>`
}

function inferSourceTarget(link: any): { source: string; target: string } {
  const rawSource = link?.source
  const rawTarget = link?.target

  const source = typeof rawSource === 'object' && rawSource !== null ? rawSource.label || rawSource.id : rawSource
  const target = typeof rawTarget === 'object' && rawTarget !== null ? rawTarget.label || rawTarget.id : rawTarget

  return { source: coerceTrimmedString(source), target: coerceTrimmedString(target) }
}

export function buildGraphLinkProvenanceTooltipHtml(link: any): string {
  if (!link) return ''

  const kind = coerceTrimmedString(link?.meta?.kind ?? link?.kind)
  const label = coerceTrimmedString(link?.meta?.predicate ?? link?.predicate ?? link?.label)
  const conf = formatConfidence(link?.meta?.confidence ?? link?.confidence ?? link?.weight)
  const { source, target } = inferSourceTarget(link)

  const docId = coerceTrimmedString(link?.meta?.document_id)
  const chunkId = coerceTrimmedString(link?.meta?.chunk_id)
  const eventId = coerceTrimmedString(link?.meta?.event_id)

  const page = coerceTrimmedString(link?.meta?.page ?? link?.meta?.page_number)
  const chunkIndex = coerceTrimmedString(link?.meta?.chunk_index)
  const sharedEvents = coerceTrimmedString(link?.meta?.shared_events)
  const contentHash = coerceTrimmedString(link?.meta?.content_hash)

  const title =
    (() => {
    if (kind === 'entity_relation') {
        return 'Relation (triple)';
    }
    else if (kind === 'event_entity') {
            return 'Evidence (event → entity)';
        }
        else if (kind === 'entity_entity') {
                return 'Co-occurrence (entity ↔ entity)';
            }
            else if (kind) {
                    return `Link (${kind})`;
                }
                else {
                    return 'Link';
                }
})()

  const bodyLines = [
    label ? line('label', label) : '',
    source && target ? line('edge', `${shortId(source)} → ${shortId(target)}`) : '',
    conf ? line('confidence', conf) : '',
    sharedEvents ? line('shared_events', sharedEvents) : '',
    docId ? line('document', shortId(docId)) : '',
    eventId ? line('event', shortId(eventId)) : '',
    chunkId ? line('chunk', shortId(chunkId)) : '',
    chunkIndex ? line('chunk_index', chunkIndex) : '',
    page ? line('page', page) : '',
    contentHash ? line('content_hash', shortId(contentHash, { head: 10, tail: 6 })) : '',
  ]
    .filter(Boolean)
    .join('')

  if (!bodyLines) {
    return `<div style="font-size:12px;line-height:1.2"><div style="font-weight:600;margin-bottom:4px">${escapeHtml(
      title
    )}</div></div>`
  }

  return `<div style="font-size:12px;line-height:1.25;max-width:360px"><div style="font-weight:600;margin-bottom:4px">${escapeHtml(
    title
  )}</div>${bodyLines}</div>`
}
