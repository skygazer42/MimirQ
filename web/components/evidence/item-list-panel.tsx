'use client'

import { useId } from 'react'
import { Plus, RefreshCw } from '@/components/icons'

import type { EvidenceItem } from '@/types'
import { Button } from '@/components/ui/button'
import { WorkspaceNotice, WorkspaceTableScroll, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { LoadingButton } from '@/components/ui/loading-button'
import { Skeleton } from '@/components/ui/skeleton'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import styles from './evidence-workbench.module.css'

type ItemListPanelProps = {
  selectedSuiteId: string
  itemQuery: string
  onItemQueryChange: (value: string) => void
  statusFilter: string
  onStatusFilterChange: (value: string) => void
  onRefresh: () => void
  itemsLoading: boolean
  filteredItems: EvidenceItem[]
  itemsError: string | null
  selectedItemId: string
  onCreateItem: () => void
  onSelectItem: (itemId: string) => void
}

export function ItemListPanel({
  selectedSuiteId,
  itemQuery,
  onItemQueryChange,
  statusFilter,
  onStatusFilterChange,
  onRefresh,
  itemsLoading,
  filteredItems,
  itemsError,
  selectedItemId,
  onCreateItem,
  onSelectItem,
}: Readonly<ItemListPanelProps>) {
  const headingId = useId()
  const labels: Record<string, string> = { draft: '草稿', reviewed: '已复核', approved: '已通过', archived: '已归档' }
  return (
    <section data-evidence-item-list aria-labelledby={headingId}>
      <div className={`${ws.sectionHeading} max-sm:sr-only`}>
        <h2 id={headingId} className={ws.sectionTitle}>
          证据条目
        </h2>
      </div>
      <div className={styles.itemToolbar}>
        <SearchInput
          value={itemQuery}
          onValueChange={onItemQueryChange}
          placeholder="搜索问题或说明"
          containerClassName={styles.itemSearch}
        />
        <Select value={statusFilter} onValueChange={onStatusFilterChange} disabled={!selectedSuiteId}>
          <SelectTrigger className={styles.itemStatus} aria-label="条目状态">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">全部状态</SelectItem>
            {Object.entries(labels).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <LoadingButton
          loading={itemsLoading}
          variant="ghost"
          size="icon"
          className={styles.itemRefresh}
          aria-label="重新读取证据条目"
          disabled={!selectedSuiteId || itemsLoading}
          onClick={onRefresh}
        >
          <RefreshCw />
        </LoadingButton>
        <Button className={styles.itemCreate} onClick={onCreateItem} disabled={!selectedSuiteId}>
          <Plus />
          新建条目
        </Button>
      </div>
      {itemsError !== null ? (
        <WorkspaceNotice
          placement={filteredItems.length > 0 ? 'floating' : 'inline'}
          tone={filteredItems.length > 0 ? 'warning' : 'error'}
          retry={onRefresh}
          pending={itemsLoading}
        >
          {itemsError}
        </WorkspaceNotice>
      ) : null}
      {!selectedSuiteId ? (
        <p className={ws.muted}>从目录选择一个证据集。</p>
      ) : itemsLoading && filteredItems.length === 0 ? (
        <div className="space-y-2" aria-label="正在读取证据条目">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : filteredItems.length ? (
        <div aria-busy={itemsLoading}>
          <WorkspaceTableScroll label="证据条目表格">
            <table className={`${ws.table} ${styles.itemTable}`} aria-label="证据条目列表">
              <colgroup>
                <col className={styles.questionColumn} />
                <col className={styles.statusColumn} />
                <col className={styles.citationsColumn} />
                <col />
              </colgroup>
              <thead>
                <tr>
                  <th>问题与说明</th>
                  <th>状态</th>
                  <th>引用数</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => (
                  <tr key={item.id} data-selected={selectedItemId === item.id}>
                    <td>
                      <button
                        className="text-left text-sm font-medium underline-offset-4 hover:underline"
                        onClick={() => onSelectItem(item.id)}
                      >
                        {item.query}
                      </button>
                      {item.notes ? <p>{item.notes}</p> : null}
                    </td>
                    <td className="whitespace-nowrap">{labels[item.status] ?? item.status}</td>
                    <td className="tabular-nums">{item.reference_sources?.length ?? '—'}</td>
                    <td className="whitespace-nowrap text-xs tabular-nums">
                      {item.updated_at.slice(0, 19).replaceAll('T', ' ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </WorkspaceTableScroll>
        </div>
      ) : itemsError === null ? (
        <p className={ws.muted}>
          {itemQuery || statusFilter !== '__all__' ? '没有符合当前条件的条目。' : '此证据集还没有条目。'}
        </p>
      ) : null}
    </section>
  )
}
