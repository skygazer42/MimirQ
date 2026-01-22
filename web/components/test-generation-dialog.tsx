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

import { useState, useEffect } from 'react'
import { evaluationApi, documentApi, chatApi, datasetApi } from '@/lib/api-client'
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
import {
  X,
  Sparkles,
  Loader2,
  FileText,
  MessageSquare,
  CheckCircle2,
  AlertCircle,
  Settings,
  ChevronRight,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

interface TestGenerationDialogProps {
  open: boolean
  onClose: () => void
  onGenerated?: () => void
}

type SourceType = 'documents' | 'conversations'
type Step = 'select_source' | 'configure' | 'preview'

export function TestGenerationDialog({
  open,
  onClose,
  onGenerated,
}: TestGenerationDialogProps) {
  const [step, setStep] = useState<Step>('select_source')
  const [sourceType, setSourceType] = useState<SourceType>('documents')

  // 数据加载状态
  const [documents, setDocuments] = useState<Document[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [isLoadingData, setIsLoadingData] = useState(false)

  // 选择状态
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<Set<string>>(new Set())
  const [selectedConversationIds, setSelectedConversationIds] = useState<Set<string>>(new Set())

  // 配置参数
  const [numQuestions, setNumQuestions] = useState(10)
  const [questionTypes, setQuestionTypes] = useState<string[]>(['factual', 'reasoning'])
  const [qualityThreshold, setQualityThreshold] = useState(0.7)
  const [autoSave, setAutoSave] = useState(true)

  // 生成状态
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedQuestions, setGeneratedQuestions] = useState<GeneratedQuestion[]>([])
  const [error, setError] = useState<string>('')

  // 加载数据
  useEffect(() => {
    if (!open) return

    const loadData = async () => {
      setIsLoadingData(true)
      try {
        if (sourceType === 'documents') {
          const [docsResult, datasetsResult] = await Promise.all([
            documentApi.list({ limit: 100, status: 'completed' }),
            datasetApi.list({ limit: 50 }),
          ])
          setDocuments(docsResult.items)
          setDatasets(datasetsResult.items)
        } else {
          const convsResult = await chatApi.listConversations({ limit: 100 })
          setConversations(convsResult.items || [])
        }
      } catch (error) {
        console.error('加载数据失败:', error)
        toast.error('加载数据失败')
      } finally {
        setIsLoadingData(false)
      }
    }

    loadData()
  }, [open, sourceType])

  // 重置状态
  const handleClose = () => {
    setStep('select_source')
    setSelectedDocumentIds(new Set())
    setSelectedConversationIds(new Set())
    setGeneratedQuestions([])
    setError('')
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
        setStep('preview')
        toast.success(`成功生成 ${result.generated_questions.length} 个问题`)
      } else {
        setError(result.error_message || '生成失败')
        toast.error('生成失败')
      }
    } catch (error: any) {
      console.error('生成问题失败:', error)
      setError(error.message || '生成失败')
      toast.error('生成问题失败')
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-card rounded-2xl border border-border shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* 头部 */}
        <div className="flex items-center justify-between p-6 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-br from-sky-500 to-purple-600 rounded-lg">
              <Sparkles className="w-5 h-5 text-background dark:text-foreground" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                AI 生成测试问题
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {step === 'select_source' && '选择生成来源'}
                {step === 'configure' && '配置生成参数'}
                {step === 'preview' && '预览生成结果'}
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 步骤 1: 选择来源 */}
        {step === 'select_source' && (
          <div className="flex-1 overflow-y-auto p-6">
            <div className="space-y-4">
              {/* 来源类型选择 */}
              <div className="grid grid-cols-2 gap-4">
                <button
                  onClick={() => setSourceType('documents')}
                  className={cn(
                    'p-4 rounded-xl border-2 transition text-left',
                    sourceType === 'documents'
                      ? 'border-sky-500 bg-sky-50 dark:bg-sky-900/20'
                      : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'
                  )}
                >
                  <FileText className="w-6 h-6 mb-2 text-sky-600" />
                  <div className="font-medium text-foreground mb-1">
                    从文档生成
                  </div>
                  <div className="text-xs text-slate-600 dark:text-slate-400">
                    基于知识库文档内容生成多样化测试问题
                  </div>
                </button>

                <button
                  onClick={() => setSourceType('conversations')}
                  className={cn(
                    'p-4 rounded-xl border-2 transition text-left',
                    sourceType === 'conversations'
                      ? 'border-sky-500 bg-sky-50 dark:bg-sky-900/20'
                      : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'
                  )}
                >
                  <MessageSquare className="w-6 h-6 mb-2 text-purple-600" />
                  <div className="font-medium text-foreground mb-1">
                    从对话生成
                  </div>
                  <div className="text-xs text-slate-600 dark:text-slate-400">
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
                      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                        选择知识库（可选）
                      </label>
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
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                      选择文档
                    </label>
                    <div className="border border-slate-200 dark:border-slate-700 rounded-lg max-h-64 overflow-y-auto">
                      {isLoadingData ? (
                        <div className="flex items-center justify-center py-8">
                          <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                        </div>
                      ) : documents.length === 0 ? (
                        <div className="text-center py-8 text-slate-500 text-sm">
                          暂无可用文档
                        </div>
                      ) : (
                        documents.map((doc) => (
                          <label
                            key={doc.id}
                            className="flex items-center gap-3 p-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer border-b border-slate-100 dark:border-slate-800 last:border-0"
                          >
                            <input
                              type="checkbox"
                              checked={selectedDocumentIds.has(doc.id)}
                              onChange={() => toggleDocument(doc.id)}
                              className="w-4 h-4 rounded"
                            />
                            <FileText className="w-4 h-4 text-slate-400" />
                            <span className="flex-1 text-sm text-slate-700 dark:text-slate-300 truncate">
                              {doc.filename}
                            </span>
                            <span className="text-xs text-slate-500">
                              {doc.chunk_count} 切片
                            </span>
                          </label>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* 对话选择 */}
              {sourceType === 'conversations' && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    选择对话
                  </label>
                  <div className="border border-slate-200 dark:border-slate-700 rounded-lg max-h-64 overflow-y-auto">
                    {isLoadingData ? (
                      <div className="flex items-center justify-center py-8">
                        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                      </div>
                    ) : conversations.length === 0 ? (
                      <div className="text-center py-8 text-slate-500 text-sm">
                        暂无对话记录
                      </div>
                    ) : (
                      conversations.map((conv) => (
                        <label
                          key={conv.id}
                          className="flex items-center gap-3 p-3 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer border-b border-slate-100 dark:border-slate-800 last:border-0"
                        >
                          <input
                            type="checkbox"
                            checked={selectedConversationIds.has(conv.id)}
                            onChange={() => toggleConversation(conv.id)}
                            className="w-4 h-4 rounded"
                          />
                          <MessageSquare className="w-4 h-4 text-slate-400" />
                          <span className="flex-1 text-sm text-slate-700 dark:text-slate-300 truncate">
                            {conv.title || `对话 ${conv.id.slice(0, 8)}`}
                          </span>
                          <span className="text-xs text-slate-500">
                            {conv.message_count} 消息
                          </span>
                        </label>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 步骤 2: 配置参数 */}
        {step === 'configure' && (
          <div className="flex-1 overflow-y-auto p-6">
            <div className="space-y-6">
              {/* 生成数量 */}
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
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
                <div className="flex justify-between text-xs text-slate-500 mt-1">
                  <span>1</span>
                  <span>50</span>
                </div>
              </div>

              {/* 问题类型（仅文档） */}
              {sourceType === 'documents' && (
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    问题类型
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {[
                      { key: 'factual', label: '事实型', desc: '询问具体信息' },
                      { key: 'reasoning', label: '推理型', desc: '需要理解推理' },
                      { key: 'comparison', label: '对比型', desc: '比较不同概念' },
                    ].map((type) => (
                      <button
                        key={type.key}
                        onClick={() => toggleQuestionType(type.key)}
                        className={cn(
                          'px-4 py-2 rounded-lg border-2 transition text-sm',
                          questionTypes.includes(type.key)
                            ? 'border-sky-500 bg-sky-50 dark:bg-sky-900/20 text-sky-700 dark:text-sky-300'
                            : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400'
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
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
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
                  <div className="flex justify-between text-xs text-slate-500 mt-1">
                    <span>宽松 (0.0)</span>
                    <span>严格 (1.0)</span>
                  </div>
                </div>
              )}

              {/* 自动保存 */}
              <div className="flex items-center justify-between p-4 rounded-lg bg-muted/40">
                <div>
                  <div className="text-sm font-medium text-slate-700 dark:text-slate-300">
                    自动保存为测试用例
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                    生成后自动保存到用例库，可直接运行测试
                  </div>
                </div>
                <Switch checked={autoSave} onCheckedChange={setAutoSave} />
              </div>

              {/* 错误提示 */}
              {error && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                  <AlertCircle className="w-4 h-4 text-red-600 mt-0.5" />
                  <div className="text-sm text-red-600 dark:text-red-400">{error}</div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 步骤 3: 预览结果 */}
        {step === 'preview' && (
          <div className="flex-1 overflow-y-auto p-6">
            <div className="space-y-4">
              {generatedQuestions.length === 0 ? (
                <div className="text-center py-8 text-slate-500">
                  没有生成问题
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                    <CheckCircle2 className="w-4 h-4 text-green-600" />
                    成功生成 {generatedQuestions.length} 个问题
                    {autoSave && '（已自动保存）'}
                  </div>

                  {/* 问题列表 */}
                  <div className="space-y-3">
                    {generatedQuestions.map((q, index) => (
	                      <div
	                        key={index}
	                        className="p-4 rounded-lg border border-border bg-card"
	                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-slate-800 dark:text-slate-200 mb-1">
                              {index + 1}. {q.question}
                            </div>
                            {q.expected_answer && (
                              <div className="text-xs text-slate-600 dark:text-slate-400 mt-2">
                                <span className="font-medium">参考答案:</span> {q.expected_answer}
                              </div>
                            )}
                            {q.metadata?.question_type && (
                              <span className="inline-block mt-2 px-2 py-0.5 rounded-full bg-sky-100 dark:bg-sky-900/30 text-[10px] text-sky-700 dark:text-sky-300">
                                {q.metadata.question_type}
                              </span>
                            )}
                          </div>
                          <button
                            onClick={() => handleDeleteQuestion(index)}
                            className="text-slate-400 hover:text-red-600 transition"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* 底部操作栏 */}
        <div className="flex items-center justify-between p-6 border-t border-slate-200 dark:border-slate-800">
          <div className="text-xs text-slate-500">
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
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
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
      </div>
    </div>
  )
}
