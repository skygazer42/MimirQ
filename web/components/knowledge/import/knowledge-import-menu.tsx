'use client'

import { Bug, Globe, Link2, SlidersHorizontal, Upload, Zap } from '@/components/icons'
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from '@/components/ui/dropdown-menu'

type KnowledgeImportMenuProps = {
  onUploadFiles: () => void
  onOpenUrlImport: () => void
  onOpenUrlBatch: () => void
  onOpenWebCrawl: () => void
  onOpenJiraProject: () => void
  onOpenPipelineConfig: () => void
}

export function KnowledgeImportMenu({
  onUploadFiles,
  onOpenUrlImport,
  onOpenUrlBatch,
  onOpenWebCrawl,
  onOpenJiraProject,
  onOpenPipelineConfig,
}: Readonly<KnowledgeImportMenuProps>) {
  return (
    <>
      <DropdownMenuLabel className="text-xs text-muted-foreground">添加</DropdownMenuLabel>
      <DropdownMenuItem onSelect={onUploadFiles}>
        <Upload className="size-4 text-muted-foreground" />
        上传文件
      </DropdownMenuItem>

      <DropdownMenuSeparator />
      <DropdownMenuLabel className="text-xs text-muted-foreground">导入</DropdownMenuLabel>

      <DropdownMenuItem onSelect={onOpenUrlImport}>
        <Link2 className="size-4 text-muted-foreground" />
        通过 URL
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={onOpenUrlBatch}>
        <Zap className="size-4 text-muted-foreground" />
        URL 批量（Connector）
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={onOpenWebCrawl}>
        <Globe className="size-4 text-muted-foreground" />
        Website Crawl
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={onOpenJiraProject}>
        <Bug className="size-4 text-muted-foreground" />
        Jira Project
      </DropdownMenuItem>

      <DropdownMenuSeparator />
      <DropdownMenuLabel className="text-xs text-muted-foreground">配置</DropdownMenuLabel>
      <DropdownMenuItem onSelect={onOpenPipelineConfig}>
        <SlidersHorizontal className="size-4 text-muted-foreground" />
        管线配置
      </DropdownMenuItem>
    </>
  )
}
