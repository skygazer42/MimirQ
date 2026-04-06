'use client'

import { BarChart3, Loader2, RefreshCw } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { useIndexAudit } from '@/hooks/use-index-audit'
import { detachPromise } from '@/lib/utils'


type KnowledgeRetrievalPanelProps = {
  selectedDatasetId?: string
  compact?: boolean
}

export function KnowledgeRetrievalPanel({ selectedDatasetId, compact = false }: Readonly<KnowledgeRetrievalPanelProps>) {
  const t = useTranslations('KnowledgeRetrievalPanel')
  const { indexAudit, indexAuditError, indexAuditLoading, runIndexAudit } = useIndexAudit({ selectedDatasetId })
  const metricCards = indexAudit
    ? [
        { key: 'vectorBackend', value: indexAudit.vector_backend || '-' },
        { key: 'activeDocuments', value: indexAudit.active_documents },
        { key: 'activeChunks', value: indexAudit.active_chunks },
        { key: 'vectorIdMissing', value: indexAudit.vector_id_missing },
        { key: 'checkedIds', value: indexAudit.vector_ids_checked },
        { key: 'missingInBackend', value: indexAudit.vector_ids_missing_in_backend },
        { key: 'milvusSampled', value: indexAudit.milvus_ids_sampled },
        { key: 'orphanSample', value: (indexAudit.milvus_orphan_ids_sample || []).length },
      ]
    : []

  if (compact) {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-border/60 bg-background/40 px-4 py-3 backdrop-blur-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-primary" />
                <h4 className="text-sm font-semibold text-foreground">{t("header.title")}</h4>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t('header.description')}</p>
              <p className="mt-2 text-[11px] text-muted-foreground">
                {t('header.currentDataset')}: <span className="font-mono">{selectedDatasetId || t('header.noneSelected')}</span>
              </p>
            </div>

            <Button
              type="button"
              variant="outline"
              className="h-8 rounded-lg border-border/60 bg-background/60 px-2.5 text-xs text-muted-foreground hover:bg-background gap-1.5"
              onClick={() => detachPromise(runIndexAudit())}
              disabled={!selectedDatasetId || indexAuditLoading}
            >
              {indexAuditLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {t("actions.run")}
            </Button>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-auto p-4">
          {indexAuditError ? (
            <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-3 text-xs text-destructive">
              {indexAuditError}
            </div>
          ) : null}

          {indexAudit ? (
            <>
              <div className="space-y-2">
                {metricCards.map((item) => (
                  <div key={item.key} className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-background/60 px-3 py-2.5">
                    <div className="min-w-0 text-[11px] leading-relaxed text-muted-foreground">
                      {t(`metrics.${item.key}`)}
                    </div>
                    <div className="shrink-0 text-right text-sm font-semibold tabular-nums text-foreground">
                      {item.value}
                    </div>
                  </div>
                ))}
              </div>

              {(indexAudit.vector_ids_missing_in_backend_sample || []).length > 0 ? (
                <div>
                  <div className="text-[11px] font-medium text-foreground/80">{t('samples.missingInBackend')}</div>
                  <pre className="mt-2 max-h-40 overflow-auto rounded-xl border border-border/60 bg-muted/20 p-3 text-[11px] font-mono leading-relaxed text-muted-foreground">
                    {(indexAudit.vector_ids_missing_in_backend_sample || []).join('\n')}
                  </pre>
                </div>
              ) : null}

              {(indexAudit.milvus_orphan_ids_sample || []).length > 0 ? (
                <div>
                  <div className="text-[11px] font-medium text-foreground/80">{t('samples.orphanIds')}</div>
                  <pre className="mt-2 max-h-40 overflow-auto rounded-xl border border-border/60 bg-muted/20 p-3 text-[11px] font-mono leading-relaxed text-muted-foreground">
                    {(indexAudit.milvus_orphan_ids_sample || []).join('\n')}
                  </pre>
                </div>
              ) : null}
            </>
          ) : (
            <Panel padding="none" className="rounded-2xl border border-dashed border-border/60 bg-background/40 p-4">
              <div className="text-sm font-semibold text-foreground">{t("header.title")}</div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                运行一次审计后，这里会展示当前数据集的向量索引一致性和异常样本。
              </p>
            </Panel>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none motion-reduce:transition-none space-y-4">
      <Panel padding="none" className="rounded-2xl p-6 text-left bg-background/60 border border-border/60">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-primary" />
              <h4 className="text-sm font-semibold text-foreground">{t("header.title")}</h4>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t('header.description')}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t('header.currentDataset')}: <span className="font-mono">{selectedDatasetId || t('header.noneSelected')}</span>
            </p>
          </div>

          <Button
            type="button"
            variant="outline"
            className="h-9 rounded-xl border-border/60 bg-background/60 text-muted-foreground hover:bg-background gap-2"
            onClick={() => detachPromise(runIndexAudit())}
            disabled={!selectedDatasetId || indexAuditLoading}
          >
            {indexAuditLoading ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            {t("actions.run")}
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
              {metricCards.map((item) => (
                <div key={item.key} className="rounded-xl border border-border/60 bg-background/60 p-3">
                  <div className="text-xs text-muted-foreground">{t(`metrics.${item.key}`)}</div>
                  <div className="mt-1 text-lg font-semibold text-foreground">{item.value}</div>
                </div>
              ))}
            </div>

            {(indexAudit.vector_ids_missing_in_backend_sample || []).length > 0 ? (
              <div>
                <div className="text-xs font-medium text-foreground/80">{t('samples.missingInBackend')}</div>
                <pre className="mt-2 max-h-48 overflow-auto rounded-xl border border-border/60 bg-muted/20 p-3 text-xs font-mono text-muted-foreground">
                  {(indexAudit.vector_ids_missing_in_backend_sample || []).join('\n')}
                </pre>
              </div>
            ) : null}

            {(indexAudit.milvus_orphan_ids_sample || []).length > 0 ? (
              <div>
                <div className="text-xs font-medium text-foreground/80">{t('samples.orphanIds')}</div>
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
