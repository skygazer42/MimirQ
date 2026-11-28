type FolderTreeNodeLike = Readonly<{
  id: string
  parentId?: string | null
}>

type FolderTreeIndex = Readonly<{
  childrenByParentId: Map<string, FolderTreeNodeLike[]>
  descendantIdsByFolderId: Map<string, string[]>
}>

const folderTreeIndexCache = new WeakMap<readonly FolderTreeNodeLike[], FolderTreeIndex>()

function getFolderTreeIndex(folders: readonly FolderTreeNodeLike[]): FolderTreeIndex {
  const cached = folderTreeIndexCache.get(folders)
  if (cached !== undefined) return cached

  const childrenByParentId = new Map<string, FolderTreeNodeLike[]>()
  for (const folder of folders) {
    const parentId = folder.parentId ?? ''
    const children = childrenByParentId.get(parentId)
    if (children === undefined) {
      childrenByParentId.set(parentId, [folder])
    } else {
      children.push(folder)
    }
  }

  const index: FolderTreeIndex = { childrenByParentId, descendantIdsByFolderId: new Map() }
  folderTreeIndexCache.set(folders, index)
  return index
}

export function collectFolderDescendantIds(folders: readonly FolderTreeNodeLike[], folderId: string): string[] {
  const index = getFolderTreeIndex(folders)
  const cached = index.descendantIdsByFolderId.get(folderId)
  if (cached !== undefined) return cached

  const descendantIds: string[] = []
  const visitedIds = new Set([folderId])
  const stack = index.childrenByParentId.get(folderId)?.slice().reverse() ?? []

  for (let node = stack.pop(); node !== undefined; node = stack.pop()) {
    if (visitedIds.has(node.id)) continue

    visitedIds.add(node.id)
    descendantIds.push(node.id)

    const children = index.childrenByParentId.get(node.id)
    if (children === undefined) continue
    for (let childIndex = children.length - 1; childIndex >= 0; childIndex -= 1) {
      stack.push(children[childIndex])
    }
  }

  index.descendantIdsByFolderId.set(folderId, descendantIds)
  return descendantIds
}
