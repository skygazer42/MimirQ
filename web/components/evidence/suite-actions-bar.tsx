'use client'

import { useRef, useState, type RefObject } from 'react'
import { MoreHorizontal } from '@/components/icons'
import type { EvidenceSuite } from '@/types'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '@/components/ui/alert-dialog'
import { workspaceStyles as ws } from '@/components/ui/operational-workspace'

export function SuiteActionsBar({ selectedSuite, suiteCounts, importingQAFaq, qaFaqInputRef, onImportQAFaqFile, onOpenHardcases, onOpenDashboard, onExportSuite, onExportLtrTraining, onSyncSuite }: {
  selectedSuite: EvidenceSuite | null
  suiteCounts: { total: number; draft: number; reviewed: number; approved: number; archived: number } | null
  importingQAFaq: boolean
  qaFaqInputRef: RefObject<HTMLInputElement | null>
  onImportQAFaqFile: (file: File) => void
  onOpenHardcases: () => void
  onOpenDashboard: () => void
  onExportSuite: () => void
  onExportLtrTraining: () => void
  onSyncSuite: () => void
}) {
  const [confirm, setConfirm] = useState(false)
  const menuRef = useRef<HTMLButtonElement | null>(null)
  return <section className="mb-5 border-b border-border pb-4"><div className={ws.sectionHeading}><div><h2 className={ws.sectionTitle}>{selectedSuite?.name ?? '选择证据集'}</h2>{suiteCounts ? <p className={ws.muted}>共 {suiteCounts.total} 条 · 草稿 {suiteCounts.draft} · 已复核 {suiteCounts.reviewed} · 已通过 {suiteCounts.approved} · 已归档 {suiteCounts.archived}</p> : null}</div><DropdownMenu><DropdownMenuTrigger asChild><Button ref={menuRef} variant="outline" disabled={!selectedSuite} aria-label="证据集操作"><MoreHorizontal />证据集操作</Button></DropdownMenuTrigger><DropdownMenuContent align="end" onCloseAutoFocus={event => { if (confirm) event.preventDefault() }}><DropdownMenuItem disabled={importingQAFaq} onSelect={() => qaFaqInputRef.current?.click()}>导入 QA／FAQ</DropdownMenuItem><DropdownMenuItem onSelect={onExportSuite}>导出证据集</DropdownMenuItem><DropdownMenuItem onSelect={onExportLtrTraining}>导出排序训练数据</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem onSelect={onOpenHardcases}>难例候选</DropdownMenuItem><DropdownMenuItem onSelect={onOpenDashboard}>统计概览</DropdownMenuItem><DropdownMenuItem onSelect={() => setConfirm(true)}>同步到回归用例</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div>
    <input ref={qaFaqInputRef} type="file" accept=".csv,.jsonl,text/csv,application/x-ndjson" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) onImportQAFaqFile(file); event.target.value = '' }} />
    <AlertDialog open={confirm} onOpenChange={setConfirm}><AlertDialogContent onCloseAutoFocus={event => { event.preventDefault(); menuRef.current?.focus() }}><AlertDialogHeader><AlertDialogTitle>同步到回归用例库？</AlertDialogTitle><AlertDialogDescription>将「{selectedSuite?.name}」中已通过的条目同步到回归用例。已有绑定的用例会更新。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={onSyncSuite}>同步用例</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </section>
}
