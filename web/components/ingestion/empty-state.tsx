'use client'

import Link from 'next/link'

import { Ingestion } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { EmptyState as WorkspaceEmptyState } from '@/components/ui/empty-state'

type EmptyStateProps = {
  onUploadSample: () => void
  onUploadIngest: () => void
}

export function EmptyState({ onUploadSample, onUploadIngest }: Readonly<EmptyStateProps>) {
  return (
    <WorkspaceEmptyState
      title="还没有生成入库预检结果"
      description="上传样本查看文件类型和待复核的风险，再决定是否正式入库。"
      icon={Ingestion}
    >
      <div className="flex flex-wrap justify-center gap-2">
        <Button onClick={onUploadSample}>上传样本评估</Button>
        <Button variant="outline" onClick={onUploadIngest}>
          正式入库
        </Button>
        <Button asChild variant="ghost">
          <Link href="/datasets">选择数据集</Link>
        </Button>
      </div>
    </WorkspaceEmptyState>
  )
}
