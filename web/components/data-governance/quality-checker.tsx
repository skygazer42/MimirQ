'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Code,
  FileText,
  Info,
  Languages,
  List,
  Play,
  ScanLine,
} from 'lucide-react'
import { useTranslations } from 'next-intl'

import { pipelineApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

interface QualityIssue {
  id: string
  type: 'error' | 'warning' | 'info'
  message: string
  position?: { start: number; end: number }
  fix?: () => void
}

interface QualityCheckerProps {
  content: string
  initialScore?: number
  initialIssues?: QualityIssue[]
  onComplete: (result: { score: number; issues: QualityIssue[] }) => void
}

type CheckItemId = 'chars' | 'encoding' | 'language' | 'format' | 'issues'
type Translate = (key: string, values?: Record<string, string | number>) => string

const CHECK_ITEM_CONFIGS = [
  { id: 'chars', icon: FileText },
  { id: 'encoding', icon: Code },
  { id: 'language', icon: Languages },
  { id: 'format', icon: List },
  { id: 'issues', icon: AlertTriangle },
] as const satisfies ReadonlyArray<{
  id: CheckItemId
  icon: typeof FileText
}>

const UTF8_BOM_CODE_POINT = 0xFEFF

function getLeadingCodePoint(value: string): number | undefined {
  return value.codePointAt(0)
}

function getContentFormat(hasHtml: boolean, hasMarkdown: boolean, t: Translate): string {
  if (hasHtml) return t('format.types.html')
  if (hasMarkdown) return t('format.types.markdown')
  return t('format.types.plainText')
}

function collectLocalQualityIssues(content: string, t: Translate): QualityIssue[] {
  const detectedIssues: QualityIssue[] = []

  const emptyParagraphs = (content.match(/\n\n+/g) || []).length
  if (emptyParagraphs > 5) {
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

  const specialChars = content.match(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g) || []
  if (specialChars.length > 0) {
    detectedIssues.push({
      id: 'special-chars',
      type: 'error',
      message: t('localIssues.specialChars', { count: specialChars.length }),
    })
  }

  const paragraphs = content.split('\n').filter((paragraph) => paragraph.trim().length > 20)
  const duplicates: string[] = []
  const seen = new Set<string>()
  for (const paragraph of paragraphs) {
    const trimmed = paragraph.trim().substring(0, 50)
    if (seen.has(trimmed) && !duplicates.includes(trimmed)) {
      duplicates.push(trimmed)
    }
    seen.add(trimmed)
  }
  if (duplicates.length > 0) {
    detectedIssues.push({
      id: 'duplicates',
      type: 'info',
      message: t('localIssues.duplicates', { count: duplicates.length }),
    })
  }

  const urls = content.match(/https?:\/\/[^\s]+/g) || []
  if (urls.length > 0) {
    detectedIssues.push({
      id: 'urls',
      type: 'info',
      message: t('localIssues.urls', { count: urls.length }),
    })
  }

  return detectedIssues
}

function getBackendIssueType(severity: string | null | undefined): QualityIssue['type'] {
  if (severity === 'error') return 'error'
  if (severity === 'warning') return 'warning'
  return 'info'
}

async function getBackendQualityIssues(
  content: string,
  inputFormat: 'html' | 'markdown',
  t: Translate
): Promise<QualityIssue[]> {
  try {
    const response = await pipelineApi.governanceAnalyze({
      markdown: content,
      input_format: inputFormat,
    })

    const detectedIssues = (response.issues || []).slice(0, 10).map((issue) => {
      const countSuffix =
        typeof issue.count === 'number' && issue.count > 0
          ? t('backendIssues.countSuffix', { count: issue.count })
          : ''

      return {
        id: `backend:${issue.code}`,
        type: getBackendIssueType(issue.severity),
        message: t('backendIssues.detected', { message: `${issue.message}${countSuffix}` }),
      } satisfies QualityIssue
    })

    if (response.suggested_pipeline_patch && Object.keys(response.suggested_pipeline_patch).length > 0) {
      detectedIssues.push({
        id: 'backend:suggested-patch',
        type: 'info',
        message: t('backendIssues.suggestedPatch', {
          count: Object.keys(response.suggested_pipeline_patch).length,
        }),
      })
    }

    return detectedIssues
  } catch (error) {
    console.error('Backend governance analyze failed', error)
    return [
      {
        id: 'backend:failed',
        type: 'info',
        message: t('backendIssues.failed'),
      },
    ]
  }
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
  onComplete,
}: Readonly<QualityCheckerProps>) {
  const t = useTranslations('QualityChecker')
  const checkItems = useMemo(
    () =>
      CHECK_ITEM_CONFIGS.map(({ id, icon }) => ({
        id,
        icon,
        label: t(`checkItems.${id}.label`),
      })),
    [t]
  )
  const [isScanning, setIsScanning] = useState(false)
  const [score, setScore] = useState(initialScore)
  const [issues, setIssues] = useState<QualityIssue[]>(initialIssues)
  const [backendScanEnabled, setBackendScanEnabled] = useState(false)
  const [expandedItems, setExpandedItems] = useState<Set<CheckItemId>>(new Set(['chars']))
  const [scanProgress, setScanProgress] = useState(0)

  const textStats = useMemo(() => {
    const text = content || ''
    const chars = text.length
    const charsNoSpaces = text.replaceAll(/\s/g, '').length
    const words = text.trim() ? text.trim().split(/\s+/).length : 0
    const lines = text.split('\n').length
    const paragraphs = text.split(/\n\n+/).filter((paragraph) => paragraph.trim()).length
    const chineseChars = (text.match(/[\u4e00-\u9fa5]/g) || []).length
    const englishWords = (text.match(/[a-zA-Z]+/g) || []).length
    const numbers = (text.match(/\d+/g) || []).length

    return {
      chars,
      charsNoSpaces,
      words,
      lines,
      paragraphs,
      chineseChars,
      englishWords,
      numbers,
    }
  }, [content])

  const hasBom = useMemo(() => getLeadingCodePoint(content) === UTF8_BOM_CODE_POINT, [content])
  const encoding = useMemo(() => {
    const hasHighByte = [...content].some((char) => (char.codePointAt(0) ?? 0) > 255)
    if (hasBom) return 'UTF-8 (BOM)'
    if (hasHighByte) return 'UTF-8'
    return 'ASCII'
  }, [content, hasBom])

  const language = useMemo(() => {
    const chineseRatio = textStats.chineseChars / (textStats.chars || 1)
    const englishRatio = textStats.englishWords / (textStats.words || 1)

    if (chineseRatio > 0.3) return t('language.simplifiedChinese')
    if (englishRatio > 0.5) return t('language.english')
    return t('language.mixed')
  }, [t, textStats])

  const formatInfo = useMemo(() => {
    const hasMarkdown = /^#{1,6}\s|^\*{1,2}.*?\*{1,2}|^\[.*?\]\(.*?\)/m.test(content)
    const hasHtml = /<[^>]+>/.test(content)
    const hasHeaders = (content.match(/^#{1,6}\s/gm) || []).length
    const hasLists = (content.match(/^\s*[-*+]\s|^\s*\d+\.\s/gm) || []).length
    const hasTables = (content.match(/\|.*\|/g) || []).length > 0

    return {
      format: getContentFormat(hasHtml, hasMarkdown, t),
      hasHeaders,
      hasLists,
      hasTables,
    }
  }, [content, t])

  const handleScan = useCallback(async () => {
    setIsScanning(true)
    setScanProgress(0)

    const steps = [
      { progress: 20, delay: 300 },
      { progress: 40, delay: 300 },
      { progress: 60, delay: 300 },
      { progress: 80, delay: 300 },
      { progress: 100, delay: 200 },
    ]

    for (const step of steps) {
      await new Promise((resolve) => setTimeout(resolve, step.delay))
      setScanProgress(step.progress)
    }

    const detectedIssues = collectLocalQualityIssues(content, t)

    if (backendScanEnabled) {
      detectedIssues.push(
        ...(await getBackendQualityIssues(content, formatInfo.format === t('format.types.html') ? 'html' : 'markdown', t))
      )
    }

    setIssues(detectedIssues)

    const calculatedScore = calculateQualityScore(detectedIssues)
    setScore(calculatedScore)

    if (detectedIssues.length > 0) {
      setExpandedItems((prev) => new Set([...prev, 'issues']))
    }

    setIsScanning(false)
    onComplete({ score: calculatedScore, issues: detectedIssues })
  }, [backendScanEnabled, content, formatInfo.format, onComplete, t])

  const toggleExpanded = useCallback((id: CheckItemId) => {
    setExpandedItems((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const scoreGrade = useMemo(() => {
    if (score >= 90) {
      return { label: t('score.grades.excellent'), tone: 'success', badge: 'border border-success/20 bg-success/10 text-success' }
    }
    if (score >= 75) {
      return { label: t('score.grades.good'), tone: 'info', badge: 'border border-info/20 bg-info/10 text-info' }
    }
    if (score >= 60) {
      return { label: t('score.grades.pass'), tone: 'warning', badge: 'border border-warning/20 bg-warning/10 text-warning' }
    }
    return {
      label: t('score.grades.poor'),
      tone: 'destructive',
      badge: 'border border-destructive/20 bg-destructive/10 text-destructive',
    }
  }, [score, t])

  useEffect(() => {
    if (content && initialScore === 0) {
      void handleScan()
    }
  }, [content, handleScan, initialScore])

  return (
    <div className="space-y-6 p-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ScanLine className="size-5 text-info" />
            <h3 className="font-bold text-foreground">{t("header.title")}</h3>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={backendScanEnabled ? 'default' : 'outline'}
              size="sm"
              onClick={() => setBackendScanEnabled((value) => !value)}
            >
              {backendScanEnabled ? t('actions.backendScanOn') : t('actions.backendScanOff')}
            </Button>
            <Button onClick={handleScan} disabled={isScanning} size="sm" className="gap-2">
              {isScanning ? (
                <>
                  <div className="h-4 w-4 rounded-full border-2 border-primary-foreground/30 border-t-primary-foreground motion-safe:animate-spin motion-reduce:animate-none" />
                  {t('actions.scanning', { progress: scanProgress })}
                </>
              ) : (
                <>
                  <Play className="size-4" />
                  {t("actions.scan")}
                </>
              )}
            </Button>
          </div>
        </div>

        {score > 0 && (
          <div
            className={cn(
              'rounded-xl border-2 p-4',
              scoreGrade.tone === 'success' && 'border-success/30 bg-success/10',
              scoreGrade.tone === 'info' && 'border-info/30 bg-info/10',
              scoreGrade.tone === 'warning' && 'border-warning/30 bg-warning/10',
              scoreGrade.tone === 'destructive' && 'border-destructive/30 bg-destructive/10'
            )}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="mb-1 text-sm text-muted-foreground">{t('score.title')}</div>
                <div className="flex items-baseline gap-2">
                  <span className="text-4xl font-bold text-foreground">{score}</span>
                  <span className="text-sm text-muted-foreground">{t('score.outOf')}</span>
                  <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', scoreGrade.badge)}>
                    {scoreGrade.label}
                  </span>
                </div>
              </div>
              <div
                className={cn(
                  'flex h-16 w-16 items-center justify-center rounded-full border-4',
                  scoreGrade.tone === 'success' && 'border-success/30 bg-success/10',
                  scoreGrade.tone === 'info' && 'border-info/30 bg-info/10',
                  scoreGrade.tone === 'warning' && 'border-warning/30 bg-warning/10',
                  scoreGrade.tone === 'destructive' && 'border-destructive/30 bg-destructive/10'
                )}
              >
                <span
                  className={cn(
                    'text-2xl font-bold',
                    scoreGrade.tone === 'success' && 'text-success',
                    scoreGrade.tone === 'info' && 'text-info',
                    scoreGrade.tone === 'warning' && 'text-warning',
                    scoreGrade.tone === 'destructive' && 'text-destructive'
                  )}
                >
                  {score}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2">
        {checkItems.map((item) => {
          const Icon = item.icon
          const isExpanded = expandedItems.has(item.id)
          const issueCount = issues.filter((issue) => issue.type !== 'info').length

          return (
            <div key={item.id} className="overflow-hidden rounded-xl border border-border">
              <button
                type="button"
                onClick={() => toggleExpanded(item.id)}
                className="flex w-full items-center justify-between p-3 transition-colors hover:bg-muted motion-reduce:transition-none"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted">
                    <Icon className="size-4 text-muted-foreground" />
                  </div>
                  <span className="text-sm font-medium text-foreground/80">{item.label}</span>
                  {item.id === 'issues' && issueCount > 0 && (
                    <span className="rounded-full bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive">
                      {issueCount}
                    </span>
                  )}
                </div>
                {isExpanded ? (
                  <ChevronDown className="size-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="size-4 text-muted-foreground" />
                )}
              </button>

              {isExpanded && (
                <div className="border-t border-border bg-muted/50 p-4 pt-0">
                  {item.id === 'chars' && (
                    <div className="grid grid-cols-2 gap-3">
                      <StatRow label={t('stats.totalCharacters')} value={textStats.chars.toLocaleString()} />
                      <StatRow label={t('stats.charactersNoSpaces')} value={textStats.charsNoSpaces.toLocaleString()} />
                      <StatRow label={t('stats.wordCount')} value={textStats.words.toLocaleString()} />
                      <StatRow label={t('stats.lineCount')} value={textStats.lines.toLocaleString()} />
                      <StatRow label={t('stats.paragraphCount')} value={textStats.paragraphs.toLocaleString()} />
                      <StatRow label={t('stats.chineseCharacters')} value={textStats.chineseChars.toLocaleString()} />
                      <StatRow label={t('stats.englishWords')} value={textStats.englishWords.toLocaleString()} />
                      <StatRow label={t('stats.numberCount')} value={textStats.numbers.toLocaleString()} />
                    </div>
                  )}

                  {item.id === 'encoding' && (
                    <div className="space-y-2">
                      <StatRow label={t('encoding.detectedEncoding')} value={encoding} />
                      <StatRow label={t('encoding.characterRange')} value={t('encoding.basicMultilingualPlane')} />
                      <StatRow label={t('encoding.hasBom')} value={hasBom ? t('shared.yes') : t('shared.no')} />
                    </div>
                  )}

                  {item.id === 'language' && (
                    <div className="space-y-2">
                      <StatRow label={t('language.primaryLanguage')} value={language} />
                      <StatRow
                        label={t('language.chineseRatio')}
                        value={`${((textStats.chineseChars / (textStats.chars || 1)) * 100).toFixed(1)}%`}
                      />
                      <StatRow
                        label={t('language.englishRatio')}
                        value={`${((textStats.englishWords / (textStats.words || 1)) * 100).toFixed(1)}%`}
                      />
                    </div>
                  )}

                  {item.id === 'format' && (
                    <div className="space-y-2">
                      <StatRow label={t('format.documentFormat')} value={formatInfo.format} />
                      <StatRow label={t('format.headingCount')} value={formatInfo.hasHeaders} />
                      <StatRow label={t('format.listCount')} value={formatInfo.hasLists} />
                      <StatRow label={t('format.hasTables')} value={formatInfo.hasTables ? t('shared.yes') : t('shared.no')} />
                    </div>
                  )}

                  {item.id === 'issues' && (
                    <div className="space-y-2">
                      {issues.length === 0 ? (
                        <div className="flex items-center gap-2 py-2 text-sm text-success">
                          <CheckCircle className="size-4" />
                          {t('issues.none')}
                        </div>
                      ) : (
                        issues.map((issue) => (
                          <div
                            key={issue.id}
                            className={cn(
                              'flex items-start gap-2 rounded-lg p-3',
                              issue.type === 'error' && 'border border-destructive/20 bg-destructive/10',
                              issue.type === 'warning' && 'border border-warning/20 bg-warning/10',
                              issue.type === 'info' && 'border border-info/20 bg-info/10'
                            )}
                          >
                            {issue.type === 'error' && (
                              <AlertTriangle className="mt-0.5 size-4 flex-shrink-0 text-destructive" />
                            )}
                            {issue.type === 'warning' && (
                              <AlertTriangle className="mt-0.5 size-4 flex-shrink-0 text-warning" />
                            )}
                            {issue.type === 'info' && <Info className="mt-0.5 size-4 flex-shrink-0 text-info" />}
                            <span
                              className={cn(
                                'text-sm',
                                issue.type === 'error' && 'text-destructive',
                                issue.type === 'warning' && 'text-warning',
                                issue.type === 'info' && 'text-info'
                              )}
                            >
                              {issue.message}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function StatRow({ label, value }: Readonly<{ label: string; value: string | number | boolean }>) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-foreground">{value}</span>
    </div>
  )
}
