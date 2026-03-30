'use client'

import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
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
  creatingSuite,
  convertingFeedbackId,
  copyText,
  dashboard,
  dashboardError,
  dashboardIncludeArchived,
  dashboardLoading,
  dashboardOpen,
  dataset,
  datasetId,
  datasetLoading,
  evidenceStatusBadgeVariant,
  expectedNeedles,
  exportWhyMissedReport,
  fileInputRef,
  filteredItems,
  filteredSuites,
  handleApproveItem,
  handleArchiveItem,
  handleConvertFeedbackToEvidence,
  handleCreateItem,
  handleCreateSuite,
  handleExportLtrTraining,
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
  hardcaseRes,
  hardcaseTags,
  importCitations,
  importError,
  importPack,
  importSelectedChunkIds,
  importingQAFaq,
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
  retrieveCitations,
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
  setImportSelectedChunkIds,
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
  setWhyMissedCitations,
  setWhyMissedDriftError,
  setWhyMissedDriftedRefs,
  setWhyMissedOpen,
  setWhyMissedProfile,
  setWhyMissedRanRetrieve,
  setWhyMissedError,
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
  return (
    <div className="space-y-4">
      {pendingFeedbackId ? (
        <div className="rounded-2xl border border-amber-500/25 bg-amber-500/8 px-4 py-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-1">
              <div className="text-sm font-semibold text-foreground">导入待处理反馈</div>
              <div className="text-xs text-muted-foreground text-pretty">
                当前链接携带了一个待处理的 <span className="font-mono">feedback_id</span>。确认目标 suite 后，可直接导入为 draft EvidenceItem。
              </div>
              <div className="text-[11px] font-mono text-foreground/80">feedback_id={pendingFeedbackId}</div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                className="gap-2"
                disabled={!selectedSuiteId || convertingFeedbackId === pendingFeedbackId}
                onClick={() => {
                  detachPromise(
                    (async () => {
                      const createdId = await handleConvertFeedbackToEvidence(pendingFeedbackId, undefined, {
                        tags: ['expert-loop'],
                        source: 'chat_feedback_action',
                      })
                      if (createdId) setPendingFeedbackId('')
                    })()
                  )
                }}
              >
                {convertingFeedbackId === pendingFeedbackId ? (
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                ) : null}
                导入待处理反馈
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setPendingFeedbackId('')}>
                稍后处理
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <SuiteListPanel
          datasetLabel={datasetLoading ? '加载中…' : dataset?.name || datasetId || '-'}
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
          }}
        />

        <ItemListPanel
          selectedSuite={selectedSuite}
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
          onSelectItem={setSelectedItemId}
          statusBadgeVariant={evidenceStatusBadgeVariant}
        />

        <ItemDetailPanel
          selectedItem={selectedItem}
          selectedSuite={selectedSuite}
          suiteCounts={suiteCounts}
          importingQAFaq={importingQAFaq}
          qaFaqInputRef={qaFaqInputRef}
          statusBadgeVariant={evidenceStatusBadgeVariant}
          onImportQAFaqFile={(file) => detachPromise(handleImportQAFaq(file))}
          onOpenHardcases={() => setHardcaseOpen(true)}
          onOpenDashboard={() => setDashboardOpen(true)}
          onExportSuite={handleExportSuite}
          onExportLtrTraining={handleExportLtrTraining}
          onSyncSuite={() => detachPromise(handleSyncSuite())}
          onReviewItem={(itemId) => detachPromise(handleReviewItem(itemId))}
          onApproveItem={(itemId) => detachPromise(handleApproveItem(itemId))}
          onOpenWhyMissed={openWhyMissed}
          onArchiveItem={(itemId) => detachPromise(handleArchiveItem(itemId))}
        />
      </div>

      <HardcaseCandidatesDialog
        open={hardcaseOpen}
        selectedSuiteId={selectedSuiteId}
        loading={hardcaseLoading}
        error={hardcaseError}
        hardcaseRes={hardcaseRes}
        maxRating={hardcaseMaxRating}
        includeExisting={hardcaseIncludeExisting}
        maxCandidates={hardcaseMaxCandidates}
        tags={hardcaseTags}
        convertingFeedbackId={convertingFeedbackId}
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
        dashboard={dashboard}
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
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建 Evidence Suite</DialogTitle>
            <DialogDescription className="text-pretty">Suite 用于组织证据 Items，并作为“同步到回归”的单位。</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
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
              <Label>Tags（可选）</Label>
              <TagInput value={suiteTags} onValueChange={setSuiteTags} placeholder="回车添加 tag…" />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateSuiteOpen(false)}>
              取消
            </Button>
            <Button onClick={() => detachPromise(handleCreateSuite())} disabled={creatingSuite || !suiteName.trim()}>
              {creatingSuite ? <Loader2 className="mr-2 size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}
              创建
            </Button>
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
        hasRetrieveResult={Boolean(retrieveRes)}
        retrieveRanked={retrieveRanked}
        fileInputRef={fileInputRef}
        hasImportPack={Boolean(importPack)}
        importPackVersionLabel={String(importPack?.version ?? '?')}
        importCitations={importCitations}
        importError={importError}
        importSelectedChunkIds={importSelectedChunkIds}
        creatingItem={creatingItem}
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
        onOpenChange={(open) => {
          setWhyMissedOpen(open)
          if (!open) {
            setWhyMissedError(null)
            setWhyMissedRanRetrieve(false)
            setWhyMissedCitations([])
            setWhyMissedDriftError(null)
            setWhyMissedDriftedRefs([])
          }
        }}
        onWhyMissedProfileChange={setWhyMissedProfile}
        onRunRetrieve={() => detachPromise(runWhyMissedRetrieve())}
        onLoadDrift={() => detachPromise(loadWhyMissedDrift())}
        onExportReport={exportWhyMissedReport}
      />
    </div>
  )
}
