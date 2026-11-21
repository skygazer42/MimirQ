'use client'

import { useId, useRef, useState } from 'react'
import { DirectoryWorkspace, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { SuiteActionsBar } from './suite-actions-bar'

import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TagInput } from '@/components/ui/tag-input'
import { Textarea } from '@/components/ui/textarea'
import { CreateItemDialog } from '@/components/evidence/create-item-dialog'
import { HardcaseCandidatesDialog } from '@/components/evidence/hardcase-candidates-dialog'
import { ItemDetailPanel } from '@/components/evidence/item-detail-panel'
import { ItemListPanel } from '@/components/evidence/item-list-panel'
import { SuiteDashboardDialog } from '@/components/evidence/suite-dashboard-dialog'
import { SuiteListPanel } from '@/components/evidence/suite-list-panel'
import { WhyMissedDialog } from '@/components/evidence/why-missed-dialog'
import { detachPromise } from '@/lib/utils'

import type { EvidenceSuiteWorkbenchState } from './use-evidence-suite-workbench-state'

export function EvidenceSuiteWorkbenchShell({
  applyRetrieveSuggestions,
  createItemOpen,
  createItemTab,
  createSuiteOpen,
  creatingItem,
  createItemError,
  creatingSuite,
  createSuiteError,
  convertingFeedbackIds,
  feedbackErrors,
  copyText,
  dashboardSnapshot,
  dashboardError,
  dashboardIncludeArchived,
  dashboardLoading,
  dashboardOpen,
  dataset,
  datasetError,
  loadDataset,
  datasetId,
  datasetLoading,
  evidenceStatusBadgeVariant,
  expectedNeedles,
  exportWhyMissedReport,
  exportingSuite,
  syncingSuite,
  syncNeedsRefresh,
  itemAction,
  fileInputRef,
  filteredItems,
  filteredSuites,
  handleApproveItem,
  handleArchiveItem,
  handleConvertFeedbackToEvidence,
  handleCreateItem,
  handleCreateSuite,
  handleExportSuite,
  handleImportQAFaq,
  handlePickPackFile,
  handleReviewItem,
  handleSyncSuite,
  hardcaseError,
  hardcaseIncludeExisting,
  hardcaseLoading,
  hardcaseMaxCandidates,
  hardcaseMaxRating,
  hardcaseOpen,
  hardcaseSnapshot,
  hardcaseTags,
  importCitations,
  importError,
  importPack,
  importSelectedChunkIds,
  importingQAFaq,
  importingPack,
  includeArchivedSuites,
  itemQuery,
  itemsError,
  itemsLoading,
  loadDashboard,
  loadHardcases,
  loadItems,
  loadSuites,
  loadWhyMissedDrift,
  newExpected,
  newNotes,
  newQuery,
  openCreateItem,
  openCreateSuite,
  pendingFeedbackId,
  openWhyMissed,
  profile,
  qaFaqInputRef,
  resetCreateSuiteForm,
  retrieveError,
  retrieveRanked,
  retrieveRes,
  retrieving,
  runRetrieve,
  runWhyMissedRetrieve,
  selectedChunkIds,
  selectedItem,
  selectedItemId,
  selectedSuite,
  selectedSuiteId,
  setCreateItemOpen,
  setCreateItemTab,
  setCreateSuiteOpen,
  setDashboardError,
  setDashboardIncludeArchived,
  setDashboardOpen,
  setHardcaseError,
  setHardcaseIncludeExisting,
  setHardcaseMaxCandidates,
  setHardcaseMaxRating,
  setHardcaseOpen,
  setHardcaseTags,
  setIncludeArchivedSuites,
  setItemQuery,
  setNewExpected,
  setNewNotes,
  setNewQuery,
  setPendingFeedbackId,
  setProfile,
  setSelectedItemId,
  setSelectedSuiteId,
  setStatusFilter,
  setSuiteDesc,
  setSuiteName,
  setSuiteQuery,
  setSuiteTags,
  setWhyMissedOpen,
  setWhyMissedProfile,
  statusFilter,
  suggestedRetrieveChunkIds,
  suiteCounts,
  suiteDesc,
  suiteName,
  suiteQuery,
  suiteTags,
  suitesError,
  suitesLoading,
  toggleChunkSelection,
  whyMissedCitations,
  whyMissedDriftError,
  whyMissedDriftLoading,
  whyMissedOpen,
  whyMissedProfile,
  whyMissedRanRetrieve,
  whyMissedRefChunkIds,
  whyMissedRefDocIds,
  whyMissedReport,
  whyMissedRetrieving,
  whyMissedError,
}: Readonly<EvidenceSuiteWorkbenchState>) {
  const [pane, setPane] = useState<'directory' | 'detail'>('directory')
  const createSuiteFormId = useId()
  const [detailOpen, setDetailOpen] = useState(false)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const pendingFeedbackError = feedbackErrors.get(pendingFeedbackId)
  function restoreItemFocus(event: Event) {
    const trigger = detailTrigger.current
    if (trigger?.isConnected) {
      event.preventDefault()
      trigger.focus()
    }
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {pendingFeedbackId ? (
        <div className="rounded-2xl border border-warning/25 bg-warning/8 px-4 py-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-1">
              <div className="text-sm font-semibold text-foreground">导入待处理反馈</div>
              <div className="text-xs text-muted-foreground text-pretty">
                当前链接携带了一个待处理的 <span className="font-mono">feedback_id</span>。确认目标 suite
                后，可直接导入为 draft EvidenceItem。
              </div>
              <div className="text-[11px] font-mono text-foreground/80">feedback_id={pendingFeedbackId}</div>
              {pendingFeedbackError !== undefined ? (
                <p role="alert" className="break-words text-sm text-destructive">
                  {pendingFeedbackError}
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <LoadingButton
                loading={convertingFeedbackIds.has(pendingFeedbackId)}
                type="button"
                size="sm"
                className="gap-2"
                disabled={!selectedSuiteId}
                onClick={() => {
                  detachPromise(
                    handleConvertFeedbackToEvidence(pendingFeedbackId, undefined, {
                      tags: ['expert-loop'],
                      source: 'chat_feedback_action',
                    }),
                  )
                }}
              >
                导入待处理反馈
              </LoadingButton>
              <Button type="button" size="sm" variant="outline" onClick={() => setPendingFeedbackId('')}>
                稍后处理
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {datasetError !== null ? (
        <WorkspaceNotice pending={datasetLoading} retry={() => detachPromise(loadDataset())}>
          {datasetError}
        </WorkspaceNotice>
      ) : null}
      <DirectoryWorkspace
        pane={pane}
        onPaneChange={setPane}
        directoryLabel="证据集"
        detailLabel="证据条目"
        directory={
          <SuiteListPanel
            datasetLabel={datasetLoading && dataset === null ? '加载中…' : (dataset?.name ?? datasetId)}
            suiteQuery={suiteQuery}
            onSuiteQueryChange={setSuiteQuery}
            onRefresh={() => detachPromise(loadSuites())}
            suitesLoading={suitesLoading}
            includeArchivedSuites={includeArchivedSuites}
            onIncludeArchivedSuitesChange={setIncludeArchivedSuites}
            suitesError={suitesError}
            filteredSuites={filteredSuites}
            selectedSuiteId={selectedSuiteId}
            onCreateSuite={openCreateSuite}
            onSelectSuite={(suiteId) => {
              setSelectedSuiteId(suiteId)
              setSelectedItemId('')
              setPane('detail')
            }}
          />
        }
      >
        {selectedSuiteId ? (
          <>
            <SuiteActionsBar
              key={selectedSuiteId}
              selectedSuite={selectedSuite}
              suiteCounts={suiteCounts}
              importingQAFaq={importingQAFaq}
              exportingSuite={exportingSuite}
              syncingSuite={syncingSuite}
              syncNeedsRefresh={syncNeedsRefresh}
              qaFaqInputRef={qaFaqInputRef}
              onImportQAFaqFile={(file) => {
                void handleImportQAFaq(file)
              }}
              onOpenHardcases={() => setHardcaseOpen(true)}
              onOpenDashboard={() => setDashboardOpen(true)}
              onExportSuite={() => detachPromise(handleExportSuite())}
              onSyncSuite={handleSyncSuite}
            />
            <ItemListPanel
              selectedSuiteId={selectedSuiteId}
              itemQuery={itemQuery}
              onItemQueryChange={setItemQuery}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              onRefresh={() => detachPromise(loadItems())}
              itemsLoading={itemsLoading}
              filteredItems={filteredItems}
              itemsError={itemsError}
              selectedItemId={selectedItemId}
              onCreateItem={openCreateItem}
              onSelectItem={(id) => {
                detailTrigger.current = document.activeElement as HTMLElement
                setSelectedItemId(id)
                setDetailOpen(true)
              }}
            />
          </>
        ) : suitesLoading ? (
          <div className="space-y-3 p-4" aria-label="正在读取证据集">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : (
          <div className={ws.empty}>
            <h2>
              {suitesLoading
                ? '正在读取证据集…'
                : suitesError
                  ? '证据集读取失败'
                  : filteredSuites.length
                    ? '选择证据集'
                    : suiteQuery
                      ? '没有匹配的证据集'
                      : '还没有证据集'}
            </h2>
            <p>
              {filteredSuites.length
                ? '从目录选择一个证据集，管理问题、答案和引用。'
                : '新建证据集后，添加用于复核与回归的问题。'}
            </p>
            {!suitesLoading && !suitesError ? (
              <Button onClick={suiteQuery ? () => setSuiteQuery('') : openCreateSuite}>
                {suiteQuery ? '清除搜索' : '新建证据集'}
              </Button>
            ) : null}
          </div>
        )}
      </DirectoryWorkspace>
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className={ws.dialog} onCloseAutoFocus={restoreItemFocus}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>证据条目</DialogTitle>
            <DialogDescription>复核标准答案和引用证据。</DialogDescription>
          </DialogHeader>
          <div className={ws.dialogBody}>
            <ItemDetailPanel
              key={selectedItemId}
              itemAction={itemAction}
              selectedItem={selectedItem}
              statusBadgeVariant={evidenceStatusBadgeVariant}
              onReviewItem={(itemId) => detachPromise(handleReviewItem(itemId))}
              onApproveItem={(itemId) => detachPromise(handleApproveItem(itemId))}
              onOpenWhyMissed={() => {
                setDetailOpen(false)
                openWhyMissed()
              }}
              onArchiveItem={handleArchiveItem}
            />
          </div>
        </DialogContent>
      </Dialog>

      <HardcaseCandidatesDialog
        open={hardcaseOpen}
        selectedSuiteId={selectedSuiteId}
        loading={hardcaseLoading}
        error={hardcaseError}
        snapshot={hardcaseSnapshot}
        maxRating={hardcaseMaxRating}
        includeExisting={hardcaseIncludeExisting}
        maxCandidates={hardcaseMaxCandidates}
        tags={hardcaseTags}
        convertingFeedbackIds={convertingFeedbackIds}
        feedbackErrors={feedbackErrors}
        onOpenChange={(open) => {
          setHardcaseOpen(open)
          if (!open) {
            setHardcaseError(null)
          }
        }}
        onMaxRatingChange={setHardcaseMaxRating}
        onIncludeExistingChange={setHardcaseIncludeExisting}
        onMaxCandidatesChange={setHardcaseMaxCandidates}
        onTagsChange={setHardcaseTags}
        onRefresh={() => detachPromise(loadHardcases())}
        onCopyText={(label, text) => {
          detachPromise(copyText(label, text))
        }}
        onConvertFeedback={(feedbackId, questionHash) => {
          detachPromise(handleConvertFeedbackToEvidence(feedbackId, questionHash))
        }}
      />

      <SuiteDashboardDialog
        open={dashboardOpen}
        selectedSuite={selectedSuite}
        selectedSuiteId={selectedSuiteId}
        includeArchived={dashboardIncludeArchived}
        loading={dashboardLoading}
        error={dashboardError}
        snapshot={dashboardSnapshot}
        onOpenChange={(open) => {
          setDashboardOpen(open)
          if (!open) {
            setDashboardError(null)
          }
        }}
        onIncludeArchivedChange={setDashboardIncludeArchived}
        onRefresh={() => detachPromise(loadDashboard())}
      />

      <Dialog
        open={createSuiteOpen}
        onOpenChange={(open) => {
          setCreateSuiteOpen(open)
          if (!open) resetCreateSuiteForm()
        }}
      >
        <DialogContent className={ws.dialog}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>新建证据集</DialogTitle>
            <DialogDescription className="text-pretty">将相关问题与引用证据组织在同一个证据集中。</DialogDescription>
          </DialogHeader>
          <form
            id={createSuiteFormId}
            className={ws.dialogBody}
            onSubmit={(event) => {
              event.preventDefault()
              detachPromise(handleCreateSuite())
            }}
          >
            <fieldset disabled={creatingSuite} className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="suite-name">名称</Label>
                <Input
                  id="suite-name"
                  value={suiteName}
                  onChange={(event) => setSuiteName(event.target.value)}
                  placeholder="例如：Refund Policy v1"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="suite-desc">描述（可选）</Label>
                <Textarea
                  id="suite-desc"
                  value={suiteDesc}
                  onChange={(event) => setSuiteDesc(event.target.value)}
                  placeholder="该 Suite 的范围 / 目标 / 约定…"
                  rows={3}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="evidence-suite-tags">标签（选填）</Label>
                <TagInput
                  inputId="evidence-suite-tags"
                  value={suiteTags}
                  onValueChange={setSuiteTags}
                  placeholder="输入后回车添加标签"
                />
              </div>
            </fieldset>
          </form>
          <DialogFooter className={`${ws.dialogFooter} flex-wrap`}>
            {createSuiteError !== null ? (
              <p role="alert" className="w-full min-w-0 break-words text-sm text-destructive">
                {createSuiteError}
              </p>
            ) : null}
            <Button type="button" variant="outline" onClick={() => setCreateSuiteOpen(false)}>
              取消
            </Button>
            <LoadingButton loading={creatingSuite} type="submit" form={createSuiteFormId} disabled={!suiteName.trim()}>
              创建
            </LoadingButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CreateItemDialog
        open={createItemOpen}
        newQuery={newQuery}
        newExpected={newExpected}
        newNotes={newNotes}
        createItemTab={createItemTab}
        profile={profile}
        retrieving={retrieving}
        datasetId={datasetId}
        suggestedRetrieveChunkIds={suggestedRetrieveChunkIds}
        selectedChunkIds={selectedChunkIds}
        retrieveError={retrieveError}
        expectedNeedles={expectedNeedles}
        hasRetrieveResult={retrieveRes !== null}
        retrieveRanked={retrieveRanked}
        fileInputRef={fileInputRef}
        hasImportPack={importPack !== null}
        importingPack={importingPack}
        importPackVersionLabel={importPack?.version == null ? '未提供' : String(importPack.version)}
        importCitations={importCitations}
        importError={importError}
        importSelectedChunkIds={importSelectedChunkIds}
        creatingItem={creatingItem}
        createItemError={createItemError}
        selectedSuiteId={selectedSuiteId}
        onOpenChange={setCreateItemOpen}
        onNewQueryChange={setNewQuery}
        onNewExpectedChange={setNewExpected}
        onNewNotesChange={setNewNotes}
        onCreateItemTabChange={setCreateItemTab}
        onProfileChange={setProfile}
        onRunRetrieve={() => detachPromise(runRetrieve())}
        onApplyRetrieveSuggestions={applyRetrieveSuggestions}
        onToggleRetrieveChunk={(chunkId) => toggleChunkSelection(chunkId, 'retrieve')}
        onPickPackFile={(file) => {
          detachPromise(handlePickPackFile(file))
        }}
        onToggleImportChunk={(chunkId) => toggleChunkSelection(chunkId, 'import')}
        onCreateItem={() => detachPromise(handleCreateItem())}
      />

      <WhyMissedDialog
        onCloseAutoFocus={restoreItemFocus}
        open={whyMissedOpen}
        datasetId={datasetId}
        selectedSuiteId={selectedSuiteId}
        selectedItem={selectedItem}
        whyMissedProfile={whyMissedProfile}
        whyMissedRetrieving={whyMissedRetrieving}
        whyMissedDriftLoading={whyMissedDriftLoading}
        whyMissedReport={whyMissedReport}
        whyMissedError={whyMissedError}
        whyMissedDriftError={whyMissedDriftError}
        whyMissedRanRetrieve={whyMissedRanRetrieve}
        whyMissedCitations={whyMissedCitations}
        whyMissedRefDocIds={whyMissedRefDocIds}
        whyMissedRefChunkIds={whyMissedRefChunkIds}
        onOpenChange={setWhyMissedOpen}
        onWhyMissedProfileChange={setWhyMissedProfile}
        onRunRetrieve={() => detachPromise(runWhyMissedRetrieve())}
        onLoadDrift={() => detachPromise(loadWhyMissedDrift())}
        onExportReport={exportWhyMissedReport}
      />
    </div>
  )
}
