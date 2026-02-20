'use client'

import { Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

type KnowledgeWorkbenchActionsProps = {
  className?: string
}

export function KnowledgeWorkbenchActions({ className }: KnowledgeWorkbenchActionsProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" size="sm" className={className}>
          <Plus className="size-4" />
          导入/新增
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <div className="px-2 py-1 text-xs text-muted-foreground">Coming soon</div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

