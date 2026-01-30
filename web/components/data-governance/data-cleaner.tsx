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
import type { CleanPreviewRequest, CleanPreviewResponse, LLMCleanPreviewRequest } from '@/types'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GovernanceProfileSelector } from '@/components/governance-profile-selector'
import { CleanPreviewRuleStatsPanel } from '@/components/governance-profiles/clean-preview-rule-stats-panel'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'

interface DataCleanerProps {
  content: string
  cleanedContent?: string
  onClean: (cleaned: string) => void
}

export function DataCleaner({ content, cleanedContent = '', onClean }: DataCleanerProps) {
  const { options, updateOption, setEnabled } = usePipelineOptions()
  const [previewDiff, setPreviewDiff] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [backendInfo, setBackendInfo] = useState<string | null>(null)
  const [lastPreview, setLastPreview] = useState<CleanPreviewResponse | null>(null)
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
        rules: Array.isArray(options.governance_regex_rules) ? options.governance_regex_rules : [],
        include_diff: true,
        diff_max_lines: 2000,
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
      setLastPreview(res)
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

  const applyPipelinePatch = useCallback((patch: Record<string, any>) => {
    setEnabled(true)
    for (const [key, value] of Object.entries(patch || {})) {
      updateOption(key as any, value as any)
    }
  }, [setEnabled, updateOption])

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
          <div className="space-y-4">
            <div className="rounded-lg border border-border/60 p-3 bg-background/40">
              <div className="text-xs font-medium text-muted-foreground mb-2">治理预设（Profiles/脚本）</div>
              <GovernanceProfileSelector compact={true} onApplyPatch={applyPipelinePatch} />
            </div>
            <PipelineOptionsPanel compact={false} />
          </div>
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
            <div className="p-4 border-t border-border bg-muted max-h-80 overflow-y-auto overscroll-contain no-scrollbar space-y-3">
              {lastPreview?.issues?.length ? (
                <div className="rounded-lg border border-border/60 bg-background/40 p-3">
                  <div className="text-xs font-medium text-muted-foreground mb-2">检测到的问题（Best-effort）</div>
                  <div className="space-y-2">
                    {lastPreview.issues.slice(0, 8).map((it) => (
                      <div key={it.code} className="text-xs text-foreground/80">
                        <span className={cn(
                          'mr-2 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium',
                          it.severity === 'error'
                            ? 'bg-destructive/10 text-destructive'
                            : it.severity === 'warning'
                              ? 'bg-warning/10 text-warning'
                              : 'bg-info/10 text-info'
                        )}>
                          {it.severity.toUpperCase()}
                        </span>
                        {it.message}
                        {typeof it.count === 'number' && it.count > 0 ? `（${it.count}）` : ''}
                      </div>
                    ))}
                  </div>

                  {lastPreview.suggested_pipeline_patch && Object.keys(lastPreview.suggested_pipeline_patch).length > 0 && (
                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="text-[11px] text-muted-foreground">
                        已生成治理建议，可一键应用到当前配置（会覆盖对应字段）。
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => applyPipelinePatch(lastPreview.suggested_pipeline_patch as any)}
                      >
                        应用建议
                      </Button>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">暂无明显问题提示。</p>
              )}

              {Array.isArray(lastPreview?.rule_stats) && lastPreview.rule_stats.length ? (
                <CleanPreviewRuleStatsPanel ruleStats={lastPreview.rule_stats} />
              ) : null}

              {typeof lastPreview?.diff_unified === 'string' && lastPreview.diff_unified.trim() ? (
                <div className="rounded-lg border border-border/60 bg-background/40 overflow-hidden">
                  <div className="px-3 py-2 border-b border-border/60 text-xs font-medium text-muted-foreground flex items-center justify-between">
                    <span>Unified Diff</span>
                    {lastPreview.diff_truncated ? (
                      <span className="text-[11px] text-muted-foreground">已截断</span>
                    ) : null}
                  </div>
                  <pre className="p-3 text-[11px] leading-relaxed font-mono whitespace-pre overflow-x-auto">
{lastPreview.diff_unified}
                  </pre>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">暂无差异可显示（或尚未执行清洗）。</p>
              )}
            </div>
          )}
      </div>
    </div>
  )
}
