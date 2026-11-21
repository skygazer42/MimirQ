const DIRECTORY_PAGE_SIZE = 500

export function paginateDirectory<T>(items: readonly T[], page: number, size: number) {
  const total = items.length
  const pages = Math.max(1, Math.ceil(total / size))
  const current = Math.min(Math.max(page, 1), pages)
  const offset = (current - 1) * size
  const end = Math.min(current * size, total)

  return {
    items: items.slice(offset, end),
    page: current,
    pages,
    total,
    start: total === 0 ? 0 : offset + 1,
    end,
  }
}

export async function readDirectoryPages<T>(
  fetchPage: (params: { skip: number; limit: number }) => Promise<{ items?: T[]; total: number }>,
  getItemId: (item: T) => string,
  signal?: AbortSignal,
  pageSize = DIRECTORY_PAGE_SIZE,
): Promise<T[]> {
  const items: T[] = []
  const seen = new Set<string>()
  let total: number | undefined

  for (let skip = 0; ;) {
    signal?.throwIfAborted()
    const page = await fetchPage({ skip, limit: pageSize })
    signal?.throwIfAborted()
    const pageItems = page.items ?? (page.total === 0 ? [] : undefined)

    if (!Array.isArray(pageItems) || !Number.isSafeInteger(page.total) || page.total < 0) {
      throw new Error('目录响应不完整，请刷新后重试。')
    }
    if (total !== undefined && total !== page.total) {
      throw new Error('目录在读取期间发生变化，请刷新后重试。')
    }
    total = page.total
    if ((pageItems.length === 0 && items.length < total) || pageItems.length > pageSize) {
      throw new Error('目录分页不完整，请刷新后重试。')
    }

    for (const item of pageItems) {
      const id = getItemId(item)
      if (!id || seen.has(id)) throw new Error('目录分页出现重复，请刷新后重试。')
      seen.add(id)
      items.push(item)
    }
    if (items.length > total) throw new Error('目录数量不一致，请刷新后重试。')
    if (items.length === total) return items
    skip += pageItems.length
  }
}
