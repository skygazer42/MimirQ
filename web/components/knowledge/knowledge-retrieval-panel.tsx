'use client'

import { BarChart3, Loader2, RefreshCw } from 'lucide-react'

import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { useIndexAudit } from '@/hooks/use-index-audit'

type KnowledgeRetrievalPanelProps = {
  selectedDatasetId?: string
}

export function KnowledgeRetrievalPanel({ selectedDatasetId }: KnowledgeRetrievalPanelProps) {
  const { indexAudit, indexAuditError, indexAuditLoading, runIndexAudit } = useIndexAudit({ selectedDatasetId })

  return (
    <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none motion-reduce:transition-none space-y-4">
      <Panel padding="none" className="rounded-2xl p-6 text-left bg-background/60 border border-border/60">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-primary" />
              <h4 className="text-sm font-semibold text-foreground">Index Audit</h4>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">数据集级索引一致性检查（Postgres ↔ 向量库；仅 owner/admin）</p>
            <p className="mt-1 text-xs text-muted-foreground">
              当前数据集：<span className="font-mono">{selectedDatasetId || '未选择'}</span>
            </p>
          </div>

          <Button
            type="button"
            variant="outline"
            className="h-9 rounded-xl border-border/60 bg-background/60 text-muted-foreground hover:bg-background gap-2"
            onClick={() => void runIndexAudit()}
            disabled={!selectedDatasetId || indexAuditLoading}
          >
            {indexAuditLoading ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            运行
          </Button>
        </div>

        {indexAuditError ? (
          <div className="mt-4 rounded-xl border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">
            {indexAuditError}
          </div>
        ) : null}

        {indexAudit ? (
          <div className="mt-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="text-xs text-muted-foreground">Vector Backend</div>
                <div className="mt-1 text-xs font-mono text-foreground/90">{indexAudit.vector_backend || '-'}</div>
              </div>
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="text-xs text-muted-foreground">Active Docs</div>
                <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.active_documents}</div>
              </div>
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="text-xs text-muted-foreground">Active Chunks</div>
                <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.active_chunks}</div>
              </div>
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="text-xs text-muted-foreground">DB Missing vector_id</div>
                <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.vector_id_missing}</div>
              </div>
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="text-xs text-muted-foreground">Checked IDs</div>
                <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.vector_ids_checked}</div>
              </div>
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="text-xs text-muted-foreground">Missing In Backend</div>
                <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.vector_ids_missing_in_backend}</div>
              </div>
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="text-xs text-muted-foreground">Milvus Sampled</div>
                <div className="mt-1 text-lg font-semibold text-foreground">{indexAudit.milvus_ids_sampled}</div>
              </div>
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="text-xs text-muted-foreground">Orphan Sample</div>
                <div className="mt-1 text-lg font-semibold text-foreground">
                  {(indexAudit.milvus_orphan_ids_sample || []).length}
                </div>
              </div>
            </div>

            {(indexAudit.vector_ids_missing_in_backend_sample || []).length > 0 ? (
              <div>
                <div className="text-xs font-medium text-foreground/80">Missing in Vector Backend (sample)</div>
                <pre className="mt-2 max-h-48 overflow-auto rounded-xl border border-border/60 bg-muted/20 p-3 text-xs font-mono text-muted-foreground">
                  {(indexAudit.vector_ids_missing_in_backend_sample || []).join('\n')}
                </pre>
              </div>
            ) : null}

            {(indexAudit.milvus_orphan_ids_sample || []).length > 0 ? (
              <div>
                <div className="text-xs font-medium text-foreground/80">Orphan Vector IDs (sample)</div>
                <pre className="mt-2 max-h-48 overflow-auto rounded-xl border border-border/60 bg-muted/20 p-3 text-xs font-mono text-muted-foreground">
                  {(indexAudit.milvus_orphan_ids_sample || []).join('\n')}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </Panel>
    </div>
  )
}
