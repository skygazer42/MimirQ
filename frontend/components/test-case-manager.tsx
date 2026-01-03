/**
 * 测试用例管理组件
 * 
 * 功能：
 * - 列表展示测试用例
 * - 搜索和筛选
 * - 编辑、删除操作
 * - 批量选择和操作
 */

'use client'

import { useState, useEffect } from 'react'
import { evaluationApi } from '@/lib/api-client'
import type { RegressionCase, RegressionCaseCreate } from '@/types'
import { Button } from '@/components/ui/button'
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
} from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

interface TestCaseManagerProps {
  onRunTests?: (caseIds: string[]) => void
  onCaseSelected?: (caseId: string | null) => void
}

export function TestCaseManager({
  onRunTests,
  onCaseSelected,
}: TestCaseManagerProps) {
  const [cases, setCases] = useState<RegressionCase[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCaseIds, setSelectedCaseIds] = useState<Set<string>>(new Set())
  const [selectedCase, setSelectedCase] = useState<RegressionCase | null>(null)

  // 创建用例的状态
  const [isCreating, setIsCreating] = useState(false)
  const [newQuestion, setNewQuestion] = useState('')
  const [newExpectedAnswer, setNewExpectedAnswer] = useState('')

  // 加载用例列表
  const loadCases = async () => {
    try {
      setIsLoading(true)
      const result = await evaluationApi.listRegressionCases({ limit: 100 })
      setCases(result.items)
    } catch (error) {
      console.error('加载测试用例失败:', error)
      toast.error('加载测试用例失败')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadCases()
  }, [])

  // 过滤用例
  const filteredCases = cases.filter((c) =>
    c.question.toLowerCase().includes(searchQuery.toLowerCase())
  )

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
    if (!confirm('确定删除这个测试用例吗？')) return

    try {
      await evaluationApi.deleteRegressionCase(caseId)
      toast.success('删除成功')
      await loadCases()
      if (selectedCase?.id === caseId) {
        setSelectedCase(null)
        onCaseSelected?.(null)
      }
    } catch (error) {
      console.error('删除失败:', error)
      toast.error('删除失败')
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedCaseIds.size === 0) return
    if (!confirm(`确定删除 ${selectedCaseIds.size} 个测试用例吗？`)) return

    try {
      await Promise.all(
        Array.from(selectedCaseIds).map((id) =>
          evaluationApi.deleteRegressionCase(id)
        )
      )
      toast.success('批量删除成功')
      setSelectedCaseIds(new Set())
      await loadCases()
    } catch (error) {
      console.error('批量删除失败:', error)
      toast.error('批量删除失败')
    }
  }

  // 创建用例
  const handleCreate = async () => {
    if (!newQuestion.trim()) {
      toast.error('请输入问题')
      return
    }

    try {
      const params: RegressionCaseCreate = {
        question: newQuestion,
        expected_answer: newExpectedAnswer || undefined,
        tags: ['manual_created'],
      }

      await evaluationApi.createRegressionCase(params)
      toast.success('创建成功')
      setNewQuestion('')
      setNewExpectedAnswer('')
      setIsCreating(false)
      await loadCases()
    } catch (error) {
      console.error('创建失败:', error)
      toast.error('创建失败')
    }
  }

  // 选择用例
  const handleSelectCase = (caseItem: RegressionCase) => {
    setSelectedCase(caseItem)
    onCaseSelected?.(caseItem.id)
  }

  // 运行选中的测试
  const handleRunSelected = () => {
    if (selectedCaseIds.size === 0) {
      toast.error('请先选择测试用例')
      return
    }
    onRunTests?.(Array.from(selectedCaseIds))
  }

  return (
    <div className="flex flex-col h-full">
      {/* 头部操作栏 */}
      <div className="p-4 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
            测试用例库
          </h3>
          <div className="flex items-center gap-2">
            {selectedCaseIds.size > 0 && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2"
                  onClick={handleRunSelected}
                >
                  运行选中 ({selectedCaseIds.size})
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2 text-red-600 hover:text-red-700"
                  onClick={handleBatchDelete}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  删除
                </Button>
              </>
            )}
            <Button
              size="sm"
              className="gap-2"
              onClick={() => setIsCreating(!isCreating)}
            >
              <Plus className="w-3.5 h-3.5" />
              新建
            </Button>
          </div>
        </div>

        {/* 搜索框 */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="搜索问题..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm"
          />
        </div>
      </div>

      {/* 创建表单 */}
      {isCreating && (
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50">
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                问题 *
              </label>
              <textarea
                value={newQuestion}
                onChange={(e) => setNewQuestion(e.target.value)}
                placeholder="输入测试问题..."
                className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm resize-none"
                rows={2}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                期望答案（可选）
              </label>
              <textarea
                value={newExpectedAnswer}
                onChange={(e) => setNewExpectedAnswer(e.target.value)}
                placeholder="输入期望答案..."
                className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 text-sm resize-none"
                rows={2}
              />
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={handleCreate}>
                保存
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setIsCreating(false)
                  setNewQuestion('')
                  setNewExpectedAnswer('')
                }}
              >
                取消
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 用例列表 */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        ) : filteredCases.length === 0 ? (
          <div className="text-center py-8 text-slate-500">
            {searchQuery ? '没有找到匹配的用例' : '暂无测试用例'}
          </div>
        ) : (
          <>
            {/* 全选框 */}
            {filteredCases.length > 0 && (
              <div className="px-4 py-2 border-b border-slate-100 dark:border-slate-800 flex items-center gap-2">
                <button
                  onClick={toggleSelectAll}
                  className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
                >
                  {selectedCaseIds.size === filteredCases.length ? (
                    <CheckSquare className="w-4 h-4" />
                  ) : (
                    <Square className="w-4 h-4" />
                  )}
                  全选
                </button>
              </div>
            )}

            {/* 用例卡片 */}
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {filteredCases.map((caseItem) => (
                <div
                  key={caseItem.id}
                  className={cn(
                    'p-4 hover:bg-slate-50 dark:hover:bg-slate-800/30 transition cursor-pointer',
                    selectedCase?.id === caseItem.id &&
                      'bg-indigo-50/60 dark:bg-indigo-900/10'
                  )}
                  onClick={() => handleSelectCase(caseItem)}
                >
                  <div className="flex items-start gap-3">
                    {/* 选择框 */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        toggleSelect(caseItem.id)
                      }}
                      className="mt-0.5"
                    >
                      {selectedCaseIds.has(caseItem.id) ? (
                        <CheckSquare className="w-4 h-4 text-indigo-600" />
                      ) : (
                        <Square className="w-4 h-4 text-slate-400" />
                      )}
                    </button>

                    {/* 内容 */}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-slate-800 dark:text-slate-200 mb-1 line-clamp-2">
                        {caseItem.question}
                      </div>

                      {caseItem.expected_answer && (
                        <div className="text-xs text-slate-600 dark:text-slate-400 mb-2 line-clamp-2">
                          期望: {caseItem.expected_answer}
                        </div>
                      )}

                      {/* 标签 */}
                      {caseItem.tags && caseItem.tags.length > 0 && (
                        <div className="flex items-center gap-1 flex-wrap mb-2">
                          {caseItem.tags.map((tag, idx) => (
                            <span
                              key={idx}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-[10px] text-slate-600 dark:text-slate-400"
                            >
                              <Tag className="w-2.5 h-2.5" />
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* 元信息 */}
                      <div className="flex items-center gap-3 text-[10px] text-slate-500">
                        <span className="flex items-center gap-1">
                          <Calendar className="w-3 h-3" />
                          {new Date(caseItem.created_at).toLocaleDateString()}
                        </span>
                        {caseItem.document_ids?.length > 0 && (
                          <span className="flex items-center gap-1">
                            <FileText className="w-3 h-3" />
                            {caseItem.document_ids.length} 文档
                          </span>
                        )}
                      </div>
                    </div>

                    {/* 删除按钮 */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(caseItem.id)
                      }}
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

      {/* 底部统计 */}
      <div className="p-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50">
        <div className="text-xs text-slate-500 text-center">
          共 {filteredCases.length} 个测试用例
          {selectedCaseIds.size > 0 && ` · 已选择 ${selectedCaseIds.size} 个`}
        </div>
      </div>
    </div>
  )
}

