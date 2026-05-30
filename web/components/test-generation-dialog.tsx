/**
 * AI 生成测试问题对话框
 * 
 * 功能：
 * - 选择生成来源（文档或对话）
 * - 配置生成参数
 * - 预览生成结果
 * - 批量编辑和保存
 */

'use client'

import { useQuery } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { evaluationApi, documentApi, chatApi, datasetApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import type {
  GeneratedQuestion,
  TestGenFromDocsRequest,
  TestGenFromConversationsRequest,
  Document,
  Conversation,
  Dataset,
} from '@/types'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Sparkles, Loader2, FileText, MessageSquare, CheckCircle2, AlertCircle, ChevronRight, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'

interface TestGenerationDialogProps {
  open: boolean
  onClose: () => void
  onGenerated?: () => void
  initialSourceType?: 'documents' | 'conversations'
  initialDatasetId?: string
  initialDocumentIds?: string[]
}

type SourceType = 'documents' | 'conversations'
type Step = 'select_source' | 'configure' | 'preview'

const TEST_GEN_DOCUMENT_PARAMS = { limit: 100, status: 'completed' as const }
const TEST_GEN_DATASET_PARAMS = { limit: 50 }
const TEST_GEN_CONVERSATION_PARAMS = { limit: 100 }

const EMPTY_DOCUMENTS: Document[] = []
const EMPTY_CONVERSATIONS: Conversation[] = []
const EMPTY_DATASETS: Dataset[] = []

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function getQuestionType(metadata: unknown): string | null {
  if (!isRecord(metadata)) return null
  return typeof metadata.question_type === 'string' && metadata.question_type.trim()
    ? metadata.question_type
    : null
}

export function TestGenerationDialog({
  open,
  onClose,
  onGenerated,
  initialSourceType,
  initialDatasetId,
  initialDocumentIds,
}: Readonly<TestGenerationDialogProps>) {
  const [step, setStep] = useState<Step>('select_source')
  const [sourceType, setSourceType] = useState<SourceType>('documents')

  // 选择状态
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(new Set())
  const [selectedConversationIds, setSelectedConversationIds] = useState<Set<string>>(new Set())

  // 配置参数
  const [numQuestions, setNumQuestions] = useState(10)
  const [questionTypes, setQuestionTypes] = useState<string[]>(['factual', 'multi_hop', 'comparison'])
  const [qualityThreshold, setQualityThreshold] = useState(0.7)
  const [autoSave, setAutoSave] = useState(true)

  // 生成状态
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedQuestions, setGeneratedQuestions] = useState<GeneratedQuestion[]>([])
  const [savedCaseIds, setSavedCaseIds] = useState<string[]>([])
  const [error, setError] = useState<string>('')

  const documentsQuery = useQuery({
    queryKey: queryKeys.documents.list(TEST_GEN_DOCUMENT_PARAMS),
    enabled: open && sourceType === 'documents',
    queryFn: () => documentApi.list(TEST_GEN_DOCUMENT_PARAMS),
  })
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.list(TEST_GEN_DATASET_PARAMS),
    enabled: open && sourceType === 'documents',
    queryFn: () => datasetApi.list(TEST_GEN_DATASET_PARAMS),
  })
  const conversationsQuery = useQuery({
    queryKey: queryKeys.chat.conversations(TEST_GEN_CONVERSATION_PARAMS),
    enabled: open && sourceType === 'conversations',
    queryFn: () => chatApi.listConversations(TEST_GEN_CONVERSATION_PARAMS),
  })

  const documents = documentsQuery.data?.items ?? EMPTY_DOCUMENTS
  const datasets = datasetsQuery.data?.items ?? EMPTY_DATASETS
  const conversations = conversationsQuery.data?.items ?? EMPTY_CONVERSATIONS
  const isLoadingData =
    (sourceType === 'documents' && (documentsQuery.isLoading || datasetsQuery.isLoading)) ||
    (sourceType === 'conversations' && conversationsQuery.isLoading)

  useEffect(() => {
    if (!open) return

    // Preselect support (enterprise workflow: chunk -> ingest -> generate tests).
    if (initialDatasetId) setSelectedDatasetId(initialDatasetId)
    if (initialDocumentIds?.length) {
      setSourceType('documents')
      setSelectedDocumentIds(new Set(initialDocumentIds))
      setStep('configure')
    } else if (initialSourceType) {
      setSourceType(initialSourceType)
    }
  }, [open, initialSourceType, initialDatasetId, initialDocumentIds])

  useEffect(() => {
    const error =
      sourceType === 'documents'
        ? (documentsQuery.error || datasetsQuery.error)
        : conversationsQuery.error
    if (!error) return
    console.error('加载数据失败:', error)
    toast.error(formatApiError(error, '加载数据失败'))
  }, [
    conversationsQuery.error,
    datasetsQuery.error,
    documentsQuery.error,
    sourceType,
  ])

  const resetState = () => {
    setStep('select_source')
    setSelectedDocumentIds(new Set())
    setSelectedConversationIds(new Set())
    setGeneratedQuestions([])
    setSavedCaseIds([])
    setError('')
  }

  useEffect(() => {
    if (!open) resetState()
  }, [open])

  // 关闭对话框
  const handleClose = () => {
    onClose()
  }

  // 切换文档选择
  const toggleDocument = (docId: string) => {
    const newSet = new Set(selectedDocumentIds)
    if (newSet.has(docId)) {
      newSet.delete(docId)
    } else {
      newSet.add(docId)
    }
    setSelectedDocumentIds(newSet)
  }

  // 切换对话选择
  const toggleConversation = (convId: string) => {
    const newSet = new Set(selectedConversationIds)
    if (newSet.has(convId)) {
      newSet.delete(convId)
    } else {
      newSet.add(convId)
    }
    setSelectedConversationIds(newSet)
  }

  // 切换问题类型
  const toggleQuestionType = (type: string) => {
    if (questionTypes.includes(type)) {
      setQuestionTypes(questionTypes.filter((t) => t !== type))
    } else {
      setQuestionTypes([...questionTypes, type])
    }
  }

  // 生成问题
  const handleGenerate = async () => {
    setIsGenerating(true)
    setError('')

    try {
      let result

      if (sourceType === 'documents') {
        if (selectedDocumentIds.size === 0 && !selectedDatasetId) {
          toast.error('请至少选择一个文档或知识库')
          return
        }

        const params: TestGenFromDocsRequest = {
          dataset_id: selectedDatasetId || undefined,
          document_ids: Array.from(selectedDocumentIds),
          num_questions: numQuestions,
          question_types: questionTypes,
          auto_save_as_cases: autoSave,
        }

        result = await evaluationApi.generateFromDocuments(params)
      } else {
        if (selectedConversationIds.size === 0) {
          toast.error('请至少选择一个对话')
          return
        }

        const params: TestGenFromConversationsRequest = {
          conversation_ids: Array.from(selectedConversationIds),
          num_questions: numQuestions,
          quality_threshold: qualityThreshold,
          auto_save_as_cases: autoSave,
        }

        result = await evaluationApi.generateFromConversations(params)
      }

      if (result.status === 'completed') {
        setGeneratedQuestions(result.generated_questions)
        setSavedCaseIds(result.saved_case_ids || [])
        setStep('preview')
        if (autoSave) {
          toast.success(`成功生成 ${result.generated_questions.length} 个问题，已保存 ${result.saved_case_ids?.length || 0} 个用例`)
        } else {
          toast.success(`成功生成 ${result.generated_questions.length} 个问题`)
        }
      } else {
        setError(result.error_message || '生成失败')
        toast.error('生成失败')
      }
    } catch (error: any) {
      console.error('生成问题失败:', error)
      const msg = formatApiError(error, '生成问题失败')
      setError(msg)
      toast.error(msg)
    } finally {
      setIsGenerating(false)
    }
  }

  // 删除生成的问题
  const handleDeleteQuestion = (index: number) => {
    setGeneratedQuestions(generatedQuestions.filter((_, i) => i !== index))
  }

  // 完成并关闭
  const handleFinish = () => {
    onGenerated?.()
    handleClose()
  }

  if (!open) return null

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) handleClose()
      }}
    >
      <DialogContent className="flex flex-col max-w-4xl w-full max-h-[90vh] p-0 gap-0 bg-card overflow-hidden sm:rounded-2xl">
        {/* 头部 */}
        <div className="flex items-center justify-between p-6 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10 text-primary border border-border/60">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <DialogTitle className="text-lg font-semibold text-foreground">AI 生成测试问题</DialogTitle>
              <p className="text-xs text-muted-foreground">
                {step === 'select_source' && '选择生成来源'}
                {step === 'configure' && '配置生成参数'}
                {step === 'preview' && '预览生成结果'}
              </p>
            </div>
          </div>
        </div>

        {/* 步骤 1: 选择来源 */}
        {step === 'select_source' && (
          <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-6">
            <div className="space-y-4">
              {/* 来源类型选择 */}
              <div className="grid grid-cols-2 gap-4">
                <button
                  onClick={() => setSourceType('documents')}
	                  className={cn(
	                    'p-4 rounded-xl border-2 transition text-left',
	                    sourceType === 'documents'
	                      ? 'border-info bg-info/10'
	                      : 'border-border/60 hover:border-border'
	                  )}
	                >
                  <FileText className="w-6 h-6 mb-2 text-info" />
                  <div className="font-medium text-foreground mb-1">
                    从文档生成
                  </div>
	                  <div className="text-xs text-muted-foreground">
	                    基于知识库文档内容生成多样化测试问题
	                  </div>
                </button>

                <button
                  onClick={() => setSourceType('conversations')}
	                  className={cn(
	                    'p-4 rounded-xl border-2 transition text-left',
	                    sourceType === 'conversations'
	                      ? 'border-info bg-info/10'
	                      : 'border-border/60 hover:border-border'
	                  )}
	                >
                  <MessageSquare className="w-6 h-6 mb-2 text-purple-600" />
                  <div className="font-medium text-foreground mb-1">
                    从对话生成
                  </div>
	                  <div className="text-xs text-muted-foreground">
	                    从真实对话历史中提炼高质量问题
	                  </div>
                </button>
              </div>

              {/* 文档选择 */}
              {sourceType === 'documents' && (
                <div className="space-y-3">
                  {/* 知识库选择 */}
                  {datasets.length > 0 && (
                    <div>
                      <div className="block text-sm font-medium text-foreground/80 mb-2">
                        选择知识库（可选）
                      </div>
                      <select
                        value={selectedDatasetId}
                        onChange={(e) => setSelectedDatasetId(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg border border-input bg-background text-sm text-foreground shadow-sm"
                      >
                        <option value="">所有知识库</option>
                        {datasets.map((ds) => (
                          <option key={ds.id} value={ds.id}>
                            {ds.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* 文档列表 */}
                  <div>
                    <div className="block text-sm font-medium text-foreground/80 mb-2">
                      选择文档
                    </div>
                    <div className="border border-border/60 rounded-lg max-h-64 overflow-y-auto overscroll-contain no-scrollbar">
                      {(() => {
    if (isLoadingData) {
        return (<div className="flex items-center justify-center py-8">
                          <Loader2 className="w-6 h-6 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                        </div>);
    }
    else if (documents.length === 0) {
            return (<div className="text-center py-8 text-muted-foreground text-sm">
                          暂无可用文档
                        </div>);
        }
        else {
            return (documents.map((doc) => (<label key={doc.id} className="flex items-center gap-3 p-3 hover:bg-muted/30 cursor-pointer border-b border-border/60 last:border-0">
                            <input type="checkbox" checked={selectedDocumentIds.has(doc.id)} onChange={() => toggleDocument(doc.id)} className="w-4 h-4 rounded"/>
                            <FileText className="w-4 h-4 text-muted-foreground"/>
                            <span className="flex-1 text-sm text-foreground truncate">
                              {doc.filename}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {doc.chunk_count} 切片
                            </span>
                          </label>)));
        }
})()}
                    </div>
                  </div>
                </div>
              )}

              {/* 对话选择 */}
              {sourceType === 'conversations' && (
                <div>
                  <div className="block text-sm font-medium text-foreground/80 mb-2">
                    选择对话
                  </div>
                  <div className="border border-border/60 rounded-lg max-h-64 overflow-y-auto overscroll-contain no-scrollbar">
                    {(() => {
    if (isLoadingData) {
        return (<div className="flex items-center justify-center py-8">
                        <Loader2 className="w-6 h-6 animate-spin motion-reduce:animate-none text-muted-foreground"/>
                      </div>);
    }
    else if (conversations.length === 0) {
            return (<div className="text-center py-8 text-muted-foreground text-sm">
                        暂无对话记录
                      </div>);
        }
        else {
            return (conversations.map((conv) => (<label key={conv.id} className="flex items-center gap-3 p-3 hover:bg-muted/30 cursor-pointer border-b border-border/60 last:border-0">
                          <input type="checkbox" checked={selectedConversationIds.has(conv.id)} onChange={() => toggleConversation(conv.id)} className="w-4 h-4 rounded"/>
                          <MessageSquare className="w-4 h-4 text-muted-foreground"/>
                          <span className="flex-1 text-sm text-foreground truncate">
                            {conv.title || `对话 ${conv.id.slice(0, 8)}`}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {conv.message_count} 消息
                          </span>
                        </label>)));
        }
})()}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 步骤 2: 配置参数 */}
        {step === 'configure' && (
          <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-6">
            <div className="space-y-6">
              {/* 生成数量 */}
              <div>
                <label className="block text-sm font-medium text-foreground/80 mb-2">
                  生成数量: {numQuestions}
                </label>
                <input
                  type="range"
                  min="1"
                  max="50"
                  value={numQuestions}
                  onChange={(e) => setNumQuestions(Number(e.target.value))}
                  className="w-full"
                />
                <div className="flex justify-between text-xs text-muted-foreground mt-1">
                  <span>1</span>
                  <span>50</span>
                </div>
              </div>

              {/* 问题类型（仅文档） */}
              {sourceType === 'documents' && (
                <div>
                  <div className="block text-sm font-medium text-foreground/80 mb-2">
                    问题类型
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { key: 'factual', label: '事实型', desc: '询问具体信息' },
                      { key: 'multi_hop', label: '多跳/推理', desc: '组合 2+ 信息推理' },
                      { key: 'comparison', label: '对比型', desc: '比较不同概念' },
                      { key: 'conditional', label: '条件型', desc: '如果/当…会怎样' },
                      { key: 'unanswerable', label: '不可答/拒答', desc: '文档中无法回答' },
                    ].map((type) => (
                      <button
                        key={type.key}
                        onClick={() => toggleQuestionType(type.key)}
                        className={cn(
                          'px-4 py-2 rounded-lg border-2 transition text-sm',
                          questionTypes.includes(type.key)
                            ? 'border-info bg-info/10 text-info'
                            : 'border-border/60 text-muted-foreground hover:border-border'
                        )}
                      >
                        <div className="font-medium">{type.label}</div>
                        <div className="text-xs opacity-75">{type.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 质量阈值（仅对话） */}
              {sourceType === 'conversations' && (
                <div>
                  <label className="block text-sm font-medium text-foreground/80 mb-2">
                    质量阈值: {qualityThreshold.toFixed(1)}
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    value={qualityThreshold}
                    onChange={(e) => setQualityThreshold(Number(e.target.value))}
                    className="w-full"
                  />
                  <div className="flex justify-between text-xs text-muted-foreground mt-1">
                    <span>宽松 (0.0)</span>
                    <span>严格 (1.0)</span>
                  </div>
                </div>
              )}

              {/* 自动保存 */}
              <div className="flex items-center justify-between p-4 rounded-lg bg-muted/40">
                <div>
                  <div className="text-sm font-medium text-foreground/80">
                    自动保存为测试用例
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    生成后自动保存到用例库，可直接运行测试
                  </div>
                </div>
                <Switch checked={autoSave} onCheckedChange={setAutoSave} />
              </div>

              {/* 错误提示 */}
              {error && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20">
                  <AlertCircle className="w-4 h-4 text-destructive mt-0.5" />
                  <div className="text-sm text-destructive">{error}</div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 步骤 3: 预览结果 */}
        {step === 'preview' && (
          <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-6">
            <div className="space-y-4">
              {generatedQuestions.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  没有生成问题
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <CheckCircle2 className="w-4 h-4 text-success" />
                    成功生成 {generatedQuestions.length} 个问题
                    {autoSave && `（已自动保存 ${savedCaseIds.length} 个用例）`}
                  </div>

                  {/* 问题列表 */}
                  <div className="space-y-3">
                    {generatedQuestions.map((q, index) => {
                      const questionType = getQuestionType(q.metadata)
                      return (
	                      <div
	                        key={`${q.question}-${q.expected_answer || ''}-${questionType || ''}`}
	                        className="p-4 rounded-lg border border-border bg-card"
	                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-foreground mb-1">
                              {index + 1}. {q.question}
                            </div>
                            {q.expected_answer && (
                              <div className="text-xs text-muted-foreground mt-2">
                                <span className="font-medium">参考答案:</span> {q.expected_answer}
                              </div>
                            )}
                            {questionType && (
                              <span className="inline-block mt-2 px-2 py-0.5 rounded-full bg-info/10 text-[11px] text-info">
                                {questionType}
                              </span>
                            )}
	                          </div>
	                          <button
                            type="button"
                            onClick={() => handleDeleteQuestion(index)}
                            aria-label={`删除问题 ${index + 1}`}
                            className="rounded-md p-1 text-muted-foreground hover:text-destructive transition-colors duration-150 motion-reduce:transition-none focus-ring"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    )})}
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* 底部操作栏 */}
        <div className="flex items-center justify-between p-6 border-t border-border">
          <div className="text-xs text-muted-foreground">
            {step === 'select_source' && '第 1 步，共 3 步'}
            {step === 'configure' && '第 2 步，共 3 步'}
            {step === 'preview' && '第 3 步，共 3 步'}
          </div>
          <div className="flex items-center gap-2">
            {step === 'select_source' && (
              <Button
                onClick={() => setStep('configure')}
                disabled={
                  (sourceType === 'documents' &&
                    selectedDocumentIds.size === 0 &&
                    !selectedDatasetId) ||
                  (sourceType === 'conversations' && selectedConversationIds.size === 0)
                }
              >
                下一步
                <ChevronRight className="w-4 h-4 ml-1" />
              </Button>
            )}

            {step === 'configure' && (
              <>
                <Button variant="outline" onClick={() => setStep('select_source')}>
                  上一步
                </Button>
                <Button onClick={handleGenerate} disabled={isGenerating}>
                  {isGenerating ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin motion-reduce:animate-none" />
                      生成中...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4 mr-2" />
                      开始生成
                    </>
                  )}
                </Button>
              </>
            )}

            {step === 'preview' && (
              <>
                <Button variant="outline" onClick={() => setStep('configure')}>
                  重新生成
                </Button>
                <Button onClick={handleFinish}>
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                  完成
                </Button>
              </>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
