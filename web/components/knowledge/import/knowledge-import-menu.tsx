'use client'

import { Bug, Globe, Link2, SlidersHorizontal, Upload, Zap } from 'lucide-react'

import { cn } from '@/lib/utils'
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from '@/components/ui/dropdown-menu'

type KnowledgeImportMenuProps = {
  onUploadFiles: () => void
  onOpenUrlImport: () => void
  onOpenUrlBatch: () => void
  onOpenWebCrawl: () => void
  onOpenJiraProject: () => void
  onOpenPipelineConfig: () => void

  className?: string
}

export function KnowledgeImportMenu({
  onUploadFiles,
  onOpenUrlImport,
  onOpenUrlBatch,
  onOpenWebCrawl,
  onOpenJiraProject,
  onOpenPipelineConfig,
  className,
}: KnowledgeImportMenuProps) {
  return (
    <div className={cn('min-w-0', className)}>
      <DropdownMenuLabel className="text-xs text-muted-foreground">添加</DropdownMenuLabel>
      <DropdownMenuItem onSelect={onUploadFiles} className="gap-2">
        <Upload className="size-4 text-muted-foreground" />
        上传文件
      </DropdownMenuItem>

      <DropdownMenuSeparator />
      <DropdownMenuLabel className="text-xs text-muted-foreground">导入</DropdownMenuLabel>

      <DropdownMenuItem onSelect={onOpenUrlImport} className="gap-2">
        <Link2 className="size-4 text-muted-foreground" />
        通过 URL
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={onOpenUrlBatch} className="gap-2">
        <Zap className="size-4 text-muted-foreground" />
        URL 批量（Connector）
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={onOpenWebCrawl} className="gap-2">
        <Globe className="size-4 text-muted-foreground" />
        Website Crawl
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={onOpenJiraProject} className="gap-2">
        <Bug className="size-4 text-muted-foreground" />
        Jira Project
      </DropdownMenuItem>

      <DropdownMenuSeparator />
      <DropdownMenuLabel className="text-xs text-muted-foreground">配置</DropdownMenuLabel>
      <DropdownMenuItem onSelect={onOpenPipelineConfig} className="gap-2">
        <SlidersHorizontal className="size-4 text-muted-foreground" />
        管线配置
      </DropdownMenuItem>
    </div>
  )
}
