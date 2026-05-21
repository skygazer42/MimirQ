'use client'

import type { Ref } from 'react'

import { Kbd } from '@/components/ui/kbd'
import { SearchInput } from '@/components/ui/search-input'

type GraphSearchOverlayProps = Readonly<{
  open: boolean
  inputRef: Ref<HTMLInputElement>
  searchTerm: string
  highlightedMatchCount: number
  onSearchTermChange: (value: string) => void
}>

export function GraphSearchOverlay({
  open,
  inputRef,
  searchTerm,
  highlightedMatchCount,
  onSearchTermChange,
}: GraphSearchOverlayProps) {
  if (!open) return null

  return (
    <div className="pointer-events-auto w-full min-w-[280px] max-w-md">
      <div className="relative">
        <SearchInput
          ref={inputRef}
          value={searchTerm}
          onValueChange={onSearchTermChange}
          placeholder="搜索实体节点、关系、路径..."
          aria-label="搜索实体节点、关系、路径"
          inputClassName="h-10 rounded-full bg-muted/60 shadow-sm pr-16"
        />
        <div className="pointer-events-none absolute right-11 top-1/2 flex -translate-y-1/2 items-center gap-2 text-xs text-muted-foreground">
          {searchTerm ? <span>{highlightedMatchCount} 匹配</span> : null}
          <span className="flex items-center gap-1">
            <Kbd className="h-5 px-1.5">Ctrl</Kbd>
            <Kbd className="h-5 px-1.5">F</Kbd>
          </span>
        </div>
      </div>
    </div>
  )
}
