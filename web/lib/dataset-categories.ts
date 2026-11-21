import type { DatasetCategoryNode } from '@/types/datasets'

export function flattenDatasetCategoryTree(items: readonly DatasetCategoryNode[]) {
  const categories: DatasetCategoryNode[] = []

  function visitCategory(node: DatasetCategoryNode) {
    categories.push(node)
    for (const child of node.children ?? []) {
      visitCategory(child)
    }
  }

  for (const node of items) {
    visitCategory(node)
  }

  return categories
}
