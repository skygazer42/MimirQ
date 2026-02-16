export type FolderNode = {
  path?: string
  documents?: number
  depth?: number
  children?: FolderNode[]
}

export type FolderTreePayload = {
  root?: FolderNode | null
}

export type FlatFolderRow = {
  path: string
  documents: number
  depth: number
}

export function flattenFolderTree(folderTree: FolderTreePayload | null | undefined): FlatFolderRow[] {
  const root = folderTree?.root
  if (!root) return []

  const children = Array.isArray(root.children) ? root.children : []
  if (!children.length) return []

  // Iterative DFS to avoid recursion limits on deep folder trees.
  const out: FlatFolderRow[] = []
  const stack: FolderNode[] = [...children]

  while (stack.length) {
    const node = stack.pop()
    if (!node) continue

    out.push({
      path: String(node.path || ''),
      documents: Number(node.documents || 0),
      depth: Number(node.depth || 0),
    })

    const next = Array.isArray(node.children) ? node.children : []
    // Preserve a roughly stable traversal order (not critical; UI sorts anyway).
    for (let i = next.length - 1; i >= 0; i -= 1) {
      stack.push(next[i] as FolderNode)
    }
  }

  return out
}

