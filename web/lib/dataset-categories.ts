import type { DatasetCategoryNode } from '@/types'

export function flattenDatasetCategoryTree(items: DatasetCategoryNode[]) {
  const out: Array<{ id: string; name: string; depth: number }> = []

  const walk = (node: DatasetCategoryNode) => {
    out.push({ id: node.id, name: node.name, depth: Number(node.depth || 0) })
    for (const child of node.children || []) {
      walk(child)
    }
  }

  for (const n of items || []) {
    walk(n)
  }

  return out
}

