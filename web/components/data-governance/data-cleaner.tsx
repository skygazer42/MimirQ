'use client'

import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Info, Loader2, Sparkles, TextCursorInput, Undo, Wrench } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { pipelineApi, promptTemplateApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { coerceOneOf } from '@/lib/one-of'
import { queryKeys } from '@/lib/query-keys'
import type {
  CleanPreviewRequest,
  CleanPreviewResponse,
  DocumentPipelineOptions,
  LLMCleanPreviewRequest,
} from '@/types'
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
import { computeCleanPreviewImpact } from '@/lib/clean-preview-impact'

const SELECT_DEFAULT_VALUE = '__mimirq_default__'
const DATA_CLEANER_INPUT_FORMAT_VALUES = ['markdown', 'html'] as const

interface DataCleanerProps {
  content: string
  cleanedContent?: string
  onClean: (cleaned: string) => void
}

function getSeverityBadgeClass(severity: string) {
  if (severity === 'error') {
    return 'bg-destructive/10 text-destructive'
  }
  if (severity === 'warning') {
    return 'bg-warning/10 text-warning'
  }
  return 'bg-info/10 text-info'
}

export function DataCleaner({
  content,
  cleanedContent: _cleanedContent = '',
  onClean,
}: Readonly<DataCleanerProps>) {
  const t = useTranslations('DataCleaner')
  const { options, updateOption, setEnabled } = usePipelineOptions()
  const [previewDiff, setPreviewDiff] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [backendInfo, setBackendInfo] = useState<string | null>(null)
  const [lastPreview, setLastPreview] = useState<CleanPreviewResponse | null>(null)
  const [inputFormat, setInputFormat] = useState<'markdown' | 'html'>('markdown')
  const [llmEnabled, setLlmEnabled] = useState(false)
  const [promptTemplateId, setPromptTemplateId] = useState<string>('')
  const impact = useMemo(() => computeCleanPreviewImpact(lastPreview), [lastPreview])

  const promptTemplatesQuery = useQuery({
    queryKey: queryKeys.prompts.list({ is_active: true, limit: 50 }),
    queryFn: async () => {
      const response = await promptTemplateApi.list({ is_active: true, limit: 50 })
      return response.items || []
    },
  })
  const promptTemplates = promptTemplatesQuery.data || []

  const handleApply = useCallback(async () => {
    setIsApplying(true)
    setBackendError(null)
    setBackendInfo(null)

    try {
      const opt = <T,>(value: T | null | undefined): T | undefined =>
        value === null || value === undefined ? undefined : value

      const request: CleanPreviewRequest = {
        markdown: content,
        use_default_rules: true,
        rules: Array.isArray(options.governance_regex_rules) ? options.governance_regex_rules : [],
        include_diff: true,
        diff_max_lines: 2000,
        input_format: inputFormat,
        html_xpath: inputFormat === 'html' ? (options.governance_html_xpath || undefined) : undefined,
        normalize_line_endings: true,
        trim_trailing_spaces: true,
        remove_toc_lines: opt(options.governance_remove_toc_lines),
        remove_noise_lines: opt(options.governance_remove_noise_lines),
        remove_common_lines: opt(options.governance_remove_common_lines),
        unwrap_lines: opt(options.governance_unwrap_lines),
        remove_boilerplate: opt(options.governance_remove_boilerplate),
        remove_images: opt(options.governance_remove_images),
        extract_frontmatter: opt(options.governance_extract_frontmatter),
        strip_frontmatter: opt(options.governance_strip_frontmatter),
        detect_language: opt(options.governance_detect_language),
        language_min_chars: opt(options.governance_language_min_chars),
        normalize_urls: opt(options.governance_normalize_urls),
        normalize_urls_strip_tracking: opt(options.governance_normalize_urls_strip_tracking),
        drop_duplicate_paragraphs: opt(options.governance_drop_duplicate_paragraphs),
        drop_duplicate_paragraphs_min_occurrences: opt(
          options.governance_drop_duplicate_paragraphs_min_occurrences
        ),
        drop_duplicate_paragraphs_min_chars: opt(options.governance_drop_duplicate_paragraphs_min_chars),
        drop_duplicate_paragraphs_max_chars: opt(options.governance_drop_duplicate_paragraphs_max_chars),
        trim_references: opt(options.governance_trim_references),
        extract_keywords: opt(options.governance_extract_keywords),
        keywords_provider: opt(options.governance_keywords_provider),
        keywords_top_k: opt(options.governance_keywords_top_k),
        keywords_max_chars: opt(options.governance_keywords_max_chars),
        normalize_tables: opt(options.governance_normalize_tables),
        strip_code_line_numbers: opt(options.governance_strip_code_line_numbers),
        pii_anonymize: opt(options.governance_pii_anonymize),
        pii_mode: opt(options.governance_pii_mode),
        pii_mask: opt(options.governance_pii_mask),
        secrets_redact: opt(options.governance_secrets_redact),
        secrets_mode: opt(options.governance_secrets_mode),
        secrets_mask: opt(options.governance_secrets_mask),
        max_blank_lines: opt(options.governance_max_blank_lines),
        drop_outline_only: opt(options.governance_drop_outline_only),
        drop_outline_min_content_chars: opt(options.governance_drop_outline_min_content_chars),
        drop_outline_max_heading_ratio: opt(options.governance_drop_outline_max_heading_ratio),
        drop_low_density: opt(options.governance_drop_low_density),
        drop_low_density_threshold: opt(options.governance_drop_low_density_threshold),
        unwrap_max_line_length: opt(options.governance_unwrap_max_line_length),
        noise_min_chars: opt(options.governance_noise_min_chars),
        noise_ratio_threshold: opt(options.governance_noise_ratio_threshold),
        common_lines_min_occurrences: opt(options.governance_common_lines_min_docs),
      }

      const response = await pipelineApi.cleanPreview(request)
      setLastPreview(response)

      const info: string[] = []
      if (typeof response.input_lines === 'number' && typeof response.output_lines === 'number') {
        const removed = typeof response.removed_lines === 'number' ? response.removed_lines : 0
        const added = typeof response.added_lines === 'number' ? response.added_lines : 0
        const changedLines = typeof response.changed_lines === 'number' ? response.changed_lines : 0
        const inputChars = typeof response.input_chars === 'number' ? response.input_chars : content.length
        const outputChars =
          typeof response.output_chars === 'number' ? response.output_chars : (response.markdown || '').length

        info.push(
          t('info.cleaningStats', {
            inputLines: response.input_lines,
            outputLines: response.output_lines,
            removed,
            added,
            changedLines,
            inputChars,
            outputChars,
          })
        )
      }

      if (typeof response.urls_changed === 'number' && response.urls_changed > 0) {
        info.push(t('info.urlsChanged', { count: response.urls_changed }))
      }
      if (typeof response.paragraphs_dropped === 'number' && response.paragraphs_dropped > 0) {
        info.push(t('info.paragraphsDropped', { count: response.paragraphs_dropped }))
      }
      if (typeof response.references_removed_lines === 'number' && response.references_removed_lines > 0) {
        info.push(t('info.referencesRemoved', { count: response.references_removed_lines }))
      }

      if (response.title) info.push(t('info.title', { value: response.title }))
      if (Array.isArray(response.tags) && response.tags.length) {
        const value = `${response.tags.slice(0, 12).join('，')}${response.tags.length > 12 ? '...' : ''}`
        info.push(t('info.tags', { value }))
      }
      if (response.language) {
        const confidence =
          typeof response.language_confidence === 'number'
            ? t('info.languageWithConfidence', { value: response.language, confidence: response.language_confidence.toFixed(2) })
            : response.language
        info.push(t('info.language', { value: confidence }))
      }
      if (Array.isArray(response.keywords) && response.keywords.length) {
        const value = `${response.keywords.slice(0, 12).join('，')}${response.keywords.length > 12 ? '...' : ''}`
        info.push(t('info.keywords', { value }))
      }
      if (response.frontmatter && typeof response.frontmatter === 'object') {
        const keys = Object.keys(response.frontmatter || {})
        if (keys.length) {
          const value = `${keys.slice(0, 8).join('，')}${keys.length > 8 ? '...' : ''}`
          info.push(t('info.frontmatter', { value }))
        }
      }

      if (response.pii_hits && Object.keys(response.pii_hits).length > 0) {
        const summary = Object.entries(response.pii_hits)
          .map(([key, value]) => `${key}=${value}`)
          .join('，')
        info.push(t('info.piiHits', { value: summary }))
      }
      if (response.secrets_hits && Object.keys(response.secrets_hits).length > 0) {
        const summary = Object.entries(response.secrets_hits)
          .map(([key, value]) => `${key}=${value}`)
          .join('，')
        info.push(t('info.secretsHits', { value: summary }))
      }
      setBackendInfo(info.length ? info.join('\n') : null)

      if (response.dropped) {
        setBackendError(
          t('errors.filtered', {
            reason: response.drop_reason || t('errors.qualityFilterTriggered'),
          })
        )
        onClean(response.markdown || '')
        return
      }

      let next = response.markdown

      if (llmEnabled) {
        try {
          const llmRequest: LLMCleanPreviewRequest = {
            markdown: next,
            prompt_template_id: promptTemplateId || undefined,
          }
          const llmResponse = await pipelineApi.llmCleanPreview(llmRequest)
          next = llmResponse.markdown
          if (llmResponse.warnings?.length) {
            setBackendError(llmResponse.warnings.join('；'))
          }
        } catch (error: any) {
          setBackendError(formatApiError(error, t('errors.llmCleanFailedKeepPreview')))
        }
      }

      onClean(next)
    } catch (error: any) {
      setBackendError(formatApiError(error, t('errors.backendCleanFailed')))
    } finally {
      setIsApplying(false)
    }
  }, [content, inputFormat, llmEnabled, onClean, options, promptTemplateId, t])

  const applyPipelinePatch = useCallback(
    (patch: Partial<DocumentPipelineOptions>) => {
      setEnabled(true)
      for (const key of Object.keys(patch) as Array<keyof DocumentPipelineOptions>) {
        const value = patch[key]
        if (value === undefined) continue
        updateOption(key, value)
      }
    },
    [setEnabled, updateOption]
  )

  const handleReset = useCallback(() => {
    onClean(content)
  }, [content, onClean])

  return (
    <div className="space-y-4 p-4 md:space-y-5 md:p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wrench className="size-[18px] text-primary/80" />
          <h3 className="text-[15px] font-medium tracking-[-0.01em] text-foreground/80">{t("header.title")}</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground/80">{t('inputFormat.label')}</span>
          <Select
            value={inputFormat}
            onValueChange={(value) => setInputFormat(coerceOneOf(DATA_CLEANER_INPUT_FORMAT_VALUES, value, 'markdown'))}
          >
            <SelectTrigger className="h-8 w-[112px] rounded-lg border-border/60 bg-background/70 text-[11px] text-foreground/80 shadow-none">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="markdown">{t('inputFormat.options.markdown')}</SelectItem>
              <SelectItem value="html">{t('inputFormat.options.html')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border/60 bg-card/95">
        <div className="border-b border-border/60 bg-muted/20 px-3.5 py-2 text-[11px] font-medium text-muted-foreground/80">
          {t('rules.title')}
        </div>
        <div className="p-3.5">
          <div className="space-y-3">
            <div className="rounded-xl border border-border/60 bg-muted/[0.16] p-2.5">
              <div className="mb-1.5 text-[11px] font-medium text-muted-foreground/80">{t('rules.profilesTitle')}</div>
              <GovernanceProfileSelector compact={true} onApplyPatch={applyPipelinePatch} />
            </div>
            <PipelineOptionsPanel compact={false} />
          </div>
        </div>
      </div>

      {backendError && (
        <Alert variant="warning">
          <AlertTriangle className="size-4" />
          <div>
            <AlertTitle>{t('alerts.warningTitle')}</AlertTitle>
            <AlertDescription className="text-foreground/70">{backendError}</AlertDescription>
          </div>
        </Alert>
      )}
      {backendInfo && (
        <Alert variant="info">
          <Info className="size-4" />
          <div>
            <AlertTitle>{t('alerts.infoTitle')}</AlertTitle>
            <AlertDescription className="whitespace-pre-line text-foreground/70">{backendInfo}</AlertDescription>
          </div>
        </Alert>
      )}

      <div className="flex items-center gap-2 border-t border-border/60 pt-3.5">
        <Button onClick={handleReset} variant="outline" size="sm" className="h-8 flex-1 gap-1.5 rounded-lg border-border/60 bg-background/70 text-foreground/75 shadow-none">
          <Undo className="h-3.5 w-3.5" />
          {t('actions.reset')}
        </Button>
        <Button onClick={handleApply} disabled={isApplying} className="h-8 flex-1 gap-2 rounded-lg shadow-none">
          {isApplying ? (
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
          ) : (
            <Sparkles className="size-4" />
          )}
          {isApplying ? t('actions.applying') : t("actions.apply")}
        </Button>
      </div>

      <div className="rounded-xl border border-border/60 bg-card/95 p-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary/75" />
            <span className="text-sm font-medium text-foreground/80">{t('llm.title')}</span>
          </div>
          <Button variant={llmEnabled ? 'default' : 'outline'} size="sm" className="h-8 rounded-lg shadow-none" onClick={() => setLlmEnabled((value) => !value)}>
            {llmEnabled ? t('llm.enabled') : t('llm.enable')}
          </Button>
        </div>

        {llmEnabled && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="w-16 text-xs text-muted-foreground">{t('llm.promptTemplateLabel')}</span>
              <Select
                value={promptTemplateId || SELECT_DEFAULT_VALUE}
                onValueChange={(value) => setPromptTemplateId(value === SELECT_DEFAULT_VALUE ? '' : value)}
              >
                <SelectTrigger className="h-8 w-full rounded-lg border-border/60 bg-background/70 text-[11px] shadow-none">
                  <SelectValue placeholder={t('llm.promptTemplatePlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={SELECT_DEFAULT_VALUE}>{t('llm.promptTemplateDefault')}</SelectItem>
                  {promptTemplates.map((template) => (
                    <SelectItem key={template.id} value={template.id}>
                      {template.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-border/60 bg-card/95">
        <button
          type="button"
          onClick={() => setPreviewDiff((value) => !value)}
          className="flex w-full items-center justify-between px-3 py-2.5 transition-colors hover:bg-muted/30"
        >
          <span className="text-sm font-medium text-foreground/75">{t('diff.title')}</span>
          <TextCursorInput className="size-4 text-muted-foreground" />
        </button>
        {previewDiff && (
          <div className="max-h-80 space-y-3 overflow-y-auto border-t border-border/60 bg-muted/20 p-3.5 no-scrollbar overscroll-contain">
            {impact ? (
              <div className="rounded-lg border border-border/60 bg-background/40 p-3">
                <div className="mb-2 text-[11px] font-medium text-muted-foreground/80">{t('diff.impactTitle')}</div>
                <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                  <div className="flex items-center justify-between gap-2">
                    <span>{t('diff.impact.chars')}</span>
                    <span className="font-mono text-foreground/90">
                      {impact.inputChars}
                      {' -> '}
                      {impact.outputChars} ({impact.deltaChars >= 0 ? '+' : ''}
                      {impact.deltaChars}
                      {impact.deltaCharsPct == null ? '' : `, ${Math.round(impact.deltaCharsPct * 100)}%`})
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span>{t('diff.impact.lines')}</span>
                    <span className="font-mono text-foreground/90">
                      {impact.inputLines}
                      {' -> '}
                      {impact.outputLines} ({impact.deltaLines >= 0 ? '+' : ''}
                      {impact.deltaLines})
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span>{t('diff.impact.diff')}</span>
                    <span className="font-mono text-foreground/90">
                      +{impact.addedLines} / -{impact.removedLines} / ~{impact.changedLines}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span>{t('diff.impact.piiSecrets')}</span>
                    <span className="font-mono text-foreground/90">
                      {impact.piiHitsTotal} / {impact.secretsHitsTotal}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span>{t('diff.impact.urlsChanged')}</span>
                    <span className="font-mono text-foreground/90">{impact.urlsChanged}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span>{t('diff.impact.paragraphsDropped')}</span>
                    <span className="font-mono text-foreground/90">{impact.paragraphsDropped}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span>{t('diff.impact.referencesRemovedLines')}</span>
                    <span className="font-mono text-foreground/90">{impact.referencesRemovedLines}</span>
                  </div>
                </div>
              </div>
            ) : null}

            {lastPreview?.issues?.length ? (
              <div className="rounded-lg border border-border/60 bg-background/40 p-3">
                <div className="mb-2 text-xs font-medium text-muted-foreground">{t('diff.issuesTitle')}</div>
                <div className="space-y-2">
                  {lastPreview.issues.slice(0, 8).map((issue) => (
                    <div key={issue.code} className="text-xs text-foreground/80">
                      <span
                        className={cn(
                          'mr-2 inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium',
                          getSeverityBadgeClass(issue.severity)
                        )}
                      >
                        {t(`severity.${issue.severity}`)}
                      </span>
                      {issue.message}
                      {typeof issue.count === 'number' && issue.count > 0 ? `（${issue.count}）` : ''}
                    </div>
                  ))}
                </div>

                {lastPreview.suggested_pipeline_patch &&
                  Object.keys(lastPreview.suggested_pipeline_patch).length > 0 && (
                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="text-[11px] text-muted-foreground">{t('diff.applySuggestionHint')}</div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => applyPipelinePatch(lastPreview.suggested_pipeline_patch as any)}
                      >
                        {t('diff.applySuggestion')}
                      </Button>
                    </div>
                  )}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">{t('diff.noIssueHint')}</p>
            )}

            {Array.isArray(lastPreview?.rule_stats) && lastPreview.rule_stats.length ? (
              <CleanPreviewRuleStatsPanel ruleStats={lastPreview.rule_stats} />
            ) : null}

            {typeof lastPreview?.diff_unified === 'string' && lastPreview.diff_unified.trim() ? (
              <div className="overflow-hidden rounded-lg border border-border/60 bg-background/40">
                <div className="flex items-center justify-between border-b border-border/60 px-3 py-2 text-xs font-medium text-muted-foreground">
                  <span>{t('diff.unifiedDiff')}</span>
                  {lastPreview.diff_truncated ? (
                    <span className="text-[11px] text-muted-foreground">{t('diff.truncated')}</span>
                  ) : null}
                </div>
                <pre className="overflow-x-auto whitespace-pre p-3 font-mono text-[11px] leading-relaxed">
{lastPreview.diff_unified}
                </pre>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">{t('diff.noDiffHint')}</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
