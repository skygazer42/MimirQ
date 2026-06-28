'use client'

import { Fragment, useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, GitCompare, Info, Loader2, Sparkles, TextCursorInput, Undo, Wrench } from 'lucide-react'
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
        value ?? undefined

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
        } catch (error: unknown) {
          setBackendError(formatApiError(error, t('errors.llmCleanFailedKeepPreview')))
        }
      }

      onClean(next)
    } catch (error: unknown) {
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

  const resetButtonClass =
    'h-8 rounded-full border-border/45 bg-background/42 px-3 text-[11px] font-medium text-muted-foreground/78 shadow-none hover:border-border/55 hover:bg-background/64 hover:text-foreground'
  const applyButtonClass =
    'h-8 gap-2 rounded-full border-primary/30 bg-primary/[0.12] px-3.5 text-[11px] font-semibold text-primary shadow-[0_10px_24px_-18px_hsl(var(--primary)/0.45)] hover:border-primary/40 hover:bg-primary/[0.18] hover:text-primary'
  const llmToggleClass = cn(
    'h-7 rounded-full px-3 text-[11px] font-semibold shadow-none transition-colors motion-reduce:transition-none',
    llmEnabled
      ? 'border-accent/28 bg-accent/[0.09] text-accent hover:border-accent/38 hover:bg-accent/[0.16] hover:text-accent'
      : 'border-border/45 bg-background/48 text-muted-foreground hover:bg-background/70 hover:text-foreground'
  )
  const configShellClass =
    'overflow-hidden rounded-[1.35rem] border border-border/42 bg-[linear-gradient(180deg,hsl(var(--card)/0.82)_0%,hsl(var(--surface-2)/0.56)_100%)] p-2 shadow-[0_18px_46px_-40px_hsl(var(--foreground)/0.28),inset_0_1px_0_hsl(var(--card)/0.68)]'
  const configHeaderClass =
    'relative overflow-hidden rounded-[1.12rem] border border-border/36 bg-card/62 px-3 py-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.66)]'
  const rulesPanelClass =
    'mt-2 overflow-hidden rounded-[1.12rem] border border-border/38 bg-card/50 shadow-[0_14px_34px_-34px_hsl(var(--foreground)/0.2)]'
  const configFlowClass =
    'mt-3 grid grid-cols-[1fr_auto_1fr_auto_1fr] items-center gap-1 rounded-full border border-border/32 bg-background/34 px-2 py-1.5'
  const configFlowStepClass =
    'flex min-w-0 items-center justify-center gap-1.5 truncate rounded-full px-2 py-1 text-[10.5px] font-medium leading-3 text-muted-foreground/72 first:bg-primary/[0.07] first:text-primary'
  const configFlowDotClass =
    'size-1.5 shrink-0 rounded-full bg-current opacity-55'
  const configFlowConnectorClass =
    'h-px w-4 rounded-full bg-border/46'
  const configSubpanelClass =
    'rounded-[1rem] border border-border/32 bg-background/30 p-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.34)]'
  const llmPanelClass =
    'rounded-[1rem] border border-accent/18 bg-accent/[0.045] p-2.5'
  const diffPanelClass =
    'overflow-hidden rounded-[1rem] border border-border/45 bg-card/82 shadow-[0_8px_18px_rgba(15,23,42,0.02)]'
  const emptyStateClass =
    'flex items-start gap-2 rounded-[0.95rem] border border-dashed border-border/38 bg-background/34 px-3 py-2.5 text-[11px] leading-5 text-muted-foreground/72'
  const cleanerLabelClass =
    'text-[10px] font-semibold uppercase leading-3 tracking-[0.16em] text-muted-foreground/56'
  const cleanerCaptionClass =
    'text-[10.5px] leading-4 text-muted-foreground/62'

  return (
    <div className="space-y-3 p-4 md:p-5">
      <div className={configShellClass}>
        <div className={configHeaderClass}>
          <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--primary)/0.28),transparent)]" />
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-[0.95rem] border border-primary/16 bg-primary/[0.07] text-primary shadow-[0_10px_22px_-18px_hsl(var(--primary)/0.5)]">
                <Wrench className="size-4" />
              </span>
              <div className="min-w-0">
                <h3 className="text-[15px] font-semibold leading-5 tracking-[-0.018em] text-foreground/92">{t("header.title")}</h3>
                <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground/66">
                  预设与治理规则集中配置
                </p>
              </div>
            </div>
            <div className="flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-border/38 bg-background/42 px-2 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
              <span className="text-[10px] font-medium tracking-[0.08em] text-muted-foreground/58">格式</span>
              <Select
                value={inputFormat}
                onValueChange={(value) => setInputFormat(coerceOneOf(DATA_CLEANER_INPUT_FORMAT_VALUES, value, 'markdown'))}
              >
                <SelectTrigger className="focus-ring h-6 w-[92px] rounded-full border-0 bg-transparent px-1 text-[11px] font-semibold text-foreground/82 shadow-none">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="markdown">{t('inputFormat.options.markdown')}</SelectItem>
                  <SelectItem value="html">{t('inputFormat.options.html')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className={configFlowClass} aria-label="智能清洗流程">
            {['治理预设', '规则清洗', '结果预览'].map((label, index) => (
              <Fragment key={label}>
                {index > 0 ? <span aria-hidden="true" className={configFlowConnectorClass} /> : null}
                <span className={configFlowStepClass}>
                  <span className={configFlowDotClass} />
                  <span className="truncate">{label}</span>
                </span>
              </Fragment>
            ))}
          </div>
        </div>

        <div className={rulesPanelClass}>
          <div className="flex items-center justify-between gap-3 border-b border-border/35 bg-muted/[0.16] px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-[13px] font-semibold leading-4 tracking-[-0.012em] text-foreground/86">治理编排</div>
              <div className={cn('mt-0.5 truncate', cleanerCaptionClass)}>按顺序合并治理预设、脚本补丁和规则管线</div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <span className="rounded-full border border-primary/12 bg-primary/[0.06] px-2 py-0.5 text-[9.5px] font-medium text-primary/82">
                预设
              </span>
              <span className="rounded-full border border-info/12 bg-info/[0.06] px-2 py-0.5 text-[9.5px] font-medium text-info/82">
                管线
              </span>
            </div>
          </div>
          <div className="grid gap-2.5 p-2.5">
            <div className={configSubpanelClass}>
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className={cleanerLabelClass}>治理预设</div>
                <div className={cleanerCaptionClass}>选择预设或脚本补丁</div>
              </div>
              <GovernanceProfileSelector compact={true} onApplyPatch={applyPipelinePatch} />
            </div>
            <div className={configSubpanelClass}>
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className={cleanerLabelClass}>规则管线</div>
                <div className={cleanerCaptionClass}>规则开关与 JSON 配置</div>
              </div>
              <PipelineOptionsPanel compact={true} showJsonToolbar={true} showIndexingControls={false} />
            </div>
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

      <div className="flex items-center justify-between gap-2 rounded-[1rem] border border-border/34 bg-card/42 px-2 py-1.5">
        <Button onClick={handleReset} variant="outline" size="sm" className={resetButtonClass}>
          <Undo className="h-3.5 w-3.5" />
          {t('actions.reset')}
        </Button>
        <Button onClick={handleApply} disabled={isApplying} variant="outline" className={applyButtonClass}>
          {isApplying ? (
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
          ) : (
            <Sparkles className="size-4" />
          )}
          {isApplying ? t('actions.applying') : t("actions.apply")}
        </Button>
      </div>

      <div className={llmPanelClass}>
        <div className="flex items-center justify-between">
          <div className="flex min-w-0 items-center gap-2">
            <span className="flex size-7 items-center justify-center rounded-[0.85rem] bg-accent/[0.08] text-accent ring-1 ring-accent/12">
              <Sparkles className="size-3.5" />
            </span>
            <div className="min-w-0">
              <span className="text-[12px] font-medium text-foreground/80">{t('llm.title')}</span>
              <p className="mt-0.5 truncate text-[10.5px] text-muted-foreground/68">可选二次清洗，默认只执行规则预览</p>
            </div>
          </div>
          <Button variant="outline" size="sm" className={llmToggleClass} onClick={() => setLlmEnabled((value) => !value)}>
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

      <div className={diffPanelClass}>
        <button
          type="button"
          onClick={() => setPreviewDiff((value) => !value)}
          className="flex w-full items-center justify-between px-3 py-2 transition-colors hover:bg-muted/30"
        >
          <span className="flex min-w-0 items-center gap-2">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-[0.85rem] bg-info/[0.07] text-info ring-1 ring-info/12">
              <GitCompare className="size-3.5" />
            </span>
            <span className="min-w-0">
              <span className="block text-[12px] font-semibold leading-4 text-foreground/78">{t('diff.title')}</span>
              <span className="block text-[10.5px] leading-4 text-muted-foreground/62">执行清洗后查看规则命中、文本变化和统一 diff</span>
            </span>
          </span>
          <TextCursorInput className="size-4 text-muted-foreground/70" />
        </button>
        {previewDiff && (
          <div className="max-h-80 space-y-3 overflow-y-auto border-t border-border/48 bg-muted/[0.14] p-3 no-scrollbar overscroll-contain">
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
                        onClick={() => {
                          const patch = lastPreview.suggested_pipeline_patch
                          if (patch) applyPipelinePatch(patch)
                        }}
                      >
                        {t('diff.applySuggestion')}
                      </Button>
                    </div>
                  )}
              </div>
            ) : (
              <div className={emptyStateClass}>
                <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-success" />
                <div>
                  <div className="font-medium text-foreground/72">{t('diff.noIssueHint')}</div>
                  <div className="text-muted-foreground/62">执行智能清洗后，如果规则命中或出现风险提示，会在这里汇总。</div>
                </div>
              </div>
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
              <div className={emptyStateClass}>
                <TextCursorInput className="mt-0.5 size-3.5 shrink-0 text-info" />
                <div>
                  <div className="font-medium text-foreground/72">{t('diff.noDiffHint')}</div>
                  <div className="text-muted-foreground/62">当前还没有生成可比较的清洗结果，点击上方执行后会展示统一 diff。</div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
