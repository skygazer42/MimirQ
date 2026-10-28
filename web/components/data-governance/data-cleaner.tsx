'use client'
import { FeedbackToast } from '@/components/feedback-toast'

import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Wrench } from '@/components/icons'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
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
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { CleanPreviewRuleStatsPanel } from '@/components/governance-profiles/clean-preview-rule-stats-panel'
import styles from './governance-inbox.module.css'
import { computeCleanPreviewImpact } from '@/lib/clean-preview-impact'

const DATA_CLEANER_INPUT_FORMAT_VALUES = ['markdown', 'html'] as const

interface DataCleanerProps {
  content: string
  cleanedContent?: string
  disabled?: boolean
  onConfigure?: () => void
  onClean: (cleaned: string) => void
}

export function DataCleaner({
  content,
  onClean,
  disabled = false,
  onConfigure,
}: Readonly<DataCleanerProps>) {
  const t = useTranslations('DataCleaner')
  const { options, updateOption, setEnabled } = usePipelineOptions()
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
    if (isApplying || disabled || !content.trim()) return
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
  }, [content, disabled, inputFormat, isApplying, llmEnabled, onClean, options, promptTemplateId, t])

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

  return (
    <>
      <div className={styles.toolLine}>
        <div className={styles.toolIdentity}><strong>规则清洗</strong><span>按当前规则生成清洗结果</span></div>
        <div className={styles.toolActions}>
          <Button variant="outline" disabled={isApplying || disabled} onClick={onConfigure}><Wrench className="size-4" />清洗规则</Button>
          <Button onClick={() => void handleApply()} disabled={isApplying || disabled}>{isApplying ? <Loader2 className={styles.spinner} /> : <Wrench className="size-4" />}{isApplying ? '正在清洗…' : '运行清洗'}</Button>
        </div>
      </div>
      <FeedbackToast type="error" message={backendError} id="governance-cleaning-feedback" />
      <div className={styles.toolBody}>
        <div className={styles.formRow}>
          <div className={styles.fieldGroup}>
            <label htmlFor="governance-clean-format">输入格式</label>
            <select className={styles.fieldControl} id="governance-clean-format" value={inputFormat} disabled={isApplying || disabled} onChange={event => setInputFormat(coerceOneOf(DATA_CLEANER_INPUT_FORMAT_VALUES, event.target.value, 'markdown'))}>
              <option value="markdown">Markdown</option><option value="html">HTML</option>
            </select>
          </div>
          <label className={styles.checkControl}><input type="checkbox" checked={llmEnabled} disabled={isApplying || disabled} onChange={event => setLlmEnabled(event.target.checked)} />模型二次清洗</label>
          {llmEnabled && <select className={styles.fieldControl} aria-label="清洗提示词模板" value={promptTemplateId} disabled={isApplying || disabled} onChange={event => setPromptTemplateId(event.target.value)}>
            <option value="">默认提示词</option>{promptTemplates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
          </select>}
        </div>
        {lastPreview && <details className={styles.compactDetails} open>
          <summary>清洗结果{impact ? ' · ' + impact.inputChars.toLocaleString() + ' → ' + impact.outputChars.toLocaleString() + ' 字' : ''}</summary>
          <div>
            {lastPreview.dropped ? <p className="text-xs text-destructive">当前规则会过滤该文档，正文已保留。请调整规则后重试。</p> : <p className="text-xs text-muted-foreground">清洗结果已放入正文，保存后用于切块。</p>}
            {lastPreview.issues?.map(issue => <p key={issue.code} className="mt-2 text-xs leading-6 text-muted-foreground">{issue.message}{issue.count ? ' · ' + issue.count + ' 处' : ''}</p>)}
            {lastPreview.suggested_pipeline_patch && Object.keys(lastPreview.suggested_pipeline_patch).length > 0 && <Button variant="ghost" size="sm" disabled={isApplying || disabled} onClick={() => applyPipelinePatch(lastPreview.suggested_pipeline_patch!)}>应用建议规则</Button>}
            {backendInfo && <details className={styles.compactDetails}><summary>处理记录</summary><pre>{backendInfo}</pre></details>}
            {lastPreview.rule_stats?.length ? <details className={styles.compactDetails}><summary>规则命中记录</summary><CleanPreviewRuleStatsPanel ruleStats={lastPreview.rule_stats} /></details> : null}
            {lastPreview.diff_unified?.trim() && <details className={styles.compactDetails}><summary>查看文本差异{lastPreview.diff_truncated ? '（已截断）' : ''}</summary><pre>{lastPreview.diff_unified}</pre></details>}
          </div>
        </details>}
      </div>
    </>
  )
}
