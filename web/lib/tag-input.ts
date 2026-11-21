type TagInputIssue = 'limit' | 'length'

export function tagKey(tag: string): string {
  return tag.trim().toLowerCase()
}

/** maxTags=0 表示不限数量；只追加新值，不修改调用方已有标签。 */
export function appendTagText(current: readonly string[], text: string, options: { maxTags: number; maxLen: number }) {
  const tags = [...current]
  const seen = new Set(current.map(tagKey))
  const pending: string[] = []
  const issues = new Set<TagInputIssue>()
  for (const raw of text.split(/[\n,;，；、]+/g)) {
    let tag = raw.trim()
    if (tag.startsWith('#')) tag = tag.slice(1).trim()
    tag = tag.replaceAll(/\s+/g, ' ')
    if (tag.length === 0) continue
    const key = tagKey(tag)
    if (seen.has(key)) continue
    if (Array.from(tag).length > options.maxLen) {
      pending.push(raw)
      issues.add('length')
      continue
    }
    if (options.maxTags !== 0 && tags.length >= options.maxTags) {
      pending.push(raw)
      issues.add('limit')
      continue
    }
    seen.add(key)
    tags.push(tag)
  }
  return { tags, pending: pending.join(', '), issues: Array.from(issues) }
}
