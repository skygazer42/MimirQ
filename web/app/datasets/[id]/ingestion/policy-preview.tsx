'use client'

import { FileSearch, Loader2 } from '@/components/icons'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingButton } from '@/components/ui/loading-button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatApiError } from '@/lib/api-errors'
import { formatPolicyDate } from './policy-model'
import type { IngestionPolicyController } from './use-ingestion-policy'
import styles from './policy.module.css'

export function PolicyPreviewDialog({ policyController }: { policyController: IngestionPolicyController }) {
  const { preview } = policyController
  const issues = preview?.clean.issues

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !policyController.previewing && !policyController.saving) policyController.setPreviewOpen(false)
      }}
    >
      <DialogContent
        className={styles.previewDialog}
        showCloseButton={!policyController.previewing && !policyController.saving}
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          policyController.restoreFocus()
        }}
      >
        <DialogHeader className={styles.dialogHeader}>
          <DialogTitle>文件预览</DialogTitle>
          <DialogDescription>
            {policyController.datasetQuery.data?.name} · 按已保存策略检查命中规则、解析与治理结果。
          </DialogDescription>
        </DialogHeader>
        <div className={styles.previewSource}>
          <div className={styles.field}>
            <Label htmlFor="policy-preview-file">选择文件</Label>
            <Input
              id="policy-preview-file"
              type="file"
              disabled={policyController.previewing || policyController.saving}
              onChange={(event) => policyController.setPreviewFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <LoadingButton
            className={styles.primaryAction}
            loading={policyController.previewing}
            disabled={!policyController.previewFile || policyController.dirty || policyController.blocked}
            onClick={() => {
              void policyController.runPreview()
            }}
          >
            <FileSearch />
            生成预览
          </LoadingButton>
        </div>
        {policyController.dirty ? (
          <div className={styles.previewDraftNotice}>
            <span>当前修改尚未保存，请先保存策略再预览。</span>
            <Button
              variant="outline"
              className={styles.primaryAction}
              disabled={policyController.blocked}
              onClick={() => {
                void policyController.save()
              }}
            >
              {policyController.saving ? '保存中' : '保存策略'}
            </Button>
          </div>
        ) : null}
        {policyController.saveError ? (
          <p className={styles.formError} role="alert">
            {policyController.saveError}
          </p>
        ) : null}
        {policyController.policyQuery.isError ? (
          <div className={styles.previewDraftNotice} role="alert">
            <span>已保存策略重新读取失败，请重新读取后再预览。</span>
            <Button
              variant="outline"
              disabled={policyController.policyQuery.isFetching}
              onClick={() => {
                void policyController.policyQuery.refetch()
              }}
            >
              重新读取策略
            </Button>
          </div>
        ) : null}
        {policyController.previewError ? (
          <p className={styles.formError} role="alert">
            {policyController.previewError}。文件已保留，可重新生成。
          </p>
        ) : null}
        {preview !== null ? (
          <div className={styles.previewResults}>
            <div className={styles.previewSummary}>
              <strong>
                {preview.rule.matched
                  ? `命中：${preview.rule.rule_name ?? preview.rule.rule_id}`
                  : '未命中规则，采用默认处理配置'}
              </strong>
              <span>
                {preview.rule.parser_backend}
                {preview.rule.chunk_strategy && ` · ${preview.rule.chunk_strategy}`}
                {preview.rule.governance_profile_ref && ` · ${preview.rule.governance_profile_ref}`}
              </span>
              <span>解析前预处理：{preview.preprocess.changed ? '文件已调整' : '文件未调整'}</span>
            </div>
            {issues && issues.length > 0 ? (
              <details className={styles.previewIssues}>
                <summary>检测到 {issues.length} 类问题</summary>
                <ul>
                  {issues.map((issue, index) => (
                    <li key={index}>
                      <span>{issue.severity}</span>
                      {issue.message}
                      {issue.count == null ? null : `（${issue.count}）`}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
            <Tabs defaultValue="compare" className={styles.previewTabs}>
              <TabsList className={styles.tabsList} aria-label="预览结果">
                <TabsTrigger value="compare">解析与治理对比</TabsTrigger>
                <TabsTrigger value="diff">文本差异</TabsTrigger>
              </TabsList>
              <TabsContent value="compare" className={styles.comparePanel}>
                <section>
                  <h3>解析后</h3>
                  <pre>{preview.parse.markdown ? preview.parse.markdown : '没有解析文本'}</pre>
                </section>
                <section>
                  <h3>治理后</h3>
                  <pre>{preview.clean.markdown === '' ? '没有治理文本' : preview.clean.markdown}</pre>
                </section>
              </TabsContent>
              <TabsContent value="diff" className={styles.diffPanel}>
                <pre>{preview.clean.diff_unified ? preview.clean.diff_unified : '没有文本差异'}</pre>
              </TabsContent>
            </Tabs>
          </div>
        ) : (
          <div className={styles.previewEmpty} role={policyController.previewing ? 'status' : undefined}>
            {policyController.previewing ? (
              <>
                <Loader2 className="animate-spin motion-reduce:animate-none" />
                <p>正在检查文件…</p>
              </>
            ) : (
              <>
                <FileSearch />
                <p>选择文件，查看已保存策略的处理结果。</p>
              </>
            )}
          </div>
        )}
        <div className={styles.dialogFooter}>
          <span>{policyController.previewFile?.name}</span>
          <Button
            variant="ghost"
            disabled={policyController.previewing || policyController.saving}
            onClick={() => policyController.setPreviewOpen(false)}
          >
            关闭
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function PolicyOverviewDialog({ policyController }: { policyController: IngestionPolicyController }) {
  const stats = policyController.statsQuery.data
  return (
    <Dialog open onOpenChange={policyController.setOverviewOpen}>
      <DialogContent
        className={styles.overviewDialog}
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          policyController.restoreFocus()
        }}
      >
        <DialogHeader className={styles.dialogHeader}>
          <DialogTitle>入库概览</DialogTitle>
          <DialogDescription>{policyController.datasetQuery.data?.name}</DialogDescription>
        </DialogHeader>
        <div className={styles.dialogBody}>
          {policyController.statsQuery.isPending ? (
            <p role="status">正在读取入库概览…</p>
          ) : policyController.statsQuery.isError ? (
            <div className={styles.fieldError} role="alert">
              {formatApiError(policyController.statsQuery.error, '入库概览读取失败')}
              <button
                onClick={() => {
                  void policyController.statsQuery.refetch()
                }}
              >
                重新读取
              </button>
            </div>
          ) : stats ? (
            <dl className={styles.statsList}>
              <div>
                <dt>文档</dt>
                <dd>{stats.total_documents.toLocaleString()}</dd>
              </div>
              <div>
                <dt>已完成 / 失败</dt>
                <dd>
                  {stats.by_status?.completed ?? 0} / {stats.by_status?.failed ?? 0}
                </dd>
              </div>
              <div>
                <dt>切块</dt>
                <dd>{stats.total_chunks.toLocaleString()}</dd>
              </div>
              <div>
                <dt>字符</dt>
                <dd>{stats.total_characters.toLocaleString()}</dd>
              </div>
              <div>
                <dt>最近处理</dt>
                <dd>{formatPolicyDate(stats.last_processed_at)}</dd>
              </div>
            </dl>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}
