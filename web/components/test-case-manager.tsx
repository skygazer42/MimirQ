/**
 * Golden 评测集管理组件
 *
 * 功能：
 * - 列表展示数据集级 Golden 评测样本
 * - 搜索和筛选
 * - 标记、删除操作
 * - 批量选择和操作
 */

'use client'

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query'
import { evaluationApi, ragApi } from '@/lib/api'
import type { RegressionCase, RegressionCaseCreate } from '@/types'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Search,
  Trash2,
  Plus,
  Loader2,
  CheckSquare,
  Square,
  Tag,
  Calendar,
  FileText,
  Upload,
  Star,
} from '@/components/icons'
import { toast } from 'sonner'
import { cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  buildRegressionReferenceSources,
  parseRegressionEvidencePack,
  type RegressionEvidencePack,
} from '@/lib/regression-evidence'

type TestCaseManagerProps = {
  datasetId: string | null
  onRunTests: (caseIds: string[]) => void
  isRunning?: boolean
  dense?: boolean
}

type RegressionEvidenceDraft = {
  pack: RegressionEvidencePack
  source: 'retrieve_preview' | 'evidence_pack'
  question: string
  expectedAnswer: string
  selectedChunkIds: ReadonlySet<string>
}

type TestCaseRowProps = {
  caseItem: RegressionCase
  isSelected: boolean
  isChecked: boolean
  isGolden: boolean
  isPending: boolean
  dense?: boolean
  onSelectCase: (caseId: string) => void
  onToggleSelect: (caseId: string) => void
  onToggleGolden: (caseItem: RegressionCase) => Promise<void>
  onDelete: (caseId: string) => Promise<void>
}

const GOLDEN_TAG = 'golden'
const GOLDEN_DRAFT_TAG = 'golden_draft'

function isGoldenCase(caseItem: RegressionCase): boolean {
  return caseItem.tags.includes(GOLDEN_TAG) || caseItem.tags.includes(GOLDEN_DRAFT_TAG)
}

function TestCaseRow({
  caseItem,
  isSelected,
  isChecked,
  isGolden,
  isPending,
  dense = false,
  onSelectCase,
  onToggleSelect,
  onToggleGolden,
  onDelete,
}: Readonly<TestCaseRowProps>) {
  const handleSelect = () => {
    onSelectCase(caseItem.id)
  }

  const handleToggleSelect = () => {
    onToggleSelect(caseItem.id)
  }

  const handleToggleGolden = () => {
    detachPromise(onToggleGolden(caseItem))
  }

  const hasManualGolden = caseItem.tags.includes(GOLDEN_TAG)
  const goldenActionLabel = hasManualGolden
    ? '移出人工 Golden 标记'
    : isGolden
      ? '已由插件草稿纳入 Golden，点击固定为人工 Golden'
      : '纳入 Golden 评测集'

  return (
    <div
      className={cn(
        'transition-colors motion-reduce:transition-none',
        dense ? 'px-3 py-3 hover:bg-muted/40' : 'p-4 hover:bg-muted/50',
        isSelected && (dense ? 'bg-info/5' : 'bg-primary/10'),
      )}
    >
      <div className={cn('flex items-start', dense ? 'gap-2.5' : 'gap-3')}>
        <button
          type="button"
          onClick={handleToggleSelect}
          className="mt-0.5"
          aria-pressed={isChecked}
          aria-label={isChecked ? '取消选择测试用例' : '选择测试用例'}
        >
          {isChecked ? (
            <CheckSquare className="w-4 h-4 text-primary" />
          ) : (
            <Square className="w-4 h-4 text-muted-foreground" />
          )}
        </button>

        <button type="button" className="flex-1 min-w-0 text-left" onClick={handleSelect} aria-pressed={isSelected}>
          <div
            className={cn(
              'font-medium text-foreground line-clamp-2',
              dense ? 'mb-1 text-[13px] leading-5' : 'mb-1 text-sm',
            )}
          >
            {caseItem.question}
          </div>

          {caseItem.expected_answer ? (
            <div className={cn('text-muted-foreground line-clamp-2', dense ? 'mb-1.5 text-[13px]' : 'mb-2 text-xs')}>
              标准答案: {caseItem.expected_answer}
            </div>
          ) : null}

          {caseItem.tags.length > 0 ? (
            <div className={cn('flex items-center gap-1 flex-wrap', dense ? 'mb-1.5' : 'mb-2')}>
              {[...new Set(caseItem.tags)].map((tag) => (
                <span
                  key={tag}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full border text-muted-foreground',
                    dense
                      ? 'border-info/15 bg-background/70 px-1.5 py-0.5 text-[12px]'
                      : 'border-border/60 bg-muted px-2 py-0.5 text-[13px]',
                  )}
                >
                  <Tag className="w-2.5 h-2.5" />
                  {tag}
                </span>
              ))}
            </div>
          ) : null}

          <div className="flex items-center gap-3 text-[13px] text-muted-foreground/80">
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {new Date(caseItem.created_at).toLocaleDateString()}
            </span>
            {caseItem.document_ids.length > 0 ? (
              <span className="flex items-center gap-1">
                <FileText className="w-3 h-3" />
                {caseItem.document_ids.length} 文档
              </span>
            ) : null}
            {caseItem.reference_sources.length > 0 ? (
              <span className="flex items-center gap-1">
                <Star className="w-3 h-3" />
                标准证据 {caseItem.reference_sources.length}
              </span>
            ) : null}
          </div>
        </button>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleToggleGolden}
            disabled={isPending}
            className={cn(
              'text-muted-foreground hover:text-foreground transition-colors motion-reduce:transition-none',
              isGolden && 'text-warning hover:text-warning',
            )}
            aria-label={goldenActionLabel}
            title={goldenActionLabel}
          >
            <Star className="w-4 h-4" fill={isGolden ? 'currentColor' : 'none'} />
          </button>

          <ConfirmDialog
            title="删除该测试用例？"
            description="此操作不可恢复。"
            confirmLabel="删除"
            cancelLabel="返回"
            confirmVariant="destructive"
            confirmDisabled={isPending}
            onConfirm={() => onDelete(caseItem.id)}
          >
            <button
              type="button"
              disabled={isPending}
              className="text-muted-foreground hover:text-destructive transition-colors motion-reduce:transition-none"
              aria-label="删除测试用例"
              title="删除"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </ConfirmDialog>
        </div>
      </div>
    </div>
  )
}

export function TestCaseManager({
  datasetId,
  onRunTests,
  dense = false,
  isRunning = false,
}: Readonly<TestCaseManagerProps>) {
  const queryClient = useQueryClient()
  const sessionKey = getAuthSessionKey()
  const mountedRef = useRef(false)
  const previewRequestRef = useRef<AbortController | null>(null)
  const importRequestRef = useRef<Promise<string> | null>(null)
  const evidenceSubmissionRef = useRef<Promise<RegressionCase> | null>(null)
  const pendingCaseIdsRef = useRef(new Set<string>())
  const [pendingCaseIds, setPendingCaseIds] = useState<ReadonlySet<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [goldenOnly, setGoldenOnly] = useState(false)
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(new Set())
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [newQuestion, setNewQuestion] = useState('')
  const [newExpectedAnswer, setNewExpectedAnswer] = useState('')
  const evidenceFileInputRef = useRef<HTMLInputElement>(null)
  const [evidenceDialogOpen, setEvidenceDialogOpen] = useState(false)
  const [evidenceDraft, setEvidenceDraft] = useState<RegressionEvidenceDraft | null>(null)
  const [evidenceLoading, setEvidenceLoading] = useState(false)
  const [evidenceImporting, setEvidenceImporting] = useState(false)
  const [evidenceCreating, setEvidenceCreating] = useState(false)
  const [evidenceSaveError, setEvidenceSaveError] = useState<string | null>(null)

  useLayoutEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      previewRequestRef.current?.abort()
    }
  }, [])

  function isCurrent() {
    return mountedRef.current && sessionKey === getAuthSessionKey()
  }

  const hasDataset = datasetId !== null
  const regressionCasesKey = queryKeys.evaluations.regressionCaseWindow(datasetId)
  const regressionCasesQuery = useQuery({
    queryKey: regressionCasesKey,
    queryFn: hasDataset ? ({ signal }) => evaluationApi.listRegressionCaseWindow(datasetId, { signal }) : skipToken,
  })
  const cases = regressionCasesQuery.data?.items
  const caseTotal = regressionCasesQuery.data?.total
  const casesFullyLoaded = regressionCasesQuery.data?.fullyLoaded
  const goldenCases = cases?.filter(isGoldenCase)
  const standardAnswerCount = cases?.filter(
    (caseItem) => caseItem.expected_answer !== null && caseItem.expected_answer.trim().length > 0,
  ).length
  const referenceSourceCount = cases?.reduce((total, caseItem) => total + caseItem.reference_sources.length, 0)
  const normalizedSearch = searchQuery.toLowerCase()
  const filteredCases = cases?.filter((caseItem) => {
    const searchable = [caseItem.question, caseItem.expected_answer, ...caseItem.tags].join(' ').toLowerCase()
    return searchable.includes(normalizedSearch) && (!goldenOnly || isGoldenCase(caseItem))
  })
  const allVisibleSelected =
    filteredCases !== undefined &&
    filteredCases.length > 0 &&
    filteredCases.every((caseItem) => selectedCaseIds.has(caseItem.id))
  const hiddenSelectionCount =
    selectedCaseIds.size -
    (filteredCases === undefined ? 0 : filteredCases.filter((caseItem) => selectedCaseIds.has(caseItem.id)).length)
  const selectedCasesPending = [...selectedCaseIds].some((caseId) => pendingCaseIds.has(caseId))

  useLayoutEffect(() => {
    const snapshot = regressionCasesQuery.data
    if (snapshot === undefined || !snapshot.fullyLoaded || regressionCasesQuery.isError) return
    const existingIds = new Set(snapshot.items.map((caseItem) => caseItem.id))
    setSelectedCaseIds((current) => {
      const remaining = new Set([...current].filter((caseId) => existingIds.has(caseId)))
      return remaining.size === current.size ? current : remaining
    })
    setSelectedCaseId((current) => (current !== null && !existingIds.has(current) ? null : current))
  }, [regressionCasesQuery.data, regressionCasesQuery.isError])

  function invalidateRegressionCases() {
    if (sessionKey === getAuthSessionKey()) {
      detachPromise(queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.regressionCaseLists() }))
    }
  }

  function setCasesPending(caseIds: readonly string[], pending: boolean) {
    for (const caseId of caseIds) {
      if (pending) pendingCaseIdsRef.current.add(caseId)
      else pendingCaseIdsRef.current.delete(caseId)
    }
    if (isCurrent()) setPendingCaseIds(new Set(pendingCaseIdsRef.current))
  }

  function toggleSelect(caseId: string) {
    setSelectedCaseIds((current) => {
      const next = new Set(current)
      if (next.has(caseId)) next.delete(caseId)
      else next.add(caseId)
      return next
    })
  }

  function toggleSelectAll(visibleCases: readonly RegressionCase[]) {
    setSelectedCaseIds((current) => {
      const next = new Set(current)
      const removeVisible = visibleCases.every((caseItem) => current.has(caseItem.id))
      for (const caseItem of visibleCases) {
        if (removeVisible) next.delete(caseItem.id)
        else next.add(caseItem.id)
      }
      return next
    })
  }

  async function deleteCaseIds(caseIds: string[]) {
    if (caseIds.some((caseId) => pendingCaseIdsRef.current.has(caseId))) {
      throw new Error('所选样本仍有操作进行中，请稍后再试')
    }
    setCasesPending(caseIds, true)
    try {
      const results = await Promise.allSettled(
        caseIds.map(async (caseId) => {
          await evaluationApi.deleteRegressionCase(caseId)
          return caseId
        }),
      )
      if (!isCurrent()) return
      const deletedIds = new Set(
        results.filter((result) => result.status === 'fulfilled').map((result) => result.value),
      )
      await queryClient.cancelQueries({ queryKey: regressionCasesKey, exact: true })
      if (!isCurrent()) return
      queryClient.setQueryData<NonNullable<typeof regressionCasesQuery.data>>(regressionCasesKey, (current) => {
        if (current === undefined) return current
        const items = current.items.filter((item) => !deletedIds.has(item.id))
        return {
          ...current,
          items,
          total: current.total === null ? null : current.total - (current.items.length - items.length),
        }
      })
      setSelectedCaseIds((current) => new Set([...current].filter((caseId) => !deletedIds.has(caseId))))
      setSelectedCaseId((current) => (current !== null && deletedIds.has(current) ? null : current))
      const failures = results.filter((result) => result.status === 'rejected')
      if (failures.length > 0) {
        throw new AggregateError(
          failures.map((result) => result.reason),
          `${deletedIds.size} 个已确认删除，${failures.length} 个未确认删除；请先刷新列表确认，再重试`,
        )
      }
      toast.success(caseIds.length === 1 ? '删除成功' : `已删除 ${deletedIds.size} 个测试用例`)
    } finally {
      invalidateRegressionCases()
      setCasesPending(caseIds, false)
    }
  }

  async function handleToggleGolden(caseItem: RegressionCase) {
    if (pendingCaseIdsRef.current.has(caseItem.id)) return
    const hasManualGolden = caseItem.tags.includes(GOLDEN_TAG)
    const tags = hasManualGolden ? caseItem.tags.filter((tag) => tag !== GOLDEN_TAG) : [...caseItem.tags, GOLDEN_TAG]
    setCasesPending([caseItem.id], true)
    try {
      const updated = await evaluationApi.patchRegressionCase(caseItem.id, { tags })
      if (updated.dataset_id !== datasetId) throw new Error('更新回执的数据集不匹配，请刷新样本列表确认')
      if (!isCurrent()) return
      queryClient.setQueryData<NonNullable<typeof regressionCasesQuery.data>>(regressionCasesKey, (current) => {
        if (current === undefined) return current
        return { ...current, items: current.items.map((item) => (item.id === updated.id ? updated : item)) }
      })
      toast.success(
        hasManualGolden
          ? caseItem.tags.includes(GOLDEN_DRAFT_TAG)
            ? '已移除人工 Golden 标记；该样本仍由插件草稿纳入'
            : '已移除人工 Golden 标记'
          : '已纳入 Golden 评测集',
      )
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, 'Golden 标记更新未确认，请先刷新列表'))
    } finally {
      invalidateRegressionCases()
      setCasesPending([caseItem.id], false)
    }
  }

  function openEvidenceDraft(
    pack: RegressionEvidencePack,
    source: RegressionEvidenceDraft['source'],
    expectedAnswer: string,
  ) {
    setEvidenceDraft({
      pack,
      source,
      question: pack.query === undefined ? '' : pack.query,
      expectedAnswer,
      selectedChunkIds:
        pack.selected_chunk_ids === undefined
          ? new Set(pack.citations.slice(0, 1).map((citation) => citation.chunk_id))
          : new Set(pack.selected_chunk_ids),
    })
    setEvidenceSaveError(null)
    setEvidenceDialogOpen(true)
  }

  function handleCreatingOpenChange(open: boolean) {
    if (!open) {
      previewRequestRef.current?.abort()
      previewRequestRef.current = null
      setEvidenceLoading(false)
    }
    setIsCreating(open)
  }

  async function handleCreate() {
    const question = newQuestion.trim()
    if (question === '') {
      toast.error('请输入问题')
      return
    }
    if (!hasDataset) {
      toast.error('请先选择数据集')
      return
    }
    if (previewRequestRef.current !== null) return
    const request = new AbortController()
    previewRequestRef.current = request
    setEvidenceLoading(true)
    try {
      const result = await ragApi.retrieveEvidence(
        { query: question, dataset_id: datasetId },
        { signal: request.signal },
      )
      const pack = parseRegressionEvidencePack({
        ...result,
        dataset_id: datasetId,
        query: question,
      })
      if (!isCurrent() || previewRequestRef.current !== request) return
      openEvidenceDraft(pack, 'retrieve_preview', newExpectedAnswer)
      setIsCreating(false)
    } catch (error) {
      if (isCurrent() && previewRequestRef.current === request && !request.signal.aborted) {
        toast.error(formatApiError(error, '未取得可用标准证据，请检查数据集与检索结果'))
      }
    } finally {
      if (previewRequestRef.current === request) {
        previewRequestRef.current = null
        if (isCurrent()) setEvidenceLoading(false)
      }
    }
  }

  function handleChooseEvidencePack() {
    evidenceFileInputRef.current?.click()
  }

  async function handleEvidencePackFile(file: File) {
    if (!hasDataset) {
      toast.error('请先选择导入目标数据集')
      return
    }
    const request = file.text()
    importRequestRef.current = request
    setEvidenceImporting(true)
    try {
      const raw = await request
      const value: unknown = JSON.parse(raw)
      const pack = parseRegressionEvidencePack(value)
      if (pack.dataset_id !== undefined && pack.dataset_id !== null && pack.dataset_id !== datasetId) {
        throw new Error(`证据包属于数据集 ${pack.dataset_id}，请先切换到该数据集`)
      }
      if (!isCurrent() || importRequestRef.current !== request) return
      openEvidenceDraft(pack, 'evidence_pack', '')
    } catch (error) {
      if (isCurrent() && importRequestRef.current === request) {
        toast.error(formatApiError(error, '证据包读取失败，请检查 JSON 及引用字段'))
      }
    } finally {
      if (importRequestRef.current === request) {
        importRequestRef.current = null
        if (isCurrent()) setEvidenceImporting(false)
      }
    }
  }

  function handleEvidenceDialogOpenChange(open: boolean) {
    if (evidenceSubmissionRef.current === null) setEvidenceDialogOpen(open)
  }

  async function handleCreateCaseFromEvidencePack(draft: RegressionEvidenceDraft) {
    if (evidenceSubmissionRef.current !== null) return
    if (!hasDataset) {
      toast.error('请先选择数据集')
      return
    }
    const question = draft.question.trim()
    if (question === '') {
      toast.error('请输入问题')
      return
    }
    if (draft.selectedChunkIds.size === 0) {
      toast.error('请至少选择一条标准证据')
      return
    }
    setEvidenceCreating(true)
    setEvidenceSaveError(null)
    try {
      const answer = draft.expectedAnswer.trim()
      const payload: RegressionCaseCreate = {
        question,
        dataset_id: datasetId,
        expected_answer: answer === '' ? undefined : answer,
        reference_sources: buildRegressionReferenceSources(draft.pack, draft.selectedChunkIds, draft.source),
        tags: [GOLDEN_TAG, draft.source === 'retrieve_preview' ? 'from_retrieval_preview' : 'evidence_pack'],
        extra: {
          evidence_pack_exported_at: draft.pack.exported_at,
          query_for_retrieval: draft.pack.query_for_retrieval,
          retrieval_metrics: draft.pack.metrics,
          has_evidence: draft.pack.has_evidence,
          abstain_triggered: draft.pack.abstain_triggered,
          abstain_reason: draft.pack.abstain_reason,
          created_from:
            draft.source === 'retrieve_preview' ? 'regression.test_case_manager' : 'regression.evidence_pack_import',
        },
      }
      evidenceSubmissionRef.current = evaluationApi.createRegressionCase(payload)
      const created = await evidenceSubmissionRef.current
      if (!isCurrent()) return
      await queryClient.cancelQueries({ queryKey: regressionCasesKey, exact: true })
      if (!isCurrent()) return
      queryClient.setQueryData<NonNullable<typeof regressionCasesQuery.data>>(regressionCasesKey, (current) => {
        if (current === undefined) return { items: [created], total: null, fullyLoaded: false }
        const exists = current.items.some((caseItem) => caseItem.id === created.id)
        const items = [created, ...current.items.filter((caseItem) => caseItem.id !== created.id)]
        const total = current.total === null ? null : current.total + (exists ? 0 : 1)
        return { items, total, fullyLoaded: current.fullyLoaded && items.length === total }
      })
      toast.success('已创建 Golden 评测样本')
      setEvidenceDialogOpen(false)
      if (draft.source === 'retrieve_preview') {
        setIsCreating(false)
        setNewQuestion('')
        setNewExpectedAnswer('')
      }
    } catch (error) {
      if (isCurrent()) {
        setEvidenceSaveError(
          `创建未确认，请先刷新样本列表确认是否已保存。 ${formatApiError(error, '请检查问题和所选证据')}`,
        )
      }
    } finally {
      if (evidenceSubmissionRef.current !== null) invalidateRegressionCases()
      evidenceSubmissionRef.current = null
      if (isCurrent()) setEvidenceCreating(false)
    }
  }

  function handleRunCaseIds(caseIds: string[], emptyMessage: string) {
    if (!hasDataset) {
      toast.error('请先选择数据集')
      return
    }
    if (caseIds.length === 0) {
      toast.error(emptyMessage)
      return
    }
    if (caseIds.some((caseId) => pendingCaseIdsRef.current.has(caseId))) {
      toast.error('所选样本仍有操作进行中，请稍后再运行')
      return
    }
    onRunTests(caseIds)
  }

  let caseListContent: ReactNode
  if (!hasDataset) {
    caseListContent = <p className="p-6 text-sm text-muted-foreground">先选择数据集，再管理 Golden 评测样本。</p>
  } else if (filteredCases === undefined) {
    caseListContent = (
      <div role="status" className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
        {regressionCasesQuery.isError ? (
          '尚未取得样本列表，请重新读取。'
        ) : (
          <>
            <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none" />
            正在读取评测样本…
          </>
        )}
      </div>
    )
  } else if (filteredCases.length === 0) {
    const hasFilters = searchQuery !== '' || goldenOnly
    let emptyTitle = hasFilters ? '已加载样本中没有匹配项' : '当前没有已加载样本'
    let emptyDescription = '列表尚未完整读取，请重新读取后再判断整个数据集的样本。'
    if (casesFullyLoaded) {
      emptyTitle = hasFilters ? '没有匹配的评测样本' : '暂无评测样本'
      emptyDescription = hasFilters
        ? '当前筛选条件没有命中样本，可以清空筛选或新增一条可复用标准问答。'
        : '添加标准问题、答案和引用证据，建立评测基准。'
    }

    caseListContent = (
      <div
        className={cn(
          'flex h-full min-h-[260px] items-center justify-center px-6 text-center',
          dense ? 'py-8' : 'py-10',
        )}
      >
        <div className="max-w-md">
          <FileText className="mx-auto size-6 text-muted-foreground" aria-hidden="true" />
          <div className="mt-4 text-base font-semibold text-foreground">{emptyTitle}</div>
          <div className="mt-2 text-[13px] leading-6 text-muted-foreground">{emptyDescription}</div>

          {hasFilters ? (
            <div className="mt-5">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setSearchQuery('')
                  setGoldenOnly(false)
                }}
              >
                清空筛选
              </Button>
            </div>
          ) : null}
        </div>
      </div>
    )
  } else {
    caseListContent = (
      <>
        <div
          className={cn(
            'border-b flex items-center gap-2',
            dense ? 'border-border/60 px-3 py-2' : 'border-border px-4 py-2',
          )}
        >
          <button
            type="button"
            onClick={() => toggleSelectAll(filteredCases)}
            aria-pressed={allVisibleSelected}
            className={cn(
              'flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors motion-reduce:transition-none',
              dense ? 'text-[13px]' : 'text-xs',
            )}
          >
            {allVisibleSelected ? <CheckSquare className="w-4 h-4" /> : <Square className="w-4 h-4" />}
            {allVisibleSelected ? '取消选择当前筛选结果' : '全选当前筛选结果'}
          </button>
        </div>

        <div className="divide-y divide-border">
          {filteredCases.map((caseItem) => {
            const isGolden = isGoldenCase(caseItem)
            return (
              <TestCaseRow
                key={caseItem.id}
                caseItem={caseItem}
                isSelected={selectedCaseId === caseItem.id}
                isChecked={selectedCaseIds.has(caseItem.id)}
                isGolden={isGolden}
                isPending={pendingCaseIds.has(caseItem.id)}
                dense={dense}
                onSelectCase={setSelectedCaseId}
                onToggleSelect={toggleSelect}
                onToggleGolden={handleToggleGolden}
                onDelete={(caseId) => deleteCaseIds([caseId])}
              />
            )
          })}
        </div>
      </>
    )
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-col h-full">
      {/* 头部操作栏 */}
      <div className={cn('border-b', dense ? 'border-border bg-background px-5 py-4' : 'border-border p-4')}>
        <div className={cn('flex flex-wrap items-center justify-between gap-3', dense ? 'mb-2.5' : 'mb-3')}>
          <div>
            <h3 className={cn('font-semibold text-foreground', dense ? 'text-[13px]' : 'text-sm')}>评测样本</h3>

            {dense && cases !== undefined ? (
              <div aria-label="Golden 评测集统计" className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
                <span className="text-[12px] text-muted-foreground">
                  {caseTotal === null ? '样本总数未取得' : `样本 ${caseTotal}`}
                  {!casesFullyLoaded ? ` · 已载 ${cases.length}` : ''}
                </span>
                <span className="text-[12px] text-muted-foreground">
                  {casesFullyLoaded ? 'Golden' : '已载 Golden'} {goldenCases?.length}
                </span>
                <span className="text-[12px] text-success">
                  {casesFullyLoaded ? '标准答案' : '已载标准答案'} {standardAnswerCount}
                </span>
                <span className="text-[12px] text-muted-foreground">
                  {casesFullyLoaded ? '标准证据' : '已载标准证据'} {referenceSourceCount}
                </span>
                <span className="text-[12px] text-primary">已选 {selectedCaseIds.size}</span>
              </div>
            ) : null}
          </div>
          <div className={cn('flex items-center', dense ? 'gap-1.5' : 'gap-2')}>
            {cases !== undefined && cases.length > 0 && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  className={cn(
                    'gap-2',
                    dense &&
                      'h-8 rounded-lg border-warning/30 bg-warning/5 px-2.5 text-[13px] text-warning hover:bg-warning/10',
                  )}
                  onClick={() =>
                    handleRunCaseIds(
                      cases.filter(isGoldenCase).map((caseItem) => caseItem.id),
                      '当前数据集暂无 Golden 样本',
                    )
                  }
                  disabled={isRunning || !hasDataset || goldenCases?.length === 0}
                >
                  <Star className="w-3.5 h-3.5" />
                  {casesFullyLoaded ? '运行 Golden' : '运行已载 Golden'}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className={cn('gap-2', dense && 'h-8 rounded-lg border-border/60 bg-card/90 px-2.5 text-[13px]')}
                  onClick={() =>
                    handleRunCaseIds(
                      cases.map((caseItem) => caseItem.id),
                      '当前数据集暂无评测样本',
                    )
                  }
                  disabled={isRunning || !hasDataset}
                >
                  {casesFullyLoaded ? '运行全部' : '运行已载'}
                </Button>
              </>
            )}
            {selectedCaseIds.size > 0 && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  className={cn('gap-2', dense && 'h-8 rounded-lg border-border/60 bg-card/90 px-2.5 text-[13px]')}
                  onClick={() => handleRunCaseIds([...selectedCaseIds], '请先选择评测样本')}
                  disabled={isRunning || !hasDataset || selectedCasesPending}
                >
                  运行选中 ({selectedCaseIds.size})
                </Button>
                <ConfirmDialog
                  title="批量删除测试用例？"
                  description={`将删除已选的 ${selectedCaseIds.size} 个测试用例，其中 ${hiddenSelectionCount} 个不在当前筛选结果中。此操作不可恢复。`}
                  confirmLabel="删除"
                  cancelLabel="返回"
                  confirmVariant="destructive"
                  confirmDisabled={selectedCasesPending}
                  onConfirm={() => deleteCaseIds([...selectedCaseIds])}
                >
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={selectedCasesPending}
                    className={cn(
                      'gap-2 text-destructive hover:text-destructive',
                      dense && 'h-8 rounded-lg border-border/60 bg-card/90 px-2.5 text-[13px]',
                    )}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    删除
                  </Button>
                </ConfirmDialog>
              </>
            )}
            <input
              ref={evidenceFileInputRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(event) => {
                const file = event.currentTarget.files?.item(0)
                event.currentTarget.value = ''
                if (file != null) detachPromise(handleEvidencePackFile(file))
              }}
            />
            <Button
              size="sm"
              variant="outline"
              className={cn('gap-2', dense && 'h-8 rounded-lg border-border/60 bg-card/90 px-2.5 text-[13px]')}
              onClick={handleChooseEvidencePack}
              disabled={!hasDataset || evidenceImporting || evidenceLoading || evidenceCreating}
              title={hasDataset ? '导入 Evidence Pack JSON' : '请先选择数据集'}
            >
              <Upload className="w-3.5 h-3.5" />
              {evidenceImporting ? '读取证据包中…' : '导入 Evidence Pack'}
            </Button>
            <Button
              size="sm"
              className={cn(
                'gap-2',
                dense && 'h-9 rounded-md bg-foreground px-3 text-[13px] text-background hover:bg-foreground/85',
              )}
              onClick={() => setIsCreating(true)}
              disabled={!hasDataset || evidenceImporting || evidenceCreating}
            >
              <Plus className="w-3.5 h-3.5" />
              新增标准问答
            </Button>
          </div>
        </div>

        {/* 搜索框 */}
        <div className="relative">
          <Search
            className={cn(
              'absolute top-1/2 -translate-y-1/2 text-muted-foreground',
              dense ? 'left-2.5 h-3.5 w-3.5' : 'left-3 h-4 w-4',
            )}
          />
          <Input
            aria-label="搜索 Golden 评测样本"
            type="text"
            placeholder="搜索问题、关键词或标签..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={cn(dense ? 'h-9 rounded-md border-border bg-background pl-8 text-[13px]' : 'pl-10')}
          />
        </div>

        <div className={cn('flex items-center justify-start gap-3', dense ? 'mt-2.5' : 'mt-3')}>
          <Button
            size="sm"
            variant={goldenOnly ? 'default' : 'outline'}
            className={cn(
              'gap-2',
              goldenOnly && 'bg-warning/15 text-warning hover:bg-warning/20',
              dense && 'h-8 rounded-lg border-border/60 bg-card/90 px-2.5 text-[13px]',
            )}
            onClick={() => {
              setGoldenOnly((v) => !v)
            }}
            disabled={!hasDataset}
            title={hasDataset ? '只显示纳入 Golden 评测集的样本' : '请先选择数据集'}
          >
            <Star className="w-3.5 h-3.5" fill={goldenOnly ? 'currentColor' : 'none'} />
            只看 Golden
          </Button>
        </div>
        {hiddenSelectionCount > 0 ? (
          <p role="status" className="mt-2 text-xs text-muted-foreground">
            已选 {selectedCaseIds.size} 个样本，其中 {hiddenSelectionCount}{' '}
            个不在当前筛选结果中；运行选中和批量删除包含这些样本。
          </p>
        ) : null}
        {regressionCasesQuery.data !== undefined && !casesFullyLoaded ? (
          <p className="mt-2 text-xs text-muted-foreground">
            {caseTotal === null
              ? `当前已知 ${cases?.length} 个样本，尚未取得完整列表。`
              : `当前加载 ${cases?.length} / ${caseTotal} 个样本。`}
            搜索、统计和批量运行只覆盖已加载部分。
          </p>
        ) : null}
        {regressionCasesQuery.isFetching && regressionCasesQuery.data !== undefined ? (
          <p role="status" className="mt-2 text-xs text-muted-foreground">
            正在更新样本列表，当前显示上次读取结果…
          </p>
        ) : null}
        {regressionCasesQuery.error !== null ? (
          <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 text-sm text-destructive">
            <p>
              {formatApiError(regressionCasesQuery.error, '样本列表读取失败')}
              {regressionCasesQuery.data !== undefined ? '；保留上次读取结果。' : ''}
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={regressionCasesQuery.isFetching}
              onClick={() => detachPromise(regressionCasesQuery.refetch())}
            >
              重新读取
            </Button>
          </div>
        ) : null}
      </div>

      <Dialog open={isCreating} onOpenChange={handleCreatingOpenChange}>
        <DialogContent className={cn('max-w-2xl', dense && 'max-h-[min(82vh,720px)] overflow-y-auto')}>
          <DialogHeader>
            <DialogTitle>新增标准问答</DialogTitle>
          </DialogHeader>

          <form
            className={cn(dense ? 'space-y-2.5' : 'space-y-3')}
            onSubmit={(event) => {
              event.preventDefault()
              detachPromise(handleCreate())
            }}
          >
            <div>
              <div
                className={cn('block font-medium text-muted-foreground', dense ? 'mb-1 text-[13px]' : 'mb-1 text-xs')}
              >
                标准问题 *
              </div>
              <Textarea
                aria-label="标准问题"
                required
                disabled={evidenceLoading}
                value={newQuestion}
                onChange={(e) => setNewQuestion(e.target.value)}
                placeholder="输入用于评估 RAG 的标准问题..."
                className={cn(
                  'resize-none',
                  dense ? 'min-h-[72px] rounded-xl border-border/60 bg-card/95 text-[13px]' : 'min-h-[72px]',
                )}
              />
            </div>
            <div>
              <div
                className={cn('block font-medium text-muted-foreground', dense ? 'mb-1 text-[13px]' : 'mb-1 text-xs')}
              >
                标准答案（推荐）
              </div>
              <Textarea
                aria-label="标准答案"
                disabled={evidenceLoading}
                value={newExpectedAnswer}
                onChange={(e) => setNewExpectedAnswer(e.target.value)}
                placeholder="输入可比对的标准答案..."
                className={cn(
                  'resize-none',
                  dense ? 'min-h-[72px] rounded-xl border-border/60 bg-card/95 text-[13px]' : 'min-h-[72px]',
                )}
              />
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                className={cn(
                  dense && 'h-9 rounded-md bg-foreground px-3 text-[13px] text-background hover:bg-foreground/85',
                )}
                type="submit"
                disabled={evidenceLoading || !hasDataset || newQuestion.trim() === ''}
              >
                {evidenceLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin motion-reduce:animate-none" />
                    检索中…
                  </>
                ) : (
                  '检索并选择标准证据'
                )}
              </Button>
              <Button
                size="sm"
                variant="outline"
                type="button"
                className={cn(dense && 'h-8 rounded-lg border-border/60 bg-card/90 px-2.5 text-[13px]')}
                onClick={() => {
                  handleCreatingOpenChange(false)
                  setNewQuestion('')
                  setNewExpectedAnswer('')
                }}
              >
                取消
              </Button>
            </div>
            <div
              className={cn(
                'rounded-xl border border-warning/30 bg-warning/5 px-3 py-2 text-muted-foreground',
                dense ? 'text-[13px] leading-5' : 'text-[13px]',
              )}
            >
              每个样本至少需要一条标准证据。检索后选择引用，或导入证据包，再确认创建。
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {evidenceDraft !== null ? (
        <Dialog open={evidenceDialogOpen} onOpenChange={handleEvidenceDialogOpenChange}>
          <DialogContent className="max-w-3xl max-h-[calc(100dvh-2rem)] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>选择标准证据并创建 Golden 样本</DialogTitle>
            </DialogHeader>
            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault()
                detachPromise(handleCreateCaseFromEvidencePack(evidenceDraft))
              }}
            >
              <div className="rounded-lg border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
                <p className="break-all">
                  目标数据集：<span className="font-mono text-foreground/80">{datasetId}</span>
                </p>
                <p className="mt-1">引用 {evidenceDraft.pack.citations.length} 条</p>
                {evidenceDraft.pack.exported_at !== undefined ? (
                  <p className="mt-1 break-all">导出时间：{evidenceDraft.pack.exported_at}</p>
                ) : null}
              </div>
              <fieldset disabled={evidenceCreating} className="space-y-4">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <label className="block text-xs font-medium text-muted-foreground">
                    标准问题
                    <Textarea
                      required
                      value={evidenceDraft.question}
                      onChange={(event) => setEvidenceDraft({ ...evidenceDraft, question: event.target.value })}
                      placeholder="输入评测问题"
                      className="mt-1 min-h-[84px] resize-none"
                    />
                  </label>
                  <label className="block text-xs font-medium text-muted-foreground">
                    标准答案（推荐）
                    <Textarea
                      value={evidenceDraft.expectedAnswer}
                      onChange={(event) => setEvidenceDraft({ ...evidenceDraft, expectedAnswer: event.target.value })}
                      placeholder="可选：标准答案"
                      className="mt-1 min-h-[84px] resize-none"
                    />
                  </label>
                </div>
                <div className="overflow-hidden rounded-lg border border-border">
                  <div className="flex items-center justify-between border-b border-border bg-card px-3 py-2">
                    <span className="text-xs font-semibold text-foreground">选择标准证据</span>
                    <span className="text-[13px] text-muted-foreground">
                      已选 {evidenceDraft.selectedChunkIds.size} / {evidenceDraft.pack.citations.length}
                    </span>
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {evidenceDraft.pack.citations.map((citation, index) => {
                      const label =
                        typeof citation.document_name === 'string'
                          ? `${citation.document_name}（${citation.document_id}）`
                          : citation.document_id
                      return (
                        <label
                          key={citation.chunk_id}
                          className="flex cursor-pointer items-start gap-3 border-b border-border/60 px-3 py-2 hover:bg-muted/30"
                        >
                          <input
                            type="checkbox"
                            aria-label={`选择引用 ${index + 1}：${label}`}
                            className="mt-1 h-4 w-4 rounded border-border"
                            checked={evidenceDraft.selectedChunkIds.has(citation.chunk_id)}
                            onChange={(event) => {
                              const selectedChunkIds = new Set(evidenceDraft.selectedChunkIds)
                              if (event.target.checked) selectedChunkIds.add(citation.chunk_id)
                              else selectedChunkIds.delete(citation.chunk_id)
                              setEvidenceDraft({ ...evidenceDraft, selectedChunkIds })
                            }}
                          />
                          <span className="min-w-0">
                            <span className="block truncate text-xs font-medium text-foreground" title={label}>
                              #{index + 1} {label}
                            </span>
                            <span className="mt-1 block line-clamp-2 text-[13px] text-muted-foreground">
                              {citation.chunk_content === undefined || citation.chunk_content === null
                                ? '未提供引用正文'
                                : citation.chunk_content}
                            </span>
                            <span className="mt-1 flex flex-wrap gap-2 break-all text-[13px] text-muted-foreground">
                              {citation.page_number !== undefined && citation.page_number !== null ? (
                                <span>p.{citation.page_number}</span>
                              ) : null}
                              <span className="font-mono">chunk:{citation.chunk_id}</span>
                            </span>
                          </span>
                        </label>
                      )
                    })}
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">每条引用摘录最多保存 2,000 个字符。</p>
              </fieldset>
              {evidenceSaveError !== null ? (
                <p role="alert" className="text-sm text-destructive">
                  {evidenceSaveError}
                </p>
              ) : null}
              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => handleEvidenceDialogOpenChange(false)}
                  disabled={evidenceCreating}
                >
                  取消
                </Button>
                <Button
                  type="submit"
                  disabled={
                    evidenceCreating ||
                    evidenceDraft.question.trim() === '' ||
                    evidenceDraft.selectedChunkIds.size === 0
                  }
                >
                  {evidenceCreating ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
                      创建中…
                    </>
                  ) : (
                    '创建 Golden 样本'
                  )}
                </Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
      ) : null}

      {/* 用例列表 */}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain custom-scrollbar">{caseListContent}</div>

      {/* 底部统计 */}
      {(filteredCases !== undefined && filteredCases.length > 0) || selectedCaseIds.size > 0 ? (
        <div
          className={cn(
            'border-t',
            dense ? 'border-info/15 bg-info/[0.025] px-3 py-2.5' : 'border-border bg-muted/30 p-3',
          )}
        >
          <div className={cn('text-center text-muted-foreground', dense ? 'text-[13px]' : 'text-xs')}>
            {filteredCases === undefined ? '样本列表尚未读取' : `已显示 ${filteredCases.length} 个测试用例`}
            {selectedCaseIds.size > 0 &&
              ` · 已选择 ${selectedCaseIds.size} 个（当前筛选外 ${hiddenSelectionCount} 个）`}
          </div>
        </div>
      ) : null}
    </div>
  )
}
