import type { Document } from '@/types/documents'
import { tagKey } from '@/lib/tag-input'

export const DOCUMENT_TAG_LIMIT = 50
export const DOCUMENT_TAG_LENGTH = 64

export function getUserTagsFromDocument(doc: Pick<Document, 'metadata'>): string[] {
  const user = doc.metadata?.user
  if (
    user === null ||
    typeof user !== 'object' ||
    Array.isArray(user) ||
    !('tags' in user) ||
    !Array.isArray(user.tags)
  )
    return []

  const tags: string[] = []
  const seen = new Set<string>()
  for (const tag of user.tags) {
    if (typeof tag !== 'string') continue
    const key = tagKey(tag)
    if (key.length === 0 || seen.has(key)) continue
    seen.add(key)
    tags.push(tag)
  }
  return tags
}

export function buildTagsPatch(tags: readonly string[]): { patch: { tags: string[] | null }; replace: false } {
  if (tags.length > DOCUMENT_TAG_LIMIT) throw new Error(`文档标签最多 ${DOCUMENT_TAG_LIMIT} 个。`)
  for (const tag of tags) {
    const trimmedTag = tag.trim()
    if (trimmedTag.length === 0) throw new Error('标签不能为空。')
    if (Array.from(trimmedTag).length > DOCUMENT_TAG_LENGTH)
      throw new Error(`每个标签最多 ${DOCUMENT_TAG_LENGTH} 个字符。`)
  }

  return { replace: false, patch: { tags: tags.length === 0 ? null : [...tags] } }
}
