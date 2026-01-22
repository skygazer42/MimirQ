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
  AlertTriangle,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { pipelineApi, promptTemplateApi, PromptTemplate } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
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

const SELECT_DEFAULT_VALUE = '__mimirq_default__'

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
  const [backendInfo, setBackendInfo] = useState<string | null>(null)
  const [inputFormat, setInputFormat] = useState<'markdown' | 'html'>('markdown')
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
    setBackendInfo(null)

    try {
      // 构造请求，直接使用 Context 中的 Pipeline Options
      const req: CleanPreviewRequest = {
        markdown: content,
        use_default_rules: true, // 默认开启基础规则
        rules: [],
        input_format: inputFormat,
        html_xpath: inputFormat === 'html' ? (options.governance_html_xpath || undefined) : undefined,
        normalize_line_endings: true,
        trim_trailing_spaces: true,
        
        // 映射 Pipeline Options 到后端 CleanPreviewRequest
        remove_toc_lines: options.governance_remove_toc_lines,
        remove_noise_lines: options.governance_remove_noise_lines,
        remove_common_lines: options.governance_remove_common_lines,
        unwrap_lines: options.governance_unwrap_lines,
        remove_boilerplate: options.governance_remove_boilerplate,
        remove_images: options.governance_remove_images,
        extract_frontmatter: options.governance_extract_frontmatter,
        strip_frontmatter: options.governance_strip_frontmatter,
        detect_language: options.governance_detect_language,
        language_min_chars: options.governance_language_min_chars,
        normalize_urls: options.governance_normalize_urls,
        normalize_urls_strip_tracking: options.governance_normalize_urls_strip_tracking,
        drop_duplicate_paragraphs: options.governance_drop_duplicate_paragraphs,
        drop_duplicate_paragraphs_min_occurrences: options.governance_drop_duplicate_paragraphs_min_occurrences,
        drop_duplicate_paragraphs_min_chars: options.governance_drop_duplicate_paragraphs_min_chars,
        drop_duplicate_paragraphs_max_chars: options.governance_drop_duplicate_paragraphs_max_chars,
        trim_references: options.governance_trim_references,
        extract_keywords: options.governance_extract_keywords,
        keywords_provider: options.governance_keywords_provider,
        keywords_top_k: options.governance_keywords_top_k,
        keywords_max_chars: options.governance_keywords_max_chars,
        normalize_tables: options.governance_normalize_tables,
        strip_code_line_numbers: options.governance_strip_code_line_numbers,
        pii_anonymize: options.governance_pii_anonymize,
        pii_mode: options.governance_pii_mode,
        pii_mask: options.governance_pii_mask,
        secrets_redact: options.governance_secrets_redact,
        secrets_mode: options.governance_secrets_mode,
        secrets_mask: options.governance_secrets_mask,
        max_blank_lines: options.governance_max_blank_lines,
        drop_outline_only: options.governance_drop_outline_only,
        drop_outline_min_content_chars: options.governance_drop_outline_min_content_chars,
        drop_outline_max_heading_ratio: options.governance_drop_outline_max_heading_ratio,
        drop_low_density: options.governance_drop_low_density,
        drop_low_density_threshold: options.governance_drop_low_density_threshold,
        unwrap_max_line_length: options.governance_unwrap_max_line_length,
        noise_min_chars: options.governance_noise_min_chars,
        noise_ratio_threshold: options.governance_noise_ratio_threshold,
        common_lines_min_occurrences: options.governance_common_lines_min_docs,
      }

      const res = await pipelineApi.cleanPreview(req)
      const info: string[] = []
      if (typeof res.input_lines === 'number' && typeof res.output_lines === 'number') {
        const removed = typeof res.removed_lines === 'number' ? res.removed_lines : 0
        const added = typeof res.added_lines === 'number' ? res.added_lines : 0
        const changedLines = typeof res.changed_lines === 'number' ? res.changed_lines : 0
        const inChars = typeof res.input_chars === 'number' ? res.input_chars : content.length
        const outChars = typeof res.output_chars === 'number' ? res.output_chars : (res.markdown || '').length
        info.push(`清洗统计：行 ${res.input_lines} → ${res.output_lines}（- ${removed} / + ${added} / ~ ${changedLines}），字符 ${inChars} → ${outChars}`)
      }

      if (typeof res.urls_changed === 'number' && res.urls_changed > 0) {
        info.push(`URL 规范化：变更 ${res.urls_changed} 处`)
      }
      if (typeof res.paragraphs_dropped === 'number' && res.paragraphs_dropped > 0) {
        info.push(`段落重复块去重：移除 ${res.paragraphs_dropped} 段`)
      }
      if (typeof res.references_removed_lines === 'number' && res.references_removed_lines > 0) {
        info.push(`参考文献裁剪：移除 ${res.references_removed_lines} 行`)
      }

      if (res.title) info.push(`标题：${res.title}`)
      if (Array.isArray(res.tags) && res.tags.length) info.push(`标签：${res.tags.slice(0, 12).join('，')}${res.tags.length > 12 ? '…' : ''}`)
      if (res.language) {
        const conf = typeof res.language_confidence === 'number' ? res.language_confidence : null
        info.push(`语言：${res.language}${conf !== null ? `（${conf.toFixed(2)}）` : ''}`)
      }
      if (Array.isArray(res.keywords) && res.keywords.length) {
        info.push(`关键词：${res.keywords.slice(0, 12).join('，')}${res.keywords.length > 12 ? '…' : ''}`)
      }
      if (res.frontmatter && typeof res.frontmatter === 'object') {
        const keys = Object.keys(res.frontmatter || {})
        if (keys.length) info.push(`Frontmatter：${keys.slice(0, 8).join('，')}${keys.length > 8 ? '…' : ''}`)
      }

      if (res.pii_hits && Object.keys(res.pii_hits).length > 0) {
        const summary = Object.entries(res.pii_hits)
          .map(([k, v]) => `${k}=${v}`)
          .join('，')
        info.push(`已匿名化隐私信息：${summary}`)
      }
      if (res.secrets_hits && Object.keys(res.secrets_hits).length > 0) {
        const summary = Object.entries(res.secrets_hits)
          .map(([k, v]) => `${k}=${v}`)
          .join('，')
        info.push(`已脱敏密钥/Token：${summary}`)
      }
      setBackendInfo(info.length ? info.join('\n') : null)

      if (res.dropped) {
        setBackendError(`清洗后文档被过滤：${res.drop_reason || '质量过滤触发'}`)
        onClean(res.markdown || '')
        return
      }

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
          setBackendError(formatApiError(err, 'LLM 清洗失败，已保留规则清洗结果'))
        }
      }

      onClean(next)
    } catch (err: any) {
      setBackendError(formatApiError(err, '后端清洗失败'))
    } finally {
      setIsApplying(false)
    }
  }, [content, options, onClean, llmEnabled, promptTemplateId, inputFormat])

  // 重置
  const handleReset = useCallback(() => {
    onClean(content)
  }, [onClean, content])

  return (
    <div className="p-6 space-y-6">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="w-5 h-5 text-primary" />
          <h3 className="font-bold text-foreground">智能清洗配置</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">输入格式</span>
          <Select value={inputFormat} onValueChange={(v) => setInputFormat(v as any)}>
            <SelectTrigger className="h-8 text-xs w-[120px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="markdown">Markdown</SelectItem>
              <SelectItem value="html">HTML</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* 嵌入 Pipeline Options Panel */}
      <div className="border border-border/60 rounded-xl overflow-hidden">
        <div className="bg-muted/30 px-4 py-2 border-b border-border/60 text-xs font-medium text-muted-foreground">
          规则配置
        </div>
        <div className="p-4 bg-card">
           <PipelineOptionsPanel compact={false} />
        </div>
      </div>

      {backendError && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <div>
            <AlertTitle>清洗提示</AlertTitle>
            <AlertDescription className="text-foreground/80">{backendError}</AlertDescription>
          </div>
        </Alert>
      )}
      {backendInfo && (
        <Alert variant="info">
          <Info className="h-4 w-4" />
          <div>
            <AlertTitle>清洗信息</AlertTitle>
            <AlertDescription className="text-foreground/80">{backendInfo}</AlertDescription>
          </div>
        </Alert>
      )}

      {/* 操作按钮 */}
      <div className="flex items-center gap-2 pt-4 border-t border-border">
        <Button
          onClick={handleReset}
          variant="outline"
          size="sm"
          className="flex-1 gap-1.5"
        >
          <Undo className="w-3.5 h-3.5" />
          重置内容
        </Button>
        <Button
          onClick={handleApply}
          disabled={isApplying}
          className="flex-1 gap-2"
        >
          {isApplying ? (
            <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
          ) : (
            <Sparkles className="w-4 h-4" />
          )}
          {isApplying ? '清洗中...' : '执行智能清洗'}
        </Button>
      </div>

      {/* LLM 清洗 */}
      <div className="border border-border rounded-xl p-4 bg-card">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-primary" />
            <span className="text-sm font-medium text-foreground">LLM 深度清洗</span>
          </div>
          <Button
            variant={llmEnabled ? 'default' : 'outline'}
            size="sm"
            onClick={() => setLlmEnabled((v) => !v)}
          >
            {llmEnabled ? '已启用' : '启用'}
          </Button>
        </div>

        {llmEnabled && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground w-16">提示词</span>
              <Select
                value={promptTemplateId || SELECT_DEFAULT_VALUE}
                onValueChange={(v) => setPromptTemplateId(v === SELECT_DEFAULT_VALUE ? '' : v)}
              >
                <SelectTrigger className="h-8 text-xs w-full">
                  <SelectValue placeholder="选择清洗模板" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={SELECT_DEFAULT_VALUE}>默认清洗模板（内置）</SelectItem>
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
      <div className="border border-border rounded-xl overflow-hidden">
          <button
            onClick={() => setPreviewDiff(!previewDiff)}
            className="w-full flex items-center justify-between p-3 hover:bg-muted transition-colors"
          >
            <span className="text-sm font-medium text-foreground/80">内容差异对比</span>
            <TextCursorInput className="w-4 h-4 text-muted-foreground" />
          </button>
          {previewDiff && (
            <div className="p-4 border-t border-border bg-muted max-h-60 overflow-y-auto">
               <p className="text-xs text-muted-foreground mb-2">对比功能开发中...</p>
            </div>
          )}
      </div>
    </div>
  )
}
