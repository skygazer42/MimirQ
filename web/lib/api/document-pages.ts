const CHANGED_CATALOG_MESSAGE = '文档目录在读取时发生变化，请重试同步'

export async function listDocumentPages<T extends { id: string }>(
  requestPage: (skip: number) => Promise<{ total: number; items: T[] }>,
  signal: AbortSignal,
): Promise<T[]> {
  signal.throwIfAborted()
  let page = await requestPage(0)
  signal.throwIfAborted()
  const total = page.total
  if (!Number.isSafeInteger(total) || total < 0) throw new Error('服务器返回的文档总数无效')
  const documents: T[] = []
  const seenIds = new Set<string>()
  while (true) {
    if (page.total !== total) throw new Error(CHANGED_CATALOG_MESSAGE)
    for (const document of page.items) {
      if (typeof document.id !== 'string' || document.id.length === 0) throw new Error('服务器返回的文档缺少有效标识')
      if (seenIds.has(document.id)) throw new Error(CHANGED_CATALOG_MESSAGE)
      seenIds.add(document.id)
      documents.push(document)
    }
    if (documents.length === total) return documents
    if (page.items.length === 0 || documents.length > total) throw new Error(CHANGED_CATALOG_MESSAGE)
    page = await requestPage(documents.length)
    signal.throwIfAborted()
  }
}
