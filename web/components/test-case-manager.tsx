/**
 * Golden 评测集管理组件
 *
 * 功能：
 * - 列表展示数据集级 Golden 评测样本
 * - 搜索和筛选
 * - 编辑、删除操作
 * - 批量选择和操作
 */

'use client'

import {
  useMemo,
  useRef,
  useState,
  useEffect,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { evaluationApi, ragApi } from '@/lib/api'
import type {
  Citation,
  RegressionCase,
  RegressionCaseCreate,
  RegressionReferenceSource,
} from '@/types'
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
} from 'lucide-react'
import { toast } from 'sonner'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { cn, detachPromise } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface TestCaseManagerProps {
  datasetId?: string | null
  onRunTests?: (caseIds: string[]) => void
  onCaseSelected?: (caseId: string | null) => void
  dense?: boolean
}

type EvidencePackDraft = {
  dataset_id?: string
  query?: string
  query_for_retrieval?: string
  metrics?: Record<string, unknown> | null
  citations?: Citation[]
  exported_at?: string
  source?: 'retrieve_preview' | 'evidence_pack'
  has_evidence?: boolean | null
  abstain_triggered?: boolean | null
  abstain_reason?: string | null
  selected_chunk_ids?: unknown[]
  [key: string]: unknown
}

type TestCaseRowProps = {
  caseItem: RegressionCase
  isSelected: boolean
  isChecked: boolean
  isGolden: boolean
  dense?: boolean
  onSelectCase: (caseItem: RegressionCase) => void
  onToggleSelect: (caseId: string) => void
  onToggleGolden: (caseItem: RegressionCase) => Promise<void>
  onDelete: (caseId: string) => Promise<void>
}

const GOLDEN_TAG = 'golden'
const GOLDEN_DRAFT_TAG = 'golden_draft'

function isGoldenCase(caseItem: RegressionCase): boolean {
  const tags = Array.isArray(caseItem.tags) ? caseItem.tags : []
  return tags.includes(GOLDEN_TAG) || tags.includes(GOLDEN_DRAFT_TAG)
}

function TestCaseRow({
  caseItem,
  isSelected,
  isChecked,
  isGolden,
  dense = false,
  onSelectCase,
  onToggleSelect,
  onToggleGolden,
  onDelete,
}: Readonly<TestCaseRowProps>) {
  const handleSelect = () => {
    onSelectCase(caseItem)
  }

  const handleToggleSelect = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    onToggleSelect(caseItem.id)
  }

  const handleToggleGolden = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    detachPromise(onToggleGolden(caseItem))
  }

  const hasManualGolden =
    Array.isArray(caseItem.tags) && caseItem.tags.includes(GOLDEN_TAG)
  const goldenActionLabel = hasManualGolden
    ? '移出人工 Golden 标记'
    : isGolden
      ? '已由插件草稿纳入 Golden，点击固定为人工 Golden'
      : '纳入 Golden 评测集'

  const handleDeleteConfirm = () => {
    detachPromise(onDelete(caseItem.id))
  }

  return (
    <div
      className={cn(
        'transition-colors motion-reduce:transition-none',
        dense ? 'px-3 py-3 hover:bg-slate-50/80' : 'p-4 hover:bg-muted/50',
        isSelected && (dense ? 'bg-sky-50/70' : 'bg-primary/10')
      )}
    >
      <div className={cn('flex items-start', dense ? 'gap-2.5' : 'gap-3')}>
        <button
          type="button"
          onClick={handleToggleSelect}
          className="mt-0.5"
          aria-label={isChecked ? '取消选择测试用例' : '选择测试用例'}
        >
          {isChecked ? (
            <CheckSquare className="w-4 h-4 text-primary" />
          ) : (
            <Square className="w-4 h-4 text-muted-foreground" />
          )}
        </button>

        <button
          type="button"
          className="flex-1 min-w-0 text-left"
          onClick={handleSelect}
        >
          <div
            className={cn(
              'font-medium text-foreground line-clamp-2',
              dense ? 'mb-1 text-[13px] leading-5' : 'mb-1 text-sm'
            )}
          >
            {caseItem.question}
          </div>

          {caseItem.expected_answer ? (
            <div
              className={cn(
                'text-muted-foreground line-clamp-2',
                dense ? 'mb-1.5 text-[11px]' : 'mb-2 text-xs'
              )}
            >
              标准答案: {caseItem.expected_answer}
            </div>
          ) : null}

          {caseItem.tags && caseItem.tags.length > 0 ? (
            <div
              className={cn(
                'flex items-center gap-1 flex-wrap',
                dense ? 'mb-1.5' : 'mb-2'
              )}
            >
              {caseItem.tags.map((tag) => (
                <span
                  key={tag}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full border text-muted-foreground',
                    dense
                      ? 'border-slate-200/80 bg-[#fffef9] px-1.5 py-0.5 text-[9px]'
                      : 'border-border/60 bg-muted px-2 py-0.5 text-[11px]'
                  )}
                >
                  <Tag className="w-2.5 h-2.5" />
                  {tag}
                </span>
              ))}
            </div>
          ) : null}

          <div className="flex items-center gap-3 text-[11px] text-muted-foreground/80">
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {new Date(caseItem.created_at).toLocaleDateString()}
            </span>
            {caseItem.document_ids?.length ? (
              <span className="flex items-center gap-1">
                <FileText className="w-3 h-3" />
                {caseItem.document_ids.length} 文档
              </span>
            ) : null}
            {caseItem.reference_sources?.length ? (
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
            className={cn(
              'text-muted-foreground hover:text-foreground transition-colors motion-reduce:transition-none',
              isGolden && 'text-amber-600 hover:text-amber-700'
            )}
            aria-label={goldenActionLabel}
            title={goldenActionLabel}
          >
            <Star
              className="w-4 h-4"
              fill={isGolden ? 'currentColor' : 'none'}
            />
          </button>

          <ConfirmDialog
            title="删除该测试用例？"
            description="此操作不可恢复。"
            confirmLabel="删除"
            cancelLabel="返回"
            confirmVariant="destructive"
            onConfirm={handleDeleteConfirm}
          >
            <button
              type="button"
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
  onCaseSelected,
  dense = false,
}: Readonly<TestCaseManagerProps>) {
  const queryClient = useQueryClient()
  const onCaseSelectedRef = useRef(onCaseSelected)

  const [searchQuery, setSearchQuery] = useState('')
  const [goldenOnly, setGoldenOnly] = useState(false)
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(new Set())
  const [selectedCase, setSelectedCase] = useState<RegressionCase | null>(null)

  // 创建用例的状态
  const [isCreating, setIsCreating] = useState(false)
  const [newQuestion, setNewQuestion] = useState('')
  const [newExpectedAnswer, setNewExpectedAnswer] = useState('')

  // Evidence Pack import → regression case authoring.
  const evidenceFileInputRef = useRef<HTMLInputElement>(null)
  const [evidenceDialogOpen, setEvidenceDialogOpen] = useState(false)
  const [evidencePack, setEvidencePack] = useState<EvidencePackDraft | null>(
    null
  )
  const [evidenceLoading, setEvidenceLoading] = useState(false)
  const [evidenceQuestion, setEvidenceQuestion] = useState('')
  const [evidenceExpectedAnswer, setEvidenceExpectedAnswer] = useState('')
  const [evidenceSelectedChunkIds, setEvidenceSelectedChunkIds] = useState<
    Set<string>
  >(new Set())
  const [evidenceCreating, setEvidenceCreating] = useState(false)

  useEffect(() => {
    onCaseSelectedRef.current = onCaseSelected
  }, [onCaseSelected])

  const evidenceCitations = useMemo(() => {
    const items = evidencePack?.citations
    return Array.isArray(items) ? items : []
  }, [evidencePack])

  const evidenceDatasetId = useMemo(() => {
    const fromPack =
      typeof evidencePack?.dataset_id === 'string'
        ? evidencePack.dataset_id.trim()
        : ''
    return fromPack || datasetId || ''
  }, [datasetId, evidencePack])

  const regressionCaseParams = useMemo(
    () => ({
      limit: 100,
      dataset_id: datasetId || undefined,
    }),
    [datasetId]
  )

  const regressionCasesQuery = useQuery({
    queryKey: queryKeys.evaluations.regressionCases(regressionCaseParams),
    enabled: Boolean(datasetId),
    queryFn: async () => {
      if (!datasetId) return []
      const result = await evaluationApi.listRegressionCases({
        limit: 100,
        dataset_id: datasetId,
      })
      return result.items || []
    },
  })

  const cases = useMemo(
    () => (datasetId ? (regressionCasesQuery.data ?? []) : []),
    [datasetId, regressionCasesQuery.data]
  )
  const isLoading = Boolean(datasetId) && regressionCasesQuery.isLoading

  const invalidateRegressionCases = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.evaluations.regressionCases(regressionCaseParams),
    })

  const createCaseMutation = useMutation({
    mutationFn: (payload: RegressionCaseCreate) =>
      evaluationApi.createRegressionCase(payload),
    onSuccess: invalidateRegressionCases,
  })

  const deleteCasesMutation = useMutation({
    mutationFn: (caseIds: string[]) =>
      Promise.all(
        caseIds.map((caseId) => evaluationApi.deleteRegressionCase(caseId))
      ),
    onSuccess: invalidateRegressionCases,
  })

  const patchCaseTagsMutation = useMutation({
    mutationFn: ({
      caseId,
      tags,
    }: {
      caseId: string
      tags: string[]
    }) => evaluationApi.patchRegressionCase(caseId, { tags }),
    onSuccess: invalidateRegressionCases,
  })

  useEffect(() => {
    setSelectedCaseIds(new Set())
    setSelectedCase(null)
    onCaseSelectedRef.current?.(null)
  }, [datasetId])

  useEffect(() => {
    if (!regressionCasesQuery.error) return
    console.error('加载测试用例失败:', regressionCasesQuery.error)
    toast.error(formatApiError(regressionCasesQuery.error, '加载测试用例失败'))
  }, [regressionCasesQuery.error])

  const goldenCount = useMemo(() => {
    return (cases || []).filter(isGoldenCase).length
  }, [cases])
  const standardAnswerCount = useMemo(() => {
    return (cases || []).filter(
      (c) =>
        typeof c.expected_answer === 'string' &&
        c.expected_answer.trim().length > 0
    ).length
  }, [cases])
  const referenceSourceCount = useMemo(() => {
    return (cases || []).reduce(
      (total, c) =>
        total +
        (Array.isArray(c.reference_sources) ? c.reference_sources.length : 0),
      0
    )
  }, [cases])
  const goldenCaseIds = useMemo(() => {
    return (cases || []).filter(isGoldenCase).map((c) => c.id)
  }, [cases])

  // 过滤用例
  const filteredCases = cases.filter((c) => {
    const query = searchQuery.toLowerCase()
    const searchable = [
      c.question,
      c.expected_answer,
      ...(Array.isArray(c.tags) ? c.tags : []),
    ]
      .join(' ')
      .toLowerCase()
    if (!searchable.includes(query)) return false
    if (!goldenOnly) return true
    return isGoldenCase(c)
  })

  // 切换选择
  const toggleSelect = (caseId: string) => {
    const newSet = new Set(selectedCaseIds)
    if (newSet.has(caseId)) {
      newSet.delete(caseId)
    } else {
      newSet.add(caseId)
    }
    setSelectedCaseIds(newSet)
  }

  // 全选/取消全选
  const toggleSelectAll = () => {
    if (selectedCaseIds.size === filteredCases.length) {
      setSelectedCaseIds(new Set())
    } else {
      setSelectedCaseIds(new Set(filteredCases.map((c) => c.id)))
    }
  }

  // 删除用例
  const handleDelete = async (caseId: string) => {
    try {
      await deleteCasesMutation.mutateAsync([caseId])
      toast.success('删除成功')
      if (selectedCase?.id === caseId) {
        setSelectedCase(null)
        onCaseSelected?.(null)
      }
    } catch (error) {
      console.error('删除失败:', error)
      toast.error(formatApiError(error, '删除失败'))
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedCaseIds.size === 0) return

    try {
      await deleteCasesMutation.mutateAsync(Array.from(selectedCaseIds))
      toast.success('批量删除成功')
      setSelectedCaseIds(new Set())
    } catch (error) {
      console.error('批量删除失败:', error)
      toast.error(formatApiError(error, '批量删除失败'))
    }
  }

  // 创建用例
  const handleCreate = async () => {
    const q = (newQuestion || '').trim()
    if (!q) {
      toast.error('请输入问题')
      return
    }
    if (!datasetId) {
      toast.error('请先选择数据集')
      return
    }

    setEvidenceLoading(true)
    try {
      const res = await ragApi.retrieveEvidence({
        query: q,
        dataset_id: datasetId,
      })
      const citations = Array.isArray(res?.citations)
        ? (res.citations as unknown as Citation[])
        : []
      if (!citations.length) {
        toast.error('未检索到可用 citations（请检查数据集是否已入库）')
        return
      }

      const exportedAt = new Date().toISOString()
      setEvidencePack({
        dataset_id: datasetId,
        query: q,
        query_for_retrieval: res?.query_for_retrieval || q,
        metrics: res?.metrics || null,
        citations,
        exported_at: exportedAt,
        source: 'retrieve_preview',
        has_evidence: (res as any)?.has_evidence ?? null,
        abstain_triggered: (res as any)?.abstain_triggered ?? null,
        abstain_reason: (res as any)?.abstain_reason ?? null,
      })
      setEvidenceQuestion(q)
      setEvidenceExpectedAnswer(newExpectedAnswer || '')

      // Default: select the top-1 citation as a starting point (operators can adjust).
      const firstChunkId = toTrimmedPrimitiveString(citations?.[0]?.chunk_id)
      setEvidenceSelectedChunkIds(
        firstChunkId ? new Set([firstChunkId]) : new Set()
      )

      setIsCreating(false)
      setEvidenceDialogOpen(true)
    } catch (error) {
      console.error('检索预览失败:', error)
      toast.error(formatApiError(error, '检索预览失败'))
    } finally {
      setEvidenceLoading(false)
    }
  }

  const handleChooseEvidencePack = () => {
    if (!datasetId) {
      toast.error('请先选择数据集')
      return
    }
    evidenceFileInputRef.current?.click()
  }

  const handleEvidencePackFile = async (file: File | null) => {
    if (!file) return
    try {
      const raw = await file.text()
      const parsed = JSON.parse(raw)
      const citations = Array.isArray(parsed?.citations)
        ? (parsed.citations as Citation[])
        : []
      if (!citations.length) {
        toast.error('Evidence Pack 缺少 citations')
        return
      }

      const ds =
        typeof parsed?.dataset_id === 'string'
          ? String(parsed.dataset_id).trim()
          : ''
      const effectiveDatasetId = ds || datasetId || ''
      if (!effectiveDatasetId) {
        toast.error('Evidence Pack 缺少 dataset_id，且当前未选择数据集')
        return
      }

      const q = typeof parsed?.query === 'string' ? parsed.query : ''
      setEvidencePack({
        ...parsed,
        dataset_id: effectiveDatasetId,
        source: 'evidence_pack',
      })
      setEvidenceQuestion(String(q || '').trim())
      setEvidenceExpectedAnswer('')

      const selectedChunkIds = Array.isArray(parsed?.selected_chunk_ids)
        ? parsed.selected_chunk_ids
        : []
      const normalizedSelected = selectedChunkIds
        .map((x: any) => toTrimmedPrimitiveString(x))
        .filter(Boolean)

      // Default: keep the exported selection (if present), else select top-1 as a starting point.
      const firstChunkId = toTrimmedPrimitiveString(citations?.[0]?.chunk_id)
      setEvidenceSelectedChunkIds(
        (() => {
          if (normalizedSelected.length) {
            return new Set(normalizedSelected)
          } else if (firstChunkId) {
            return new Set([firstChunkId])
          } else {
            return new Set()
          }
        })()
      )
      setEvidenceDialogOpen(true)
    } catch (err: any) {
      console.error('Failed to parse Evidence Pack', err)
      toast.error('Evidence Pack 解析失败（请确认是 JSON 文件）')
    } finally {
      // Allow re-selecting the same file.
      if (evidenceFileInputRef.current) evidenceFileInputRef.current.value = ''
    }
  }

  const handleCreateCaseFromEvidencePack = async () => {
    const ds = (evidenceDatasetId || '').trim()
    if (!ds) {
      toast.error('缺少 dataset_id')
      return
    }
    const q = (evidenceQuestion || '').trim()
    if (!q) {
      toast.error('请输入问题')
      return
    }
    if (!evidenceSelectedChunkIds.size) {
      toast.error('请至少选择 1 条证据引用（reference_sources）')
      return
    }

    const sourceTag =
      evidencePack?.source === 'retrieve_preview'
        ? 'from_retrieval_preview'
        : 'evidence_pack'
    const selected = new Set(Array.from(evidenceSelectedChunkIds || []))
    const refs: RegressionReferenceSource[] = (evidenceCitations || [])
      .filter((c: any) => selected.has(String(c?.chunk_id || '')))
      .map((c: any) => ({
        document_id: String(c?.document_id || ''),
        chunk_id: String(c?.chunk_id || ''),
        page_number:
          typeof c?.page_number === 'number' ? c.page_number : undefined,
        start_char:
          typeof c?.start_char === 'number' ? c.start_char : undefined,
        end_char: typeof c?.end_char === 'number' ? c.end_char : undefined,
        doc_pipeline_key:
          typeof c?.doc_pipeline_key === 'string'
            ? c.doc_pipeline_key
            : undefined,
        pipeline_hash:
          typeof c?.pipeline_hash === 'string' ? c.pipeline_hash : undefined,
        quote:
          typeof c?.chunk_content === 'string' ? c.chunk_content : undefined,
        label:
          sourceTag === 'from_retrieval_preview'
            ? 'ground_truth'
            : 'evidence_pack',
      }))
      .filter((r) => !!r.document_id && !!r.chunk_id)

    if (!refs.length) {
      toast.error('选中的证据引用无效（缺少 chunk_id/document_id）')
      return
    }

    setEvidenceCreating(true)
    try {
      const payload: RegressionCaseCreate = {
        question: q,
        dataset_id: ds,
        expected_answer: evidenceExpectedAnswer?.trim()
          ? evidenceExpectedAnswer.trim()
          : undefined,
        reference_sources: refs,
        tags: [GOLDEN_TAG, sourceTag],
        extra: {
          evidence_pack_exported_at: evidencePack?.exported_at || null,
          query_for_retrieval: evidencePack?.query_for_retrieval || null,
          retrieval_metrics: evidencePack?.metrics || null,
          has_evidence: evidencePack?.has_evidence ?? null,
          abstain_triggered: evidencePack?.abstain_triggered ?? null,
          abstain_reason: evidencePack?.abstain_reason ?? null,
          created_from:
            sourceTag === 'from_retrieval_preview'
              ? 'regression.test_case_manager'
              : 'regression.evidence_pack_import',
        },
      }
      await createCaseMutation.mutateAsync(payload)
      toast.success('已创建 Golden 评测样本')
      setEvidenceDialogOpen(false)
      setEvidencePack(null)
      setEvidenceSelectedChunkIds(new Set())
      setIsCreating(false)
      setNewQuestion('')
      setNewExpectedAnswer('')
    } catch (err: any) {
      console.error('Failed to create case from evidence pack', err)
      toast.error(formatApiError(err, '创建回归用例失败'))
    } finally {
      setEvidenceCreating(false)
    }
  }

  // 选择用例
  const handleSelectCase = (caseItem: RegressionCase) => {
    setSelectedCase(caseItem)
    onCaseSelected?.(caseItem.id)
  }

  const handleToggleGolden = async (caseItem: RegressionCase) => {
    const prevTags = Array.isArray(caseItem.tags) ? caseItem.tags : []
    const hasGolden = prevTags.includes(GOLDEN_TAG)
    const nextTags = hasGolden
      ? prevTags.filter((t) => t !== GOLDEN_TAG)
      : [...prevTags, GOLDEN_TAG]

    try {
      const updated = await patchCaseTagsMutation.mutateAsync({
        caseId: caseItem.id,
        tags: nextTags,
      })
      if (selectedCase?.id === caseItem.id) {
        setSelectedCase(updated)
        onCaseSelected?.(updated.id)
      }
      toast.success(hasGolden ? '已移出 Golden 评测集' : '已纳入 Golden 评测集')
    } catch (error) {
      console.error('Failed to toggle golden tag:', error)
      toast.error(formatApiError(error, '更新 Golden 标记失败'))
    }
  }

  const handleRunCaseIds = (caseIds: string[], emptyMessage: string) => {
    if (!datasetId) {
      toast.error('请先选择数据集')
      return
    }
    if (caseIds.length === 0) {
      toast.error(emptyMessage)
      return
    }
    onRunTests?.(caseIds)
  }

  // 运行选中的测试
  const handleRunSelected = () => {
    handleRunCaseIds(Array.from(selectedCaseIds), '请先选择评测样本')
  }

  const handleRunGolden = () => {
    handleRunCaseIds(goldenCaseIds, '当前数据集暂无 Golden 样本')
  }

  const handleRunAll = () => {
    handleRunCaseIds(
      cases.map((caseItem) => caseItem.id),
      '当前数据集暂无评测样本'
    )
  }

  let caseListContent: ReactNode
  if (isLoading) {
    caseListContent = (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground" />
      </div>
    )
  } else if (filteredCases.length === 0) {
    const emptyTitle = datasetId
      ? searchQuery || goldenOnly
        ? '没有匹配的评测样本'
        : '暂无 Golden 评测样本'
      : '先选择数据集'
    const emptyDescription = datasetId
      ? searchQuery || goldenOnly
        ? '当前筛选条件没有命中样本，可以清空筛选或新增一条可复用标准问答。'
        : '为当前数据集添加标准问题、标准答案和标准证据，用它作为评估 RAG pipeline 的固定标尺。'
      : 'Golden 评测集绑定到数据集，选择知识库后才能创建标准问答和标准证据。'

    caseListContent = (
      <div
        className={cn(
          'flex h-full min-h-[420px] items-center justify-center px-6 text-center',
          dense ? 'py-12' : 'py-10'
        )}
      >
        <div className="max-w-md">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl border border-slate-200/80 bg-[radial-gradient(circle_at_30%_20%,rgba(37,99,235,0.16),transparent_45%),linear-gradient(180deg,#ffffff_0%,#f8fbff_100%)] shadow-sm">
            <FileText className="h-7 w-7 text-blue-600" />
          </div>
          <div className="mt-4 text-base font-semibold text-foreground">
            {emptyTitle}
          </div>
          <div className="mt-2 text-[13px] leading-6 text-muted-foreground">
            {emptyDescription}
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            {(searchQuery || goldenOnly) && datasetId ? (
              <Button
                size="sm"
                variant="outline"
                className={cn(
                  dense &&
                    'h-8 rounded-lg border-slate-200/80 bg-card/90 px-2.5 text-[11px]'
                )}
                onClick={() => {
                  setSearchQuery('')
                  setGoldenOnly(false)
                }}
              >
                清空筛选
              </Button>
            ) : null}
            <Button
              size="sm"
              className={cn(
                'gap-2',
                dense && 'h-8 rounded-lg px-2.5 text-[11px]'
              )}
              onClick={() => setIsCreating(true)}
              disabled={!datasetId}
            >
              <Plus className="h-3.5 w-3.5" />
              新增标准问答
            </Button>
            <Button
              size="sm"
              variant="outline"
              className={cn(
                'gap-2',
                dense &&
                  'h-8 rounded-lg border-slate-200/80 bg-card/90 px-2.5 text-[11px]'
              )}
              onClick={handleChooseEvidencePack}
              disabled={!datasetId}
            >
              <Upload className="h-3.5 w-3.5" />
              导入 Evidence Pack
            </Button>
          </div>

          {datasetId ? (
            <div className="mt-6 grid grid-cols-3 gap-2 text-left">
              {[
                ['1', '标准问题', '固定 RAG 输入'],
                ['2', '标准证据', '标定 ground truth'],
                ['3', '差距评分', '追踪回归结果'],
              ].map(([step, title, desc]) => (
                <div
                  key={step}
                  className="rounded-2xl border border-slate-200/80 bg-card/90 p-2.5"
                >
                  <div className="text-[10px] font-semibold text-blue-600">
                    STEP {step}
                  </div>
                  <div className="mt-1 text-[11px] font-semibold text-foreground">
                    {title}
                  </div>
                  <div className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
                    {desc}
                  </div>
                </div>
              ))}
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
            dense ? 'border-slate-200/80 px-3 py-2' : 'border-border px-4 py-2'
          )}
        >
          <button
            type="button"
            onClick={toggleSelectAll}
            className={cn(
              'flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors motion-reduce:transition-none',
              dense ? 'text-[11px]' : 'text-xs'
            )}
          >
            {selectedCaseIds.size === filteredCases.length ? (
              <CheckSquare className="w-4 h-4" />
            ) : (
              <Square className="w-4 h-4" />
            )}
            全选
          </button>
        </div>

        <div className="divide-y divide-border">
          {filteredCases.map((caseItem) => {
            const isGolden = isGoldenCase(caseItem)
            return (
              <TestCaseRow
                key={caseItem.id}
                caseItem={caseItem}
                isSelected={selectedCase?.id === caseItem.id}
                isChecked={selectedCaseIds.has(caseItem.id)}
                isGolden={isGolden}
                dense={dense}
                onSelectCase={handleSelectCase}
                onToggleSelect={toggleSelect}
                onToggleGolden={handleToggleGolden}
                onDelete={handleDelete}
              />
            )
          })}
        </div>
      </>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* 头部操作栏 */}
      <div
        className={cn(
          'border-b',
          dense
            ? 'border-slate-200/80 bg-[#fffef9] px-3 py-3'
            : 'border-border p-4'
        )}
      >
        <div
          className={cn(
            'flex items-center justify-between',
            dense ? 'mb-2.5' : 'mb-3'
          )}
        >
          <div>
            <h3
              className={cn(
                'font-semibold text-foreground',
                dense ? 'text-[13px]' : 'text-sm'
              )}
            >
              Golden 评测集
            </h3>
            <p
              className={cn(
                'mt-1 text-muted-foreground',
                dense ? 'text-[11px] leading-4' : 'text-xs'
              )}
            >
              数据集级固定标尺：问题、标准答案、标准证据。
            </p>
            {dense ? (
              <div
                aria-label="Golden 评测集统计"
                className="mt-2 flex flex-wrap items-center gap-1.5"
              >
                <span className="rounded-full border border-slate-200 bg-card px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  样本 {cases.length}
                </span>
                <span className="rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">
                  Golden {goldenCount}
                </span>
                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">
                  标准答案 {standardAnswerCount}
                </span>
                <span className="rounded-full border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-700">
                  标准证据 {referenceSourceCount}
                </span>
                <span className="rounded-full border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">
                  已选 {selectedCaseIds.size}
                </span>
              </div>
            ) : null}
          </div>
          <div className={cn('flex items-center', dense ? 'gap-1.5' : 'gap-2')}>
            {cases.length > 0 && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  className={cn(
                    'gap-2',
                    dense &&
                      'h-8 rounded-lg border-amber-200/80 bg-amber-50/80 px-2.5 text-[11px] text-amber-700 hover:bg-amber-50'
                  )}
                  onClick={handleRunGolden}
                  disabled={!datasetId || goldenCaseIds.length === 0}
                >
                  <Star className="w-3.5 h-3.5" />
                  运行 Golden
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className={cn(
                    'gap-2',
                    dense &&
                      'h-8 rounded-lg border-slate-200/80 bg-card/90 px-2.5 text-[11px]'
                  )}
                  onClick={handleRunAll}
                  disabled={!datasetId || cases.length === 0}
                >
                  运行全部
                </Button>
              </>
            )}
            {selectedCaseIds.size > 0 && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  className={cn(
                    'gap-2',
                    dense &&
                      'h-8 rounded-lg border-slate-200/80 bg-card/90 px-2.5 text-[11px]'
                  )}
                  onClick={handleRunSelected}
                >
                  运行选中 ({selectedCaseIds.size})
                </Button>
                <ConfirmDialog
                  title="批量删除测试用例？"
                  description={`将删除 ${selectedCaseIds.size} 个测试用例。此操作不可恢复。`}
                  confirmLabel="删除"
                  cancelLabel="返回"
                  confirmVariant="destructive"
                  onConfirm={() => detachPromise(handleBatchDelete())}
                >
                  <Button
                    size="sm"
                    variant="outline"
                    className={cn(
                      'gap-2 text-destructive hover:text-destructive',
                      dense &&
                        'h-8 rounded-lg border-slate-200/80 bg-card/90 px-2.5 text-[11px]'
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
              onChange={(e) =>
                detachPromise(
                  handleEvidencePackFile(e.target.files?.[0] || null)
                )
              }
            />
            <Button
              size="sm"
              variant="outline"
              className={cn(
                'gap-2',
                dense &&
                  'h-8 rounded-lg border-slate-200/80 bg-card/90 px-2.5 text-[11px]'
              )}
              onClick={handleChooseEvidencePack}
              disabled={!datasetId}
              title={datasetId ? '导入 Evidence Pack JSON' : '请先选择数据集'}
            >
              <Upload className="w-3.5 h-3.5" />
              导入 Evidence Pack
            </Button>
            <Button
              size="sm"
              className={cn(
                'gap-2',
                dense && 'h-8 rounded-lg px-2.5 text-[11px]'
              )}
              onClick={() => setIsCreating(true)}
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
              dense ? 'left-2.5 h-3.5 w-3.5' : 'left-3 h-4 w-4'
            )}
          />
          <Input
            type="text"
            placeholder="搜索问题、关键词或标签..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={cn(
              dense
                ? 'h-9 rounded-xl border-slate-200/80 bg-card/95 pl-8 text-[13px]'
                : 'pl-10'
            )}
          />
        </div>

        <div
          className={cn(
            'flex items-center justify-start gap-3',
            dense ? 'mt-2.5' : 'mt-3'
          )}
        >
          <Button
            size="sm"
            variant={goldenOnly ? 'default' : 'outline'}
            className={cn(
              'gap-2',
              goldenOnly &&
                'bg-amber-500/15 text-amber-700 hover:bg-amber-500/20',
              dense &&
                'h-8 rounded-lg border-slate-200/80 bg-card/90 px-2.5 text-[11px]'
            )}
            onClick={() => {
              setGoldenOnly((v) => !v)
              setSelectedCaseIds(new Set())
            }}
            disabled={!datasetId}
            title={
              datasetId ? '只显示纳入 Golden 评测集的样本' : '请先选择数据集'
            }
          >
            <Star
              className="w-3.5 h-3.5"
              fill={goldenOnly ? 'currentColor' : 'none'}
            />
            只看 Golden
          </Button>
        </div>
      </div>

      <Dialog open={isCreating} onOpenChange={setIsCreating}>
        <DialogContent
          className={cn(
            'max-w-2xl',
            dense && 'max-h-[min(82vh,720px)] overflow-y-auto'
          )}
        >
          <DialogHeader>
            <DialogTitle>新增标准问答</DialogTitle>
          </DialogHeader>

          <div className={cn(dense ? 'space-y-2.5' : 'space-y-3')}>
            <div>
              <div
                className={cn(
                  'block font-medium text-muted-foreground',
                  dense ? 'mb-1 text-[11px]' : 'mb-1 text-xs'
                )}
              >
                标准问题 *
              </div>
              <Textarea
                value={newQuestion}
                onChange={(e) => setNewQuestion(e.target.value)}
                placeholder="输入用于评估 RAG 的标准问题..."
                className={cn(
                  'resize-none',
                  dense
                    ? 'min-h-[72px] rounded-xl border-slate-200/80 bg-card/95 text-[13px]'
                    : 'min-h-[72px]'
                )}
              />
            </div>
            <div>
              <div
                className={cn(
                  'block font-medium text-muted-foreground',
                  dense ? 'mb-1 text-[11px]' : 'mb-1 text-xs'
                )}
              >
                标准答案（推荐）
              </div>
              <Textarea
                value={newExpectedAnswer}
                onChange={(e) => setNewExpectedAnswer(e.target.value)}
                placeholder="输入可比对的标准答案..."
                className={cn(
                  'resize-none',
                  dense
                    ? 'min-h-[72px] rounded-xl border-slate-200/80 bg-card/95 text-[13px]'
                    : 'min-h-[72px]'
                )}
              />
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                className={cn(dense && 'h-8 rounded-lg px-2.5 text-[11px]')}
                onClick={() => detachPromise(handleCreate())}
                disabled={evidenceLoading || !datasetId || !newQuestion.trim()}
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
                className={cn(
                  dense &&
                    'h-8 rounded-lg border-slate-200/80 bg-card/90 px-2.5 text-[11px]'
                )}
                onClick={() => {
                  setIsCreating(false)
                  setNewQuestion('')
                  setNewExpectedAnswer('')
                }}
              >
                取消
              </Button>
            </div>
            <div
              className={cn(
                'rounded-xl border border-amber-200/80 bg-amber-50/70 px-3 py-2 text-muted-foreground',
                dense ? 'text-[11px] leading-5' : 'text-[11px]'
              )}
            >
              提示：后端要求每个用例必须提供至少 1 条{' '}
              <span className="font-mono">reference_sources</span>。
              点击“检索并选择标准证据”或“导入 Evidence Pack”选择 Ground Truth
              证据引用后再创建。
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={evidenceDialogOpen} onOpenChange={setEvidenceDialogOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>标准证据选择 → Golden 评测样本</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0 truncate">
                  dataset_id:{' '}
                  <span className="font-mono text-foreground/80">
                    {evidenceDatasetId || '-'}
                  </span>
                </div>
                <div className="text-[11px]">
                  citations:{' '}
                  <span className="font-mono text-foreground/80">
                    {evidenceCitations.length}
                  </span>
                </div>
              </div>
              {evidencePack?.exported_at && (
                <div className="mt-2 text-[11px]">
                  exported_at:{' '}
                  <span className="font-mono text-foreground/80">
                    {String(evidencePack.exported_at)}
                  </span>
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">
                  标准问题
                </div>
                <Textarea
                  value={evidenceQuestion}
                  onChange={(e) => setEvidenceQuestion(e.target.value)}
                  placeholder="问题（将写入 Golden 评测样本）"
                  className="min-h-[84px] resize-none"
                />
              </div>
              <div>
                <div className="text-xs font-medium text-muted-foreground mb-1">
                  标准答案（推荐）
                </div>
                <Textarea
                  value={evidenceExpectedAnswer}
                  onChange={(e) => setEvidenceExpectedAnswer(e.target.value)}
                  placeholder="可选：标准答案"
                  className="min-h-[84px] resize-none"
                />
              </div>
            </div>

            <div className="rounded-lg border border-border overflow-hidden">
              <div className="px-3 py-2 border-b border-border bg-card flex items-center justify-between">
                <div className="text-xs font-semibold text-foreground">
                  选择标准证据（reference_sources）
                </div>
                <div className="text-[11px] text-muted-foreground">
                  已选 {evidenceSelectedChunkIds.size} /{' '}
                  {evidenceCitations.length}
                </div>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {(evidenceCitations || []).map((c: any, idx: number) => {
                  const chunkId = String(c?.chunk_id || '')
                  const checked =
                    !!chunkId && evidenceSelectedChunkIds.has(chunkId)
                  const label = String(
                    c?.document_name || c?.document_id || 'Unknown'
                  )
                  const snippet = String(c?.chunk_content || '').slice(0, 180)
                  return (
                    <div
                      key={`${chunkId || idx}`}
                      className={cn(
                        'flex items-start gap-3 px-3 py-2 border-b border-border/60 cursor-pointer hover:bg-muted/30',
                        !chunkId && 'opacity-50 cursor-not-allowed'
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 rounded border-border"
                        disabled={!chunkId}
                        checked={checked}
                        onChange={(e) => {
                          const next = new Set(evidenceSelectedChunkIds)
                          if (e.target.checked) next.add(chunkId)
                          else next.delete(chunkId)
                          setEvidenceSelectedChunkIds(next)
                        }}
                      />
                      <div className="min-w-0">
                        <div
                          className="text-xs font-medium text-foreground truncate"
                          title={label}
                        >
                          #{idx + 1} {label}
                        </div>
                        <div className="text-[11px] text-muted-foreground mt-1 line-clamp-2">
                          “{snippet}
                          {snippet.length >= 180 ? '…' : ''}”
                        </div>
                        <div className="mt-1 text-[11px] text-muted-foreground flex flex-wrap gap-2">
                          {c?.page_number ? (
                            <span>p.{String(c.page_number)}</span>
                          ) : null}
                          {chunkId ? (
                            <span className="font-mono">
                              chunk:{chunkId.slice(0, 8)}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="flex items-center justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setEvidenceDialogOpen(false)}
                disabled={evidenceCreating}
              >
                取消
              </Button>
              <Button
                onClick={() =>
                  detachPromise(handleCreateCaseFromEvidencePack())
                }
                disabled={evidenceCreating}
              >
                {evidenceCreating ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin motion-reduce:animate-none" />
                    创建中…
                  </>
                ) : (
                  '创建 Golden 样本'
                )}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 用例列表 */}
      <div className="flex-1 overflow-y-auto overscroll-contain custom-scrollbar">
        {caseListContent}
      </div>

      {/* 底部统计 */}
      {filteredCases.length > 0 || selectedCaseIds.size > 0 ? (
        <div
          className={cn(
            'border-t',
            dense
              ? 'border-slate-200/80 bg-[#fffef9] px-3 py-2.5'
              : 'border-border bg-muted/30 p-3'
          )}
        >
          <div
            className={cn(
              'text-center text-muted-foreground',
              dense ? 'text-[11px]' : 'text-xs'
            )}
          >
            已显示 {filteredCases.length} 个测试用例
            {selectedCaseIds.size > 0 && ` · 已选择 ${selectedCaseIds.size} 个`}
          </div>
        </div>
      ) : null}
    </div>
  )
}
