'use client'
import { FeedbackToast } from '@/components/feedback-toast'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ChevronRight, FileText, ListChecks, Loader2, ScanLine, Wrench } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { pipelineApi } from '@/lib/api/pipeline'
import { reportClientError } from '@/lib/client-logging'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import styles from './governance-inbox.module.css'

type QualityIssue = {
  id: string
  type: 'error' | 'warning' | 'info'
  message: string
  position?: { start: number; end: number }
}
type QualityCheckerProps = {
  content: string
  initialScore?: number
  initialIssues?: QualityIssue[]
  checked?: boolean
  disabled?: boolean
  activeIssueId?: string | null
  resetRevision?: number
  onComplete: (result: { score: number; issues: QualityIssue[] }) => void
  onSelectIssue?: (issue: QualityIssue) => void
  onCleanRequest?: () => void
}

type Translate = (key: string, values?: Record<string, string | number>) => string

function collectLocalQualityIssues(content: string, t: Translate): QualityIssue[] {
  const detectedIssues: QualityIssue[] = []

  const emptyParagraphs = content.match(/\n(?:[ \t]*\n){2,}/g)?.length ?? 0
  if (emptyParagraphs > 0) {
    detectedIssues.push({
      id: 'empty-paragraphs',
      type: 'warning',
      message: t('localIssues.emptyParagraphs', { count: emptyParagraphs }),
    })
  }

  const longParagraphs = content.split('\n\n').filter((paragraph) => paragraph.length > 1000)
  if (longParagraphs.length > 0) {
    detectedIssues.push({
      id: 'long-paragraphs',
      type: 'warning',
      message: t('localIssues.longParagraphs', { count: longParagraphs.length }),
    })
  }

  const specialCharCount = content.match(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g)?.length ?? 0
  if (specialCharCount > 0) {
    detectedIssues.push({
      id: 'special-chars',
      type: 'error',
      message: t('localIssues.specialChars', { count: specialCharCount }),
    })
  }

  const paragraphs = content.split('\n').filter((paragraph) => paragraph.trim().length > 20)
  const duplicates = new Set<string>()
  const seen = new Set<string>()
  for (const paragraph of paragraphs) {
    const trimmed = paragraph.trim().substring(0, 50)
    if (seen.has(trimmed)) duplicates.add(trimmed)
    seen.add(trimmed)
  }
  if (duplicates.size > 0) {
    detectedIssues.push({
      id: 'duplicates',
      type: 'info',
      message: t('localIssues.duplicates', { count: duplicates.size }),
    })
  }

  const urlCount = content.match(/https?:\/\/[^\s]+/g)?.length ?? 0
  if (urlCount > 0) {
    detectedIssues.push({
      id: 'urls',
      type: 'info',
      message: t('localIssues.urls', { count: urlCount }),
    })
  }

  for (const issue of detectedIssues) {
    let match: RegExpMatchArray | null = null
    if (issue.id === 'empty-paragraphs') match = content.match(/\n(?:[ \t]*\n){2,}/)
    if (issue.id === 'special-chars') match = content.match(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/)
    if (issue.id === 'urls') match = content.match(/https?:\/\/[^\s]+/)
    if (match?.index != null) issue.position = { start: match.index, end: match.index + match[0].length }
    if (issue.id === 'duplicates') {
      const seen = new Set<string>()
      let offset = 0
      for (const line of content.split('\n')) {
        if (line.trim().length > 20) {
          const key = line.trim().substring(0, 50)
          if (seen.has(key)) {
            issue.position = { start: offset, end: offset + line.length }
            break
          }
          seen.add(key)
        }
        offset += line.length + 1
      }
    }
  }
  return detectedIssues
}

async function getBackendQualityIssues(
  content: string,
  inputFormat: 'html' | 'markdown',
  t: Translate,
): Promise<QualityIssue[]> {
  const response = await pipelineApi.governanceAnalyze({ markdown: content, input_format: inputFormat })
  if (response.issues === undefined) throw new Error('Governance analysis did not return its issue list')

  const detectedIssues = response.issues.slice(0, 10).map<QualityIssue>((issue) => {
    const label = issue.code === 'pii_email' ? '邮箱地址' : issue.code === 'pii_phone' ? '电话号码' : undefined
    const { count } = issue
    const suffix =
      typeof count === 'number' && count > 0
        ? label === undefined
          ? t('backendIssues.countSuffix', { count })
          : ` · ${count} 处`
        : ''
    return { id: `backend:${issue.code}`, type: issue.severity, message: `${label ?? issue.message}${suffix}` }
  })

  const patch = response.suggested_pipeline_patch
  const patchCount = patch == null ? 0 : Object.keys(patch).length
  if (patchCount > 0) {
    detectedIssues.push({
      id: 'backend:suggested-patch',
      type: 'info',
      message: t('backendIssues.suggestedPatch', { count: patchCount }),
    })
  }
  return detectedIssues
}

function calculateQualityScore(issues: QualityIssue[]): number {
  let calculatedScore = 100

  issues.forEach((issue) => {
    if (issue.type === 'error') calculatedScore -= 15
    if (issue.type === 'warning') calculatedScore -= 5
    if (issue.type === 'info') calculatedScore -= 1
  })

  return Math.max(0, calculatedScore)
}

export function QualityChecker({
  content,
  initialScore = 0,
  initialIssues = [],
  checked = false,
  disabled = false,
  activeIssueId,
  resetRevision = 0,
  onComplete,
  onSelectIssue,
  onCleanRequest,
}: Readonly<QualityCheckerProps>) {
  const t = useTranslations('QualityChecker')
  const [isScanning, setIsScanning] = useState(false)
  const [backendScanEnabled, setBackendScanEnabled] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const activeScanRef = useRef<symbol | null>(null)
  const onCompleteRef = useRef(onComplete)
  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])
  useEffect(() => {
    activeScanRef.current = null
    setIsScanning(false)
    setError(null)
    return () => {
      activeScanRef.current = null
    }
  }, [content, resetRevision])
  const handleScan = useCallback(async () => {
    if (content.trim() === '' || activeScanRef.current !== null || disabled) return
    const scan = Symbol()
    activeScanRef.current = scan
    setIsScanning(true)
    setError(null)
    try {
      const issues = collectLocalQualityIssues(content, t)
      if (backendScanEnabled) {
        try {
          issues.push(...(await getBackendQualityIssues(content, content.includes('<html') ? 'html' : 'markdown', t)))
        } catch (error) {
          if (activeScanRef.current === scan) {
            reportClientError('Backend governance analyze failed', error)
            setError('完整检测未完成，检测服务暂时不可用。可重试，或关闭完整检测后运行基础检查。')
          }
          return
        }
      }
      if (activeScanRef.current !== scan) return
      onCompleteRef.current({ score: calculateQualityScore(issues), issues })
    } finally {
      if (activeScanRef.current === scan) {
        activeScanRef.current = null
        setIsScanning(false)
      }
    }
  }, [backendScanEnabled, content, disabled, t])
  const stats = useMemo(
    () => ({
      chars: content.length,
      charsNoSpaces: content.replace(/\s/g, '').length,
      words: content.trim() ? content.trim().split(/\s+/).length : 0,
      lines: content ? content.split('\n').length : 0,
      paragraphs: content.split(/\n\s*\n/).filter((value) => value.trim()).length,
      chinese: (content.match(/[\u4e00-\u9fff]/g) || []).length,
      english: (content.match(/[a-zA-Z]+/g) || []).length,
      numbers: (content.match(/\d+/g) || []).length,
    }),
    [content],
  )
  const scoreTone = initialScore >= 80 ? 'success' : initialScore >= 60 ? 'warning' : 'danger'
  return (
    <>
      <div className={styles.toolLine}>
        <div className={styles.toolIdentity}>
          <strong>质量检测</strong>
        </div>
        <div className={styles.toolActions}>
          <label className={styles.checkControl}>
            <input
              type="checkbox"
              checked={backendScanEnabled}
              disabled={isScanning || disabled}
              onChange={(event) => setBackendScanEnabled(event.target.checked)}
            />
            完整检测
          </label>
          <Button
            variant={checked ? 'outline' : 'default'}
            disabled={isScanning || disabled}
            onClick={() => void handleScan()}
          >
            {isScanning ? <Loader2 className={styles.spinner} /> : <ScanLine className="size-4" />}
            {isScanning ? '正在检测…' : checked ? '重新检测' : '开始检测'}
          </Button>
          {initialIssues.length > 0 && (
            <Button variant="outline" disabled={disabled || isScanning} onClick={onCleanRequest}>
              <Wrench className="size-4" />
              清洗文档
            </Button>
          )}
        </div>
      </div>
      <FeedbackToast type="error" message={error} id="governance-quality-feedback" />
      <div className={styles.toolBody}>
        <div className={styles.qualityCard} data-tone={checked ? scoreTone : 'pending'}>
          <span>数据质量评分</span>
          <div className={styles.qualitySummary}>
            {checked ? (
              <strong className={cn(styles.score, styles[scoreTone])}>
                {initialScore}
                <small>/ 100</small>
              </strong>
            ) : (
              <strong>尚未检测</strong>
            )}
            <span>
              {checked
                ? initialIssues.length
                  ? initialIssues.length + ' 项待核对'
                  : '未发现问题'
                : '运行检测后查看结果'}
            </span>
          </div>
        </div>
        <details className={styles.toolSection} open>
          <summary>
            <FileText />
            <span>字符统计</span>
            <ChevronRight />
          </summary>
          <dl className={styles.textStats}>
            {(
              [
                ['总字符数', stats.chars],
                ['不含空格', stats.charsNoSpaces],
                ['单词数', stats.words],
                ['行数', stats.lines],
                ['段落数', stats.paragraphs],
                ['中文字符', stats.chinese],
                ['英文单词', stats.english],
                ['数字数量', stats.numbers],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
        </details>
        {checked && (
          <details className={styles.toolSection} open>
            <summary>
              <ListChecks />
              <span>问题识别</span>
              <span className={styles.count}>{initialIssues.length}</span>
              <ChevronRight />
            </summary>
            {initialIssues.length > 0 ? (
              <div className={styles.issueNav} aria-label="检测问题">
                {initialIssues.map((issue) => (
                  <button
                    key={issue.id}
                    type="button"
                    title={issue.message}
                    className={styles.issueButton}
                    aria-pressed={activeIssueId === issue.id}
                    onClick={() => onSelectIssue?.(issue)}
                  >
                    <AlertTriangle
                      className={
                        issue.type === 'error' ? styles.danger : issue.type === 'warning' ? styles.warning : styles.info
                      }
                    />
                    <span>{issue.message}</span>
                    <ChevronRight />
                  </button>
                ))}
              </div>
            ) : (
              <p className={styles.fieldHint}>未发现需要处理的问题</p>
            )}
          </details>
        )}
      </div>
    </>
  )
}
