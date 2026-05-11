'use client'

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Check, ChevronsUpDown, Loader2, X } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { groupApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import type { TenantGroupOut } from '@/types/backend'

const GROUP_LIST_PARAMS = { limit: 1000 } as const

export function GroupChipsInput({
  value,
  onChange,
  disabled,
  placeholder = '选择组…',
  maxItems = 200,
  className,
}: Readonly<{
  value: string[]
  onChange: (next: string[]) => void
  disabled?: boolean
  placeholder?: string
  maxItems?: number
  className?: string
}>) {
  const [open, setOpen] = useState(false)
  const groupsQuery = useQuery<TenantGroupOut[]>({
    queryKey: queryKeys.groups.list(GROUP_LIST_PARAMS),
    retry: false,
    queryFn: async () => {
      try {
        const res = await groupApi.listGroups(GROUP_LIST_PARAMS)
        return Array.isArray(res.items) ? res.items : []
      } catch (err: unknown) {
        toast.error(formatApiError(err, '加载组列表失败'))
        throw err
      }
    },
  })
  const groups = useMemo(() => groupsQuery.data || [], [groupsQuery.data])
  const loading = groupsQuery.isFetching

  const groupById = useMemo(() => new Map(groups.map((g) => [g.id, g])), [groups])

  const selected = useMemo(() => {
    const ids = Array.isArray(value) ? value : []
    const out: Array<{ id: string; label: string; subtitle?: string | null }> = []
    for (const id of ids) {
      const gid = String(id || '').trim()
      if (!gid) continue
      const g = groupById.get(gid)
      out.push({
        id: gid,
        label: g?.name || gid.slice(0, 8),
        subtitle: g?.external_id || null,
      })
    }
    return out
  }, [value, groupById])

  const selectable = useMemo(() => {
    const selectedSet = new Set((value || []).map(String))
    return (groups || []).filter((g) => !selectedSet.has(String(g.id)))
  }, [groups, value])

  const remove = (id: string) => {
    const gid = String(id || '').trim()
    if (!gid) return
    onChange((value || []).filter((x) => String(x) !== gid))
  }

  const add = (id: string) => {
    const gid = String(id || '').trim()
    if (!gid) return
    const current = Array.isArray(value) ? value : []
    if (current.includes(gid)) return
    const next = [...current, gid]
    if (next.length > maxItems) {
      toast.error(`最多选择 ${maxItems} 个组`)
      return
    }
    onChange(next)
  }

  return (
    <div className={cn('space-y-2', className)}>
      <div className="flex flex-wrap gap-2">
        {selected.length ? (
          selected.map((s) => (
            <Badge key={s.id} variant="outline" className="gap-1 pr-1.5">
              <span className="truncate max-w-[220px]">{s.label}</span>
              <button
                type="button"
                className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded hover:bg-muted/50 focus-ring"
                aria-label="移除组"
                onClick={() => remove(s.id)}
                disabled={disabled}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))
        ) : (
          <span className="text-xs text-muted-foreground">{placeholder}</span>
        )}
      </div>

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full justify-between rounded-xl"
            disabled={disabled}
          >
            <span className="flex items-center gap-2">
              {loading ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
              <span className="text-sm">{selected.length ? '添加/搜索组…' : '选择组…'}</span>
            </span>
            <ChevronsUpDown className="h-4 w-4 opacity-60" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[380px] p-0" align="start">
          <Command shouldFilter={true}>
            <CommandInput placeholder="搜索组（name / external_id / id）…" />
            <CommandList>
              <CommandEmpty>{loading ? '加载中…' : '未找到匹配的组'}</CommandEmpty>
              {selectable.map((g) => {
                const gid = String(g.id || '')
                return (
                  <CommandItem
                    key={gid}
                    value={`${g.name} ${g.external_id || ''} ${gid}`}
                    onSelect={() => {
                      if (disabled) return
                      add(gid)
                      setOpen(false)
                    }}
                    className="gap-2"
                  >
                    <Check className="h-4 w-4 opacity-0" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{g.name}</div>
                      <div className="truncate text-xs text-muted-foreground font-mono">
                        {g.external_id ? `external_id: ${g.external_id} · ` : ''}
                        id: {gid.slice(0, 8)}…
                      </div>
                    </div>
                  </CommandItem>
                )
              })}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  )
}
