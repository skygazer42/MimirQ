'use client'

import { useState, useCallback, useMemo, useEffect } from 'react'
import {
  Wrench,
  Sparkles,
  Check,
  Undo,
  TextCursorInput,
  Loader2,
  Info,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { pipelineApi, promptTemplateApi, PromptTemplate } from '@/lib/api-client'
import type { CleanPreviewRequest, LLMCleanPreviewRequest } from '@/types'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'

interface DataCleanerProps {
  content: string
  cleanedContent?: string
  onClean: (cleaned: string) => void
}

export function DataCleaner({ content, cleanedContent = '', onClean }: DataCleanerProps) {
  const { options } = usePipelineOptions()
  const [previewDiff, setPreviewDiff] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [llmEnabled, setLlmEnabled] = useState(false)
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([])
  const [promptTemplateId, setPromptTemplateId] = useState<string>('')

  // Load prompt templates
  useEffect(() => {
    let cancelled = false
    const loadTemplates = async () => {
      try {
        const response = await promptTemplateApi.list({ is_active: true, limit: 50 })
        if (cancelled) return
        setPromptTemplates(response.items || [])
      } catch {
        if (cancelled) return
        setPromptTemplates([])
      }
    }
    loadTemplates()
    return () => {
      cancelled = true
    }
  }, [])

  // 应用清洗
  const handleApply = useCallback(async () => {
    setIsApplying(true)
    setBackendError(null)

    try {
      // 构造请求，直接使用 Context 中的 Pipeline Options
      const req: CleanPreviewRequest = {
        markdown: content,
        use_default_rules: true, // 默认开启基础规则
        rules: [],
        normalize_line_endings: true,
        trim_trailing_spaces: true,
        
        // 映射 Pipeline Options 到后端 CleanPreviewRequest
        remove_toc_lines: options.governance_remove_toc_lines,
        remove_noise_lines: options.governance_remove_noise_lines,
        remove_common_lines: options.governance_remove_common_lines,
        unwrap_lines: options.governance_unwrap_lines,
        unwrap_max_line_length: options.governance_unwrap_max_line_length,
        noise_min_chars: options.governance_noise_min_chars,
        noise_ratio_threshold: options.governance_noise_ratio_threshold,
        common_lines_min_occurrences: options.governance_common_lines_min_docs,
      }

      const res = await pipelineApi.cleanPreview(req)
      let next = res.markdown

      if (llmEnabled) {
        try {
          const llmReq: LLMCleanPreviewRequest = {
            markdown: next,
            prompt_template_id: promptTemplateId || undefined,
          }
          const llmRes = await pipelineApi.llmCleanPreview(llmReq)
          next = llmRes.markdown
          if (llmRes.warnings?.length) {
            setBackendError(llmRes.warnings.join('；'))
          }
        } catch (err: any) {
          setBackendError(err?.response?.data?.detail || err?.message || 'LLM 清洗失败，已保留规则清洗结果')
        }
      }

      onClean(next)
    } catch (err: any) {
      setBackendError(err?.response?.data?.detail || err?.message || '后端清洗失败')
    } finally {
      setIsApplying(false)
    }
  }, [content, options, onClean, llmEnabled, promptTemplateId])

  // 重置
  const handleReset = useCallback(() => {
    onClean(content)
  }, [onClean, content])

  return (
    <div className="p-6 space-y-6">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="w-5 h-5 text-sky-600" />
          <h3 className="font-bold text-gray-900">智能清洗配置</h3>
        </div>
      </div>

      {/* 嵌入 Pipeline Options Panel */}
      <div className="border border-sky-100 rounded-xl overflow-hidden">
        <div className="bg-sky-50 px-4 py-2 border-b border-sky-100 text-xs font-medium text-sky-700">
          规则配置
        </div>
        <div className="p-4 bg-white">
           <PipelineOptionsPanel compact={false} />
        </div>
      </div>

      {backendError && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-700">
          {backendError}
        </div>
      )}

      {/* 操作按钮 */}
      <div className="flex items-center gap-2 pt-4 border-t border-gray-200">
        <Button
          onClick={handleReset}
          variant="outline"
          size="sm"
          className="flex-1 gap-1.5 border-sky-200 text-sky-700 hover:bg-sky-50"
        >
          <Undo className="w-3.5 h-3.5" />
          重置内容
        </Button>
        <Button
          onClick={handleApply}
          disabled={isApplying}
          className="flex-1 gap-2 bg-sky-600 hover:bg-sky-700 text-white"
        >
          {isApplying ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Sparkles className="w-4 h-4" />
          )}
          {isApplying ? '清洗中...' : '执行智能清洗'}
        </Button>
      </div>

      {/* LLM 清洗 */}
      <div className="border border-gray-200 rounded-xl p-4 bg-white">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-600" />
            <span className="text-sm font-medium text-gray-800">LLM 深度清洗</span>
          </div>
          <Button
            variant={llmEnabled ? 'default' : 'outline'}
            size="sm"
            onClick={() => setLlmEnabled((v) => !v)}
            className={cn(llmEnabled ? 'bg-purple-600 hover:bg-purple-700' : '')}
          >
            {llmEnabled ? '已启用' : '启用'}
          </Button>
        </div>

        {llmEnabled && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-16">提示词</span>
              <Select value={promptTemplateId} onValueChange={setPromptTemplateId}>
                <SelectTrigger className="h-8 text-xs w-full">
                  <SelectValue placeholder="选择清洗模板" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">默认清洗模板（内置）</SelectItem>
                  {promptTemplates.map((tpl) => (
                    <SelectItem key={tpl.id} value={tpl.id}>
                      {tpl.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
      </div>

      {/* 差异对比 (简化版) */}
      <div className="border border-gray-200 rounded-xl overflow-hidden">
          <button
            onClick={() => setPreviewDiff(!previewDiff)}
            className="w-full flex items-center justify-between p-3 hover:bg-gray-50 transition-colors"
          >
            <span className="text-sm font-medium text-gray-700">内容差异对比</span>
            <TextCursorInput className="w-4 h-4 text-gray-400" />
          </button>
          {previewDiff && (
            <div className="p-4 border-t border-gray-200 bg-gray-50 max-h-60 overflow-y-auto">
               <p className="text-xs text-gray-500 mb-2">对比功能开发中...</p>
            </div>
          )}
      </div>
    </div>
  )
}