export type FolderTreeNodeLike = Readonly<{
  id: string
  parentId?: string | null
}>

export type FolderTreeIndex<T extends FolderTreeNodeLike> = Readonly<{
  byId: Map<string, T>
  childrenByParentId: Map<string, T[]>
  descendantIdsByFolderId: Map<string, string[]>
}>

const folderTreeIndexCache = new WeakMap<readonly FolderTreeNodeLike[], FolderTreeIndex<FolderTreeNodeLike>>()

export function getFolderTreeIndex<T extends FolderTreeNodeLike>(folders: readonly T[]): FolderTreeIndex<T> {
  const cached = folderTreeIndexCache.get(folders) as FolderTreeIndex<T> | undefined
  if (cached) return cached

  const byId = new Map<string, T>()
  const childrenByParentId = new Map<string, T[]>()

  for (const folder of folders) {
    byId.set(folder.id, folder)

    const parentId = typeof folder.parentId === 'string' ? folder.parentId : ''
    const children = childrenByParentId.get(parentId)
    if (children) {
      children.push(folder)
    } else {
      childrenByParentId.set(parentId, [folder])
    }
  }

  const index: FolderTreeIndex<T> = {
    byId,
    childrenByParentId,
    descendantIdsByFolderId: new Map<string, string[]>(),
  }

  folderTreeIndexCache.set(folders, index)
  return index
}

export function collectFolderDescendantIds<T extends FolderTreeNodeLike>(folders: readonly T[], folderId: string): string[] {
  const index = getFolderTreeIndex(folders)
  const cached = index.descendantIdsByFolderId.get(folderId)
  if (cached) return cached

  const out: string[] = []
  const stack = [...((index.childrenByParentId.get(folderId) || []).slice().reverse())]

  while (stack.length > 0) {
    const node = stack.pop()
    if (!node) continue

    out.push(node.id)

    const children = index.childrenByParentId.get(node.id) || []
    for (let i = children.length - 1; i >= 0; i -= 1) {
      stack.push(children[i])
    }
  }

  index.descendantIdsByFolderId.set(folderId, out)
  return out
}
