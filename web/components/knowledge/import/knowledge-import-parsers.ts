export function parseHttpUrls(raw: string, limit: number): string[] {
  const urls: string[] = []
  const seen = new Set<string>()

  for (const part of raw.split(/[\n,;]+/g)) {
    const url = part.trim()
    if (!/^https?:\/\//i.test(url) || seen.has(url)) continue
    try {
      new URL(url)
    } catch {
      continue
    }
    seen.add(url)
    urls.push(url)
    if (urls.length >= limit) break
  }

  return urls
}

export function parseAccessMembers(raw: string): string[] {
  const memberIds = new Set<string>()
  for (const part of raw.split(/[\n,;]+/g)) {
    const memberId = part.trim()
    if (memberId.length === 0) continue
    memberIds.add(memberId)
    if (memberIds.size === 200) break
  }

  return Array.from(memberIds)
}
