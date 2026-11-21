'use client'

import type { RefObject } from 'react'
import { MoreHorizontal } from '@/components/icons'
import type { EvidenceSuite } from '@/types'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { workspaceStyles as ws } from '@/components/ui/operational-workspace'

type SuiteActionsBarProps = {
  selectedSuite: EvidenceSuite | null
  suiteCounts: EvidenceSuite['item_counts']
  importingQAFaq: boolean
  exportingSuite: boolean
  syncingSuite: boolean
  syncNeedsRefresh: boolean
  qaFaqInputRef: RefObject<HTMLInputElement | null>
  onImportQAFaqFile: (file: File) => void
  onOpenHardcases: () => void
  onOpenDashboard: () => void
  onExportSuite: () => void
  onSyncSuite: () => Promise<void>
}

export function SuiteActionsBar({
  selectedSuite,
  suiteCounts,
  importingQAFaq,
  exportingSuite,
  syncingSuite,
  syncNeedsRefresh,
  qaFaqInputRef,
  onImportQAFaqFile,
  onOpenHardcases,
  onOpenDashboard,
  onExportSuite,
  onSyncSuite,
}: Readonly<SuiteActionsBarProps>) {
  return (
    <section className="mb-5 border-b border-border pb-4">
      <div className={ws.sectionHeading}>
        <div>
          <h2 className={ws.sectionTitle}>{selectedSuite?.name ?? '选择证据集'}</h2>
          {suiteCounts ? (
            <p className={ws.muted}>
              共 {suiteCounts.total ?? '未提供'} 条 · 草稿 {suiteCounts.draft ?? '未提供'} · 已复核{' '}
              {suiteCounts.reviewed ?? '未提供'} · 已通过 {suiteCounts.approved ?? '未提供'} · 已归档{' '}
              {suiteCounts.archived ?? '未提供'}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ConfirmDialog
            title="同步到回归用例库？"
            description={`将「${selectedSuite?.name}」中已通过的条目同步到回归用例。已有绑定的用例会更新。`}
            confirmLabel={syncNeedsRefresh ? '重试刷新' : '同步用例'}
            confirmVariant="default"
            onConfirm={onSyncSuite}
          >
            <Button variant="outline" disabled={selectedSuite === null || syncingSuite}>
              同步到回归用例
            </Button>
          </ConfirmDialog>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" disabled={selectedSuite === null} aria-label="证据集操作">
                <MoreHorizontal />
                证据集操作
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem disabled={importingQAFaq} onSelect={() => qaFaqInputRef.current?.click()}>
                {importingQAFaq ? '正在导入 QA／FAQ…' : '导入 QA／FAQ'}
              </DropdownMenuItem>
              <DropdownMenuItem disabled={exportingSuite} onSelect={onExportSuite}>
                {exportingSuite ? '正在导出…' : '导出证据集'}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={onOpenHardcases}>难例候选</DropdownMenuItem>
              <DropdownMenuItem onSelect={onOpenDashboard}>统计概览</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <input
        ref={qaFaqInputRef}
        type="file"
        accept=".csv,.jsonl,text/csv,application/x-ndjson"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file !== undefined) onImportQAFaqFile(file)
          event.target.value = ''
        }}
      />
    </section>
  )
}
