'use client'
import { FeedbackToast } from '@/components/feedback-toast'

import { useCallback, useEffect, useMemo, useRef, useState, type Ref } from 'react'
import {
  AlertTriangle,
  ChevronRight,
  FileText,
  ListChecks,
  Loader2,
  ScanLine,
  Search,
  Wrench,
} from '@/components/icons'
import { useTranslations } from 'next-intl'
import { pipelineApi } from '@/lib/api/pipeline'
import { reportClientError } from '@/lib/client-logging'
import { Button } from '@/components/ui/button'
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
  onLocateIssue?: (issue: QualityIssue) => void
  onIgnoreIssue?: (issue: QualityIssue) => void
  onCleanRequest?: () => void
  scanButtonRef?: Ref<HTMLButtonElement>
  onScanningChange?: (scanning: boolean) => void
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
  onLocateIssue,
  onIgnoreIssue,
  onCleanRequest,
  scanButtonRef,
  onScanningChange,
}: Readonly<QualityCheckerProps>) {
  const t = useTranslations('QualityChecker')
  const [isScanning, setIsScanning] = useState(false)
  useEffect(() => {
    onScanningChange?.(isScanning)
    return () => onScanningChange?.(false)
  }, [isScanning, onScanningChange])
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
      <div className={styles.healthStrip}>
        <div className={styles.qualityCard} data-tone={checked ? scoreTone : 'pending'}>
          <div className={styles.scoreRing} aria-label={checked ? `数据质量评分 ${initialScore} / 100` : '尚未检测'}>
            <svg viewBox="0 0 100 100" aria-hidden="true">
              <circle className={styles.ringTrack} cx="50" cy="50" r="41" />
              {checked && (
                <circle
                  className={styles.ringProgress}
                  cx="50"
                  cy="50"
                  r="41"
                  pathLength="100"
                  strokeDasharray={`${initialScore} 100`}
                />
              )}
            </svg>
            <span className={styles.scoreValue}>
              <strong>{checked ? initialScore : '—'}</strong>
              <small>/ 100</small>
            </span>
          </div>
          <div className={styles.healthCopy}>
            <strong>{checked ? `文档健康度：${initialScore >= 80 ? '良好' : '需关注'}` : '尚未检测'}</strong>
            <p>
              {checked
                ? initialIssues.length
                  ? `发现 ${initialIssues.length} 项待核对问题，建议处理后入库`
                  : '未发现需要处理的问题，可保存后继续切块'
                : '运行检测后查看结果'}
            </p>
          </div>
        </div>
        <div className={styles.scanActions}>
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
            ref={scanButtonRef}
            variant="outline"
            disabled={isScanning || disabled}
            onClick={() => void handleScan()}
          >
            {isScanning ? <Loader2 className={styles.spinner} /> : <ScanLine className="size-4" />}
            {isScanning ? '正在检测…' : checked ? '重新检测' : '开始检测'}
          </Button>
        </div>
      </div>
      <FeedbackToast type="error" message={error} id="governance-quality-feedback" />
      <div className={styles.toolBody}>
        {checked && (
          <section className={styles.issueSection} aria-label="问题清单">
            <h3>
              <ListChecks className="size-4" />
              问题清单 <span className={styles.count}>({initialIssues.length})</span>
            </h3>
            {initialIssues.length > 0 ? (
              <div className={styles.issueNav} aria-label="检测问题">
                {initialIssues.map((issue) => (
                  <article
                    key={issue.id}
                    className={styles.issueCard}
                    data-severity={issue.type}
                    data-active={activeIssueId === issue.id}
                  >
                    <button
                      type="button"
                      title={issue.message}
                      className={styles.issueButton}
                      aria-pressed={activeIssueId === issue.id}
                      onClick={() => onSelectIssue?.(issue)}
                    >
                      <AlertTriangle aria-hidden="true" />
                      <span className={styles.severity}>
                        {issue.type === 'error' ? '高' : issue.type === 'warning' ? '中' : '低'}
                      </span>
                      <span className={styles.issueMessage}>{issue.message}</span>
                      <ChevronRight aria-hidden="true" />
                    </button>
                    {activeIssueId === issue.id && issue.position && (
                      <pre className={styles.issueExcerpt}>
                        {content.slice(
                          Math.max(0, issue.position.start - 45),
                          Math.min(content.length, issue.position.end + 100),
                        )}
                      </pre>
                    )}
                    <div className={styles.issueActions}>
                      {issue.position && onLocateIssue && (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label="定位到正文"
                          disabled={disabled || isScanning}
                          onClick={() => onLocateIssue(issue)}
                        >
                          <Search className="size-3" />
                          定位
                        </Button>
                      )}
                      {onCleanRequest && (
                        <Button
                          size="sm"
                          variant="outline"
                          aria-label="清洗文档"
                          disabled={disabled || isScanning}
                          onClick={onCleanRequest}
                        >
                          <Wrench className="size-3" />
                          清洗
                        </Button>
                      )}
                      {onIgnoreIssue && (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label="忽略此项"
                          disabled={disabled || isScanning}
                          onClick={() => onIgnoreIssue(issue)}
                        >
                          忽略
                        </Button>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <p className={styles.fieldHint}>未发现需要处理的问题</p>
            )}
          </section>
        )}
        <details className={styles.toolSection} aria-label="字符统计">
          <summary>
            <FileText />
            <span className={styles.statsSummary}>
              {stats.chars.toLocaleString()} 字 · {stats.lines.toLocaleString()} 行 ·{' '}
              {stats.paragraphs.toLocaleString()} 段落 · 中文 {stats.chinese.toLocaleString()}
            </span>
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
      </div>
    </>
  )
}
