import type { Document } from '@/types'

export type TagOpMode = 'replace' | 'append' | 'remove'

const DEFAULT_MAX_TAGS = 30
const DEFAULT_MAX_TAG_LEN = 64

function stableKey(tag: string): string {
  return tag.trim().toLowerCase()
}

export function normalizeTag(
  raw: unknown,
  opts: { maxLen?: number } = {}
): string | null {
  if (typeof raw !== 'string') return null
  const maxLen = Math.max(1, Math.min(256, Number(opts.maxLen ?? DEFAULT_MAX_TAG_LEN)))

  let s = raw.trim()
  if (!s) return null
  if (s.startsWith('#')) s = s.slice(1).trim()
  // Avoid odd whitespace that breaks pill layout while keeping spaces meaningful.
  s = s.replaceAll(/\s+/g, ' ')

  if (!s) return null
  if (s.length > maxLen) return null
  return s
}

export function normalizeTags(
  raw: unknown,
  opts: { maxTags?: number; maxLen?: number } = {}
): string[] {
  const maxTags = Math.max(0, Math.min(200, Number(opts.maxTags ?? DEFAULT_MAX_TAGS)))
  const out: string[] = []
  const seen = new Set<string>()

  const items = Array.isArray(raw) ? raw : []
  for (const item of items) {
    const tag = normalizeTag(item, { maxLen: opts.maxLen })
    if (!tag) continue
    const key = stableKey(tag)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(tag)
    if (maxTags && out.length >= maxTags) break
  }

  return out
}

export function parseTagsText(
  text: string,
  opts: { maxTags?: number; maxLen?: number } = {}
): string[] {
  const maxTags = Math.max(0, Math.min(200, Number(opts.maxTags ?? DEFAULT_MAX_TAGS)))
  const out: string[] = []
  const seen = new Set<string>()

  const parts = String(text || '')
    .split(/[\n,;，；、]+/g)
    .map((s) => s.trim())
    .filter(Boolean)

  for (const part of parts) {
    const tag = normalizeTag(part, { maxLen: opts.maxLen })
    if (!tag) continue
    const key = stableKey(tag)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(tag)
    if (maxTags && out.length >= maxTags) break
  }

  return out
}

export function mergeTags(current: unknown, mode: TagOpMode, tags: string[]): string[] {
  const base = normalizeTags(current)
  const next = normalizeTags(tags)

  if (mode === 'replace') return next

  if (mode === 'append') {
    const out = [...base]
    const seen = new Set(out.map(stableKey))
    for (const t of next) {
      const k = stableKey(t)
      if (seen.has(k)) continue
      seen.add(k)
      out.push(t)
    }
    return out.slice(0, DEFAULT_MAX_TAGS)
  }

  // remove
  const removeSet = new Set(next.map(stableKey))
  return base.filter((t) => !removeSet.has(stableKey(t)))
}

export function getUserTagsFromDocument(doc: Pick<Document, 'metadata'>): string[] {
  const meta = doc?.metadata
  if (!meta || typeof meta !== 'object') return []
  const user = (meta as Record<string, unknown>).user
  if (!user || typeof user !== 'object') return []
  return normalizeTags((user as Record<string, unknown>).tags)
}

export function buildTagsPatch(nextTags: string[]): { patch: { tags: string[] | null }; replace: false } {
  const tags = normalizeTags(nextTags)
  return {
    replace: false,
    patch: {
      // Use `null` to delete the key in merge mode (backend semantics).
      tags: tags.length ? tags : null,
    },
  }
}
