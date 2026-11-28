'use client'

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { ChevronsUpDown, Loader2, X } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { groupApi } from '@/lib/api/access'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

type GroupChipsInputProps = {
  id?: string
  value: string[]
  onChange: (next: string[]) => void
  disabled?: boolean
  placeholder?: string
  maxItems?: number
  className?: string
}

export function GroupChipsInput({
  id,
  value,
  onChange,
  disabled = false,
  placeholder = '选择组…',
  maxItems = 200,
  className,
}: Readonly<GroupChipsInputProps>) {
  const [open, setOpen] = useState(false)
  const groupsQuery = useQuery({
    queryKey: queryKeys.groups.options,
    queryFn: ({ signal }) => groupApi.listAllGroups({ signal }),
    enabled: open || value.length > 0,
    retry: false,
  })
  const selectedIds = useMemo(() => new Set(value), [value])
  const groupById = useMemo(() => new Map(groupsQuery.data?.map((group) => [group.id, group])), [groupsQuery.data])
  const selectable = groupsQuery.data?.filter((group) => !selectedIds.has(group.id))
  const atLimit = selectedIds.size >= maxItems

  function removeGroup(groupId: string) {
    if (disabled) return
    onChange([...selectedIds].filter((selectedId) => selectedId !== groupId))
  }

  function addGroup(groupId: string) {
    if (disabled || atLimit || selectedIds.has(groupId)) return
    onChange([...selectedIds, groupId])
    setOpen(false)
  }

  return (
    <div className={cn('space-y-2', className)}>
      <div className="flex flex-wrap gap-2">
        {selectedIds.size > 0 ? (
          Array.from(selectedIds, (groupId) => {
            const group = groupById.get(groupId)
            const label = group === undefined ? groupId : group.name
            return (
              <Badge key={groupId} variant="outline" className="min-w-0 max-w-full gap-1 pr-1.5">
                <span className="max-w-[220px] truncate" title={`${label} · ${groupId}`}>
                  {label}
                </span>
                <button
                  type="button"
                  className="ml-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded hover:bg-muted/50 focus-ring"
                  aria-label={`移除组：${label}`}
                  onClick={() => removeGroup(groupId)}
                  disabled={disabled}
                >
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
              </Badge>
            )
          })
        ) : (
          <span className="text-xs text-muted-foreground">{placeholder}</span>
        )}
      </div>

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            id={id}
            type="button"
            variant="outline"
            size="sm"
            className="w-full justify-between rounded-xl"
            disabled={disabled}
          >
            <span className="flex items-center gap-2">
              {groupsQuery.isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : null}
              <span className="text-sm">{value.length > 0 ? '添加/搜索组…' : '选择组…'}</span>
            </span>
            <ChevronsUpDown className="h-4 w-4 opacity-60" aria-hidden="true" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[380px] max-w-[calc(100vw-2rem)] p-0" align="start">
          <Command>
            <CommandInput aria-label="搜索组" placeholder="搜索组名称、外部标识或组 ID…" disabled={disabled} />
            {groupsQuery.isError ? (
              <div className="space-y-2 p-3">
                <p role="alert" className="text-sm text-destructive">
                  {formatApiError(groupsQuery.error, '加载组列表失败')}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={disabled || groupsQuery.isFetching}
                  onClick={() => {
                    void groupsQuery.refetch()
                  }}
                >
                  重新加载
                </Button>
              </div>
            ) : null}
            {groupsQuery.isPending ? (
              <p role="status" className="p-3 text-sm text-muted-foreground">
                正在加载组…
              </p>
            ) : null}
            <CommandList>
              {groupsQuery.data !== undefined ? (
                <CommandEmpty>
                  {groupsQuery.data.length === 0
                    ? '暂无可用的组'
                    : selectable?.length === 0
                      ? '已选择全部组'
                      : '未找到匹配的组'}
                </CommandEmpty>
              ) : null}
              {selectable?.map((group) => (
                <CommandItem
                  key={group.id}
                  value={group.id}
                  keywords={group.external_id ? [group.name, group.external_id] : [group.name]}
                  disabled={disabled || atLimit}
                  onSelect={() => addGroup(group.id)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium" title={group.name}>
                      {group.name}
                    </div>
                    {group.external_id ? (
                      <div className="truncate text-xs text-muted-foreground" title={group.external_id}>
                        外部标识：{group.external_id}
                      </div>
                    ) : null}
                    <div className="truncate font-mono text-xs text-muted-foreground" title={group.id}>
                      ID：{group.id}
                    </div>
                  </div>
                </CommandItem>
              ))}
            </CommandList>
            {atLimit ? (
              <p className="border-t p-3 text-xs text-muted-foreground">最多选择 {maxItems} 个组，请先移除已有选择。</p>
            ) : null}
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  )
}
