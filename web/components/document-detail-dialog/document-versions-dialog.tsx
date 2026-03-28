'use client'

import { Copy, Hash } from 'lucide-react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { cn, formatDate } from '@/lib/utils'
import type { DocumentVersionList } from '@/types'

interface DocumentVersionsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  activePipelineHash: string | null | undefined
  versions: DocumentVersionList | null
  isLoading: boolean
  error: string | null
  isWorking: boolean
  onRefresh: () => void
  onCopy: (text: string) => void
  onActivate: (pipelineHash: string) => void
  onDelete: (pipelineHash: string) => void
}

export function DocumentVersionsDialog({
  open,
  onOpenChange,
  activePipelineHash,
  versions,
  isLoading,
  error,
  isWorking,
  onRefresh,
  onCopy,
  onActivate,
  onDelete,
}: Readonly<DocumentVersionsDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" className="w-full gap-2 sm:w-auto">
          <Hash className="h-4 w-4" />
          版本
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogTitle>文档版本（pipeline）</DialogTitle>
        <DialogDescription className="text-xs">
          用于运维/回滚：不同 pipeline 配置会生成不同的 <span className="font-mono">pipeline_hash</span> 版本；激活版本会影响检索与引用。
        </DialogDescription>

        <div className="mt-4 space-y-3">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Hash className="h-4 w-4" />
              正在加载版本信息...
            </div>
          ) : null}

          {error ? (
            <Alert variant="destructive">
              <AlertTitle>加载版本失败</AlertTitle>
              <AlertDescription className="flex items-center justify-between gap-3">
                <span className="min-w-0 flex-1">{error}</span>
                <Button variant="outline" size="sm" onClick={onRefresh}>
                  重试
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="rounded-xl border border-border/60 bg-muted/20 p-3">
            <div className="text-xs text-muted-foreground">当前激活 pipeline_hash</div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <div className="min-w-0 font-mono text-xs text-foreground">{activePipelineHash || '-'}</div>
              <IconButton
                label="复制 pipeline_hash"
                variant="ghost"
                className="h-9 w-9 text-muted-foreground hover:text-foreground"
                disabled={!activePipelineHash}
                onClick={() => onCopy(String(activePipelineHash || ''))}
              >
                <Copy className="h-4 w-4" />
              </IconButton>
            </div>
          </div>

          {!isLoading && !error ? (
            versions?.items?.length ? (
              <div className="space-y-2">
                {versions.items.map((version) => (
                  <div
                    key={version.pipeline_hash}
                    className={cn(
                      'flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card p-3',
                      version.active ? 'border-primary/30 bg-primary/5' : 'bg-card'
                    )}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-foreground">{version.pipeline_hash}</span>
                        {version.active ? (
                          <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                            ACTIVE
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {version.chunk_count} chunks
                        {version.last_chunk_at ? ` · 更新 ${formatDate(version.last_chunk_at)}` : ''}
                      </div>
                    </div>

                    <div className="flex flex-shrink-0 items-center gap-2">
                      <IconButton
                        label="复制版本 hash"
                        variant="ghost"
                        className="h-9 w-9 text-muted-foreground hover:text-foreground"
                        onClick={() => onCopy(version.pipeline_hash)}
                      >
                        <Copy className="h-4 w-4" />
                      </IconButton>

                      {version.active ? (
                        <Button size="sm" variant="secondary" disabled>
                          已激活
                        </Button>
                      ) : (
                        <>
                          <ConfirmDialog
                            title="切换激活版本？"
                            description={
                              <>
                                将把激活版本切换为 <span className="font-mono">{version.pipeline_hash.slice(0, 12)}…</span>。这不会重新解析/重新向量化，只会影响检索与引用。
                              </>
                            }
                            confirmLabel="切换"
                            cancelLabel="返回"
                            confirmVariant="default"
                            confirmDisabled={isWorking}
                            onConfirm={() => onActivate(version.pipeline_hash)}
                          >
                            <Button size="sm" variant="outline" disabled={isWorking}>
                              激活
                            </Button>
                          </ConfirmDialog>
                          <ConfirmDialog
                            title="删除该版本？"
                            description={
                              <>
                                将删除版本 <span className="font-mono">{version.pipeline_hash.slice(0, 12)}…</span>。注意：当前激活版本无法删除。
                              </>
                            }
                            confirmLabel="删除"
                            cancelLabel="返回"
                            confirmVariant="destructive"
                            confirmDisabled={isWorking}
                            onConfirm={() => onDelete(version.pipeline_hash)}
                          >
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={isWorking}
                              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                            >
                              删除
                            </Button>
                          </ConfirmDialog>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={Hash}
                title="暂无版本信息"
                description="当前文档还没有可用的 pipeline 版本记录（或尚未生成切片）。"
                className="min-h-[240px]"
              />
            )
          ) : null}

          <div className="text-xs text-muted-foreground">
            提示：激活/删除版本需要对文档所属数据集有写权限；删除操作不可恢复。
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
