'use client'

import { useDeferredValue, useMemo, type Ref } from 'react'
import { ChevronDown, GitBranch, Loader2 } from '@/components/icons'
import { SearchInput } from '@/components/ui/search-input'
import { Button } from '@/components/ui/button'
import type { GraphNode } from '@/lib/graph-types'
import { searchDirectory, type DirectoryGroup } from '../graph-directory-model'
import styles from './graph-workspace.module.css'

type GraphNodeDirectoryProps = {
  groups: DirectoryGroup[]
  neighbors: Map<string, Set<string>>
  selectedId: string | null
  query: string
  inputRef: Ref<HTMLInputElement>
  loading: boolean
  hasLoadError: boolean
  onQueryChange: (value: string) => void
  onSelect: (node: GraphNode) => void
  onOpenScope: () => void
}

export function GraphNodeDirectory({
  groups,
  neighbors,
  selectedId,
  query,
  inputRef,
  loading,
  hasLoadError,
  onQueryChange,
  onSelect,
  onOpenScope,
}: Readonly<GraphNodeDirectoryProps>) {
  const deferredQuery = useDeferredValue(query)
  const hasSearch = deferredQuery.trim() !== ''
  const filtered = useMemo(() => searchDirectory(groups, deferredQuery), [deferredQuery, groups])
  const count = filtered.reduce((sum, group) => sum + group.nodes.length, 0)
  return (
    <aside className={styles.directory} aria-label="实体目录" data-graph-directory>
      <div className={styles.directoryHeader}>
        <div>
          <h2>实体目录</h2>
          <span aria-live="polite">{count}</span>
        </div>
        <SearchInput
          ref={inputRef}
          value={query}
          onValueChange={onQueryChange}
          placeholder="搜索实体名称"
          aria-label="搜索图谱实体"
          inputClassName={styles.search}
        />
      </div>
      <div className={styles.directoryScroll} aria-busy={loading}>
        {loading && groups.length === 0 ? (
          <div className={styles.directoryState}>
            <Loader2 className="animate-spin motion-reduce:animate-none" />
            <p>正在读取图谱…</p>
          </div>
        ) : groups.length === 0 && hasLoadError ? null : filtered.length === 0 ? (
          <div className={styles.directoryState}>
            <p>{hasSearch ? '没有匹配的实体' : '当前范围没有节点'}</p>
            <Button variant="ghost" onClick={hasSearch ? () => onQueryChange('') : onOpenScope}>
              {hasSearch ? '清除搜索' : '选择图谱'}
            </Button>
          </div>
        ) : (
          filtered.map((group) => (
            <details open key={group.key} className={styles.directoryGroup}>
              <summary>
                <ChevronDown />
                <span>{group.label}</span>
                <small>{group.nodes.length}</small>
              </summary>
              <ul>
                {group.nodes.map((node) => {
                  const nodeLabel = node.label === '' ? node.id : node.label
                  const neighborCount = neighbors.get(node.id)?.size ?? 0
                  return (
                    <li key={node.id}>
                      <button
                        type="button"
                        data-directory-node={node.id}
                        aria-pressed={selectedId === node.id}
                        onClick={() => onSelect(node)}
                        title={nodeLabel}
                      >
                        <i style={{ backgroundColor: group.color }} />
                        <span>{nodeLabel}</span>
                        <small aria-label={`${neighborCount} 个直接关联`}>{neighborCount}</small>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </details>
          ))
        )}
      </div>
      <div className={styles.directoryFooter}>
        <GitBranch />
        <span>名称右侧为已加载的直接关联数</span>
      </div>
    </aside>
  )
}
