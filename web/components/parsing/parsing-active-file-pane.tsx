'use client'

import { useState } from 'react'
import dynamic from 'next/dynamic'
import {
  Blocks,
  Check,
  ChevronRight,
  Clock,
  Code,
  Copy,
  Download,
  Edit3,
  Eye,
  FileStack,
  FileText,
  Heading1,
  Image,
  Layers,
  Loader2,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
  Table2,
  X,
} from 'lucide-react'

import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { ParsingRightPanel } from '@/components/parsing/parsing-right-panel'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { cn } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import type { ParsingBlock } from '@/lib/parsing-positions'

import type { ParsedFile, ParseRun } from './parsing-types'

const ParseCompareDialog = dynamic(
  () => import('@/components/parsing/parse-compare-dialog').then((mod) => mod.ParseCompareDialog),
  {
    loading: () => null,
  }
)

const PdfViewer = dynamic(() => import('@/components/parsing/pdf-viewer').then((mod) => mod.PdfViewer), {
  ssr: false,
  loading: () => <Skeleton className="h-[400px] w-full" />,
})

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function getQualityGateGrade(value: unknown): string {
  if (!isRecord(value) || typeof value.grade !== 'string') return 'pass'
  return value.grade
}

function getQualityGateReasons(value: unknown): string[] {
  if (!isRecord(value) || !Array.isArray(value.reasons)) return []
  return value.reasons.filter((item): item is string => typeof item === 'string')
}

function readBackendName(value: unknown): string | null {
  if (typeof value === 'string') {
    const normalized = value.trim()
    return normalized || null
  }
  if (typeof value === 'number') {
    return String(value)
  }
  return null
}

function getQualityBadgeClass(qualityGrade: string): string {
  if (qualityGrade === 'fail') {
    return 'border-destructive/20 bg-destructive/10 text-destructive'
  }
  if (qualityGrade === 'warn') {
    return 'border-warning/20 bg-warning/10 text-warning'
  }
  return 'border-success/20 bg-success/10 text-success'
}

function buildQualityEvidenceSummary(qualityGate: unknown, pdfQuality: unknown): string {
  const pieces: string[] = []
  const gateEvidence = isRecord(qualityGate) && isRecord(qualityGate.evidence) ? qualityGate.evidence : {}
  const textQuality = isRecord(gateEvidence.text_quality) ? gateEvidence.text_quality : {}
  const parseQuality = isRecord(gateEvidence.parse_quality) ? gateEvidence.parse_quality : {}
  const fallbackAttempts = Array.isArray(gateEvidence.fallback_attempts) ? gateEvidence.fallback_attempts : []

  if (isRecord(pdfQuality) && typeof pdfQuality.score === 'number') {
    pieces.push(`pdf_score=${Number(pdfQuality.score).toFixed(3)}`)
  }
  if (typeof parseQuality.score === 'number') pieces.push(`parse_score=${Number(parseQuality.score).toFixed(3)}`)
  if (typeof textQuality.content_chars === 'number') pieces.push(`content_chars=${textQuality.content_chars}`)
  if (typeof textQuality.density === 'number') pieces.push(`density=${Number(textQuality.density).toFixed(3)}`)
  if (typeof textQuality.replacement_ratio === 'number') {
    pieces.push(`replacement_ratio=${Number(textQuality.replacement_ratio).toFixed(3)}`)
  }
  if (fallbackAttempts.length > 0) {
    const fallbackBackends = [
      readBackendName(gateEvidence.fallback_initial_backend),
      readBackendName(gateEvidence.fallback_final_backend),
    ].filter((value): value is string => value != null)
    if (fallbackBackends.length > 0) {
      pieces.push(`fallback=${fallbackBackends.join('→')}`)
    }
  }

  return pieces.join(' · ')
}

type ParsingActiveFilePaneProps = {
  activeFile: ParsedFile
  activeRun: ParseRun | null
  activeMarkdown: string
  activeQualityGate: unknown
  activePdfQuality: unknown
  activeBlocksWithPositions: ParsingBlock[]
  isPdf: boolean
  tocEnabled: boolean
  previewMode: 'raw' | 'rendered'
  rightPanelMode: 'blocks' | 'markdown'
  isEditing: boolean
  editedContent: string
  copied: boolean
  activeBlockId: string | null
  hoveredBlockId: string | null
  onSelectRun: (runId: string) => void
  onPreviewModeChange: (mode: 'raw' | 'rendered') => void
  onRightPanelModeChange: (mode: 'blocks' | 'markdown') => void
  onStartEdit: () => void
  onCancelEdit: () => void
  onSaveEdit: () => void
  onCopyMarkdown: () => void
  onDownloadMarkdown: () => void
  onParseFile: (fileId: string, backend?: string) => void
  pdfPreviewResetToken: number
  onSetQueueFileParserBackend: (params: { fileId: string; filename: string; backend: string }) => void
  onSubmitToGovernance: () => void
  onEditedContentChange: (value: string) => void
  onActiveBlockIdChange: (blockId: string | null) => void
  onHoveredBlockIdChange: (blockId: string | null) => void
}

export function ParsingActiveFilePane({
  activeFile,
  activeRun,
  activeMarkdown,
  activeQualityGate,
  activePdfQuality,
  activeBlocksWithPositions,
  isPdf,
  tocEnabled,
  previewMode,
  rightPanelMode,
  isEditing,
  editedContent,
  copied,
  activeBlockId,
  hoveredBlockId,
  onSelectRun,
  onPreviewModeChange,
  onRightPanelModeChange,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onCopyMarkdown,
  onDownloadMarkdown,
  onParseFile,
  pdfPreviewResetToken,
  onSetQueueFileParserBackend,
  onSubmitToGovernance,
  onEditedContentChange,
  onActiveBlockIdChange,
  onHoveredBlockIdChange,
}: Readonly<ParsingActiveFilePaneProps>) {
  const [compareOpen, setCompareOpen] = useState(false)
  const pdfViewerKey = `${activeFile.id}:${activeFile.activeRunId || activeRun?.id || 'default'}:${pdfPreviewResetToken}`
  const qualityGrade = getQualityGateGrade(activeQualityGate)
  const qualityReasons = getQualityGateReasons(activeQualityGate)
  const qualityEvidenceSummary = buildQualityEvidenceSummary(activeQualityGate, activePdfQuality)
  const submitToGovernanceButton = isEditing ? null : (
    <Button
      onClick={onSubmitToGovernance}
      className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
    >
      <ShieldCheck className="h-4 w-4" />
      提交到数据治理
      <ChevronRight className="h-4 w-4" />
    </Button>
  )

  return (
    <>
      <ParseCompareDialog
        open={compareOpen}
        onOpenChange={setCompareOpen}
        runs={activeFile.runs || []}
        defaultBaseRunId={activeFile.activeRunId || activeRun?.id || null}
        onUseRun={(runId) => {
          onSelectRun(runId)
          setCompareOpen(false)
        }}
      />

      <>
        {activeFile.status === 'parsed' && activeFile.stats ? (
          <div className="border-b border-border/60 bg-card/70 px-6 py-4 dark:bg-background/40">
            <StatsGrid>
              <StatCard
                icon={FileText}
                label="字符数"
                value={activeFile.stats.charCount.toLocaleString()}
                color="blue"
              />
              <StatCard
                icon={FileStack}
                label="行数"
                value={activeFile.stats.lineCount.toLocaleString()}
                color="cyan"
              />
              <StatCard
                icon={Heading1}
                label="Headings"
                value={(activeFile.stats.headingCount || 0).toLocaleString()}
                color="teal"
              />
              <StatCard
                icon={Layers}
                label="页数"
                value={
                  typeof activeFile.stats.pageCount === 'number' && activeFile.stats.pageCount > 0
                    ? activeFile.stats.pageCount
                    : '-'
                }
                color="sky"
              />
              <StatCard
                icon={Blocks}
                label="定位块"
                value={Math.floor(activeFile.stats.blockCount || 0)}
                color="amber"
              />
              <StatCard
                icon={Table2}
                label="表格"
                value={Math.floor(activeFile.stats.tableCount || 0)}
                color="green"
              />
              <StatCard
                icon={Image}
                label="图片"
                value={activeFile.stats.imageCount || 0}
                color="red"
              />
              <StatCard
                icon={Clock}
                label="耗时"
                value={
                  typeof activeFile.duration === 'number' && Number.isFinite(activeFile.duration)
                    ? `${activeFile.duration}s`
                    : '-'
                }
                subValue={activeFile.parserLabel}
                color="gray"
              />
            </StatsGrid>
            {activeQualityGate ? (
              <div className="mt-3 flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold',
                      getQualityBadgeClass(qualityGrade)
                    )}
                    title="解析质量门禁（best-effort）"
                  >
                    {String(qualityGrade || 'pass').toUpperCase()}
                  </span>
                  <div className="text-xs text-muted-foreground">
                    {qualityReasons.length ? qualityReasons.join(' · ') : '无明显风险信号'}
                  </div>
                </div>
                <div className="font-mono text-[11px] text-muted-foreground">{qualityEvidenceSummary}</div>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="flex items-center justify-between border-b border-border/60 bg-muted/20 px-6 py-3 dark:bg-muted/40">
          <div className="flex items-center gap-3">
            <span className="max-w-[200px] truncate font-medium text-foreground dark:text-foreground">
              {activeFile.file.name}
            </span>
            <span className="rounded bg-muted/60 px-2 py-0.5 text-xs text-muted-foreground dark:bg-muted/60 dark:text-muted-foreground">
              {activeFile.parserLabel}
            </span>
            {activeFile.runs && activeFile.runs.length > 1 ? (
              <select
                value={activeRun?.id || ''}
                onChange={(event) => onSelectRun(event.target.value)}
                className="rounded border border-border bg-card px-2 py-1 text-xs text-foreground/80 dark:border-border dark:bg-muted dark:text-muted-foreground"
              >
                {activeFile.runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.parserLabel} {run.createdAt ? `· ${new Date(run.createdAt).toLocaleTimeString()}` : ''}
                  </option>
                ))}
              </select>
            ) : null}
            {isEditing ? (
              <span className="flex items-center gap-1 rounded bg-sky-100 px-2 py-0.5 text-xs text-sky-700 dark:bg-sky-900/30 dark:text-sky-300">
                <Edit3 className="h-3 w-3" />
                编辑中
              </span>
            ) : null}
          </div>

          <div className="flex items-center gap-2">
            {activeFile.status === 'parsed' ? (
              <>
                {activeFile.runs && activeFile.runs.length > 1 ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCompareOpen(true)}
                    disabled={isEditing}
                    className="gap-1.5"
                  >
                    <FileStack className="h-4 w-4" />
                    对比
                  </Button>
                ) : null}

                {isEditing ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={onCancelEdit}
                      className="gap-1.5 text-muted-foreground"
                    >
                      <X className="h-4 w-4" />
                      取消
                    </Button>
                    <Button onClick={onSaveEdit} size="sm" className="gap-1.5 bg-sky-600 hover:bg-sky-700">
                      <Save className="h-4 w-4" />
                      保存修改
                    </Button>
                  </>
                ) : (
                  <>
                    {rightPanelMode === 'markdown' ? (
                      <div className="mr-2 flex items-center rounded-lg bg-muted p-0.5 dark:bg-muted">
                        <button
                          onClick={() => onPreviewModeChange('rendered')}
                          className={cn(
                            'focus-ring flex items-center gap-1 rounded-md px-3 py-1.5 text-xs transition-colors duration-200 motion-reduce:transition-none',
                            previewMode === 'rendered'
                              ? 'bg-card text-foreground shadow-sm dark:bg-background dark:text-foreground dark:shadow-none'
                              : 'text-muted-foreground hover:text-foreground/80 dark:text-muted-foreground dark:hover:text-muted-foreground'
                          )}
                        >
                          <Eye className="h-3.5 w-3.5" />
                          预览
                        </button>
                        <button
                          onClick={() => onPreviewModeChange('raw')}
                          className={cn(
                            'focus-ring flex items-center gap-1 rounded-md px-3 py-1.5 text-xs transition-colors duration-200 motion-reduce:transition-none',
                            previewMode === 'raw'
                              ? 'bg-card text-foreground shadow-sm dark:bg-background dark:text-foreground dark:shadow-none'
                              : 'text-muted-foreground hover:text-foreground/80 dark:text-muted-foreground dark:hover:text-muted-foreground'
                          )}
                        >
                          <Code className="h-3.5 w-3.5" />
                          源码
                        </button>
                      </div>
                    ) : null}

                    {activeBlocksWithPositions.length > 0 ? (
                      <div className="mr-2 flex items-center rounded-lg bg-muted p-0.5 dark:bg-muted">
                        <button
                          onClick={() => onRightPanelModeChange('blocks')}
                          className={cn(
                            'focus-ring flex items-center gap-1 rounded-md px-3 py-1.5 text-xs transition-colors duration-200 motion-reduce:transition-none',
                            rightPanelMode === 'blocks'
                              ? 'bg-card text-foreground shadow-sm dark:bg-background dark:text-foreground dark:shadow-none'
                              : 'text-muted-foreground hover:text-foreground/80 dark:text-muted-foreground dark:hover:text-muted-foreground'
                          )}
                        >
                          <FileStack className="h-3.5 w-3.5" />
                          版面
                        </button>
                        <button
                          onClick={() => onRightPanelModeChange('markdown')}
                          className={cn(
                            'focus-ring flex items-center gap-1 rounded-md px-3 py-1.5 text-xs transition-colors duration-200 motion-reduce:transition-none',
                            rightPanelMode === 'markdown'
                              ? 'bg-card text-foreground shadow-sm dark:bg-background dark:text-foreground dark:shadow-none'
                              : 'text-muted-foreground hover:text-foreground/80 dark:text-muted-foreground dark:hover:text-muted-foreground'
                          )}
                        >
                          <FileText className="h-3.5 w-3.5" />
                          Markdown
                        </button>
                      </div>
                    ) : null}

                    <Button variant="outline" size="sm" onClick={onStartEdit} className="gap-1.5">
                      <Edit3 className="h-4 w-4" />
                      编辑
                    </Button>

                    <Button variant="outline" size="sm" onClick={onCopyMarkdown} className="gap-1.5">
                      {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
                      {copied ? '已复制' : '复制'}
                    </Button>

                    <Button variant="outline" size="sm" onClick={onDownloadMarkdown} className="gap-1.5">
                      <Download className="h-4 w-4" />
                      下载
                    </Button>
                  </>
                )}
              </>
            ) : null}

            {activeFile.status === 'pending' || activeFile.status === 'error' ? (
              <div className="mr-2 flex items-center gap-2">
                <span className="text-xs font-medium text-muted-foreground">解析方式</span>
                <ParserDropdown
                  value={activeFile.parserBackend}
                  filename={activeFile.file.name}
                  onChange={(backend) =>
                    onSetQueueFileParserBackend({
                      fileId: activeFile.id,
                      filename: activeFile.file.name,
                      backend,
                    })
                  }
                  className="w-56"
                />
              </div>
            ) : null}

            {activeFile.status === 'pending' ? (
              <Button onClick={() => onParseFile(activeFile.id)} className="gap-2 bg-sky-600 hover:bg-sky-700">
                <Sparkles className="h-4 w-4 text-sky-200" />
                开始解析
              </Button>
            ) : null}

            {activeFile.status === 'error' ? (
              <Button onClick={() => onParseFile(activeFile.id)} variant="outline" className="gap-2">
                <RotateCcw className="h-4 w-4" />
                重试
              </Button>
            ) : null}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar">
          {activeFile.status === 'pending' ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-xl bg-sky-100 dark:bg-sky-900/30">
                  <Sparkles className="h-8 w-8 text-sky-700 dark:text-sky-300" />
                </div>
                <p className="mb-2 text-foreground/80 dark:text-muted-foreground">准备就绪</p>
                <p className="text-sm text-muted-foreground dark:text-muted-foreground">
                  先在上方选择解析方式（当前：{activeFile.parserLabel}），再点击开始解析
                </p>
              </div>
            </div>
          ) : null}

          {activeFile.status === 'parsing' ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <div className="relative">
                  <Loader2 className="mx-auto h-12 w-12 animate-spin text-sky-700 motion-reduce:animate-none dark:text-sky-300" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-xs font-medium text-sky-700 dark:text-sky-200">
                      {Math.round(activeFile.progress || 0)}%
                    </span>
                  </div>
                </div>
                <p className="mt-4 text-foreground/80 dark:text-muted-foreground">正在解析...</p>
                <p className="mt-1 text-sm text-muted-foreground dark:text-muted-foreground">{activeFile.parserLabel}</p>
              </div>
            </div>
          ) : null}

          {activeFile.status === 'error' ? (
            <div className="flex h-full items-center justify-center">
              <div className="max-w-md text-center">
                <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-xl bg-destructive/10">
                  <FileText className="h-8 w-8 text-destructive" />
                </div>
                <p className="mb-2 font-medium text-destructive">解析失败</p>
                <p className="text-sm text-muted-foreground dark:text-muted-foreground">{activeFile.error}</p>

                {Array.isArray(activeFile.parseDiagnostics?.suggested_backends) &&
                activeFile.parseDiagnostics.suggested_backends.length > 0 ? (
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    {activeFile.parseDiagnostics.suggested_backends.slice(0, 6).map((backend) => {
                      const resolved = resolveParserBackendForFilename(activeFile.file.name, backend)
                      const label = getParserLabel(resolved.backend)
                      return (
                        <Button
                          key={backend}
                          variant="outline"
                          size="sm"
                          className="gap-2"
                          onClick={() => onParseFile(activeFile.id, backend)}
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                          用 {label} 重试
                        </Button>
                      )
                    })}
                  </div>
                ) : null}

                {activeFile.parseDiagnostics?.pdf_sample ? (
                  <div className="mt-4 text-left">
                    <div className="text-xs text-muted-foreground">
                      PDF 采样
                      {typeof activeFile.parseDiagnostics.pdf_sample.page_count === 'number'
                        ? `（${activeFile.parseDiagnostics.pdf_sample.page_count} 页）`
                        : ''}
                      {activeFile.parseDiagnostics.pdf_sample.is_scanned ? ' · 可能是扫描件（可选文本很少）' : ''}
                    </div>
                    {Array.isArray(activeFile.parseDiagnostics.pdf_sample.samples) &&
                    activeFile.parseDiagnostics.pdf_sample.samples.length > 0 ? (
                      <div className="mt-2 max-h-48 space-y-2 overflow-y-auto overscroll-contain rounded-lg border border-border/50 bg-muted/30 p-2 dark:border-border/60 dark:bg-background/40">
                        {activeFile.parseDiagnostics.pdf_sample.samples.slice(0, 3).map((sample) => (
                          <div
                            key={sample.page}
                            className="rounded-md border border-border/40 bg-card/70 p-2 dark:border-border/60 dark:bg-background/60"
                          >
                            <div className="text-xs text-muted-foreground">
                              页 {sample.page} · {sample.text_chars} 字符
                            </div>
                            {sample.excerpt ? (
                              <div className="mt-1 whitespace-pre-wrap text-xs text-foreground/80 dark:text-muted-foreground">
                                {sample.excerpt}
                              </div>
                            ) : (
                              <div className="mt-1 text-xs italic text-muted-foreground">无可选中文本</div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {activeFile.status === 'parsed' && activeMarkdown ? (
            <div className="h-full">
              {isEditing ? (
                <div className="p-6">
                  <textarea
                    value={editedContent}
                    onChange={(event) => onEditedContentChange(event.target.value)}
                    className="min-h-[500px] w-full resize-none rounded-xl border border-border bg-muted p-4 font-mono text-sm leading-relaxed text-foreground/80 whitespace-pre-wrap focus:border-transparent focus:outline-none focus:ring-2 focus:ring-sky-500 dark:border-border dark:bg-background dark:text-muted-foreground"
                    placeholder="在此编辑内容..."
                    autoFocus
                  />
                </div>
              ) : (
                <div className="flex h-full min-h-[520px] flex-col lg:flex-row">
                  {isPdf ? (
                    <div className="flex-1 min-h-0 h-full w-full border-b border-border/70 bg-muted/70 dark:border-border/60 dark:bg-background/40 lg:w-1/2 lg:border-b-0 lg:border-r relative">
                      <PdfViewer
                        key={pdfViewerKey}
                        file={activeFile.file}
                        blocks={activeBlocksWithPositions}
                        activeBlockIds={activeBlockId ? [activeBlockId] : []}
                        hoveredBlockIds={hoveredBlockId ? [hoveredBlockId] : []}
                      />
                    </div>
                  ) : null}
                  <div className={isPdf ? 'w-full lg:w-1/2' : 'w-full'}>
                    {rightPanelMode === 'blocks' && activeBlocksWithPositions.length > 0 ? (
                      <ParsingRightPanel className="h-full no-scrollbar space-y-4 p-6">
                        {activeBlocksWithPositions
                          .filter((block) => (block.text || '').trim().length > 0)
                          .map((block, idx) => {
                            const pageIndex = block.positions?.[0]?.pages?.[0]
                            const isActive = block.id === activeBlockId
                            return (
                              <button
                                key={block.id}
                                type="button"
                                onClick={() => onActiveBlockIdChange(block.id)}
                                onMouseEnter={() => onHoveredBlockIdChange(block.id)}
                                onMouseLeave={() => onHoveredBlockIdChange(null)}
                                className={cn(
                                  'w-full rounded-xl border p-4 text-left shadow-sm transition dark:shadow-none',
                                  isActive
                                    ? 'border-sky-400 bg-sky-50 dark:border-sky-700/40 dark:bg-sky-950/30'
                                    : 'border-border/50 bg-card hover:border-sky-300 dark:border-border/60 dark:bg-background/40 dark:hover:border-sky-700/40'
                                )}
                              >
                                <div className="mb-2 text-xs text-muted-foreground dark:text-muted-foreground">
                                  块 {idx + 1}
                                  {Number.isFinite(pageIndex) ? ` · 页 ${Number(pageIndex) + 1}` : ''}
                                </div>
                                <div className="prose prose-slate max-w-none prose-headings:text-foreground prose-p:text-foreground/80 prose-a:text-sky-700 prose-code:rounded prose-code:bg-sky-500/10 prose-code:px-1 prose-code:py-0.5 prose-code:text-sky-700 prose-pre:bg-slate-900 prose-table:border-collapse prose-td:border prose-td:border-sky-200 prose-td:p-2 prose-th:border prose-th:border-sky-200 prose-th:bg-sky-500/10 prose-th:p-2 dark:prose-invert dark:prose-headings:text-foreground dark:prose-p:text-muted-foreground dark:prose-a:text-sky-300 dark:prose-code:bg-muted dark:prose-code:text-sky-300 dark:prose-th:border-sky-500/30 dark:prose-th:bg-sky-500/20 dark:prose-td:border-sky-500/30">
                                  <MarkdownRenderer markdown={block.text} />
                                </div>
                              </button>
                            )
                          })}
                      </ParsingRightPanel>
                    ) : (
                      <ParsingRightPanel className="h-full no-scrollbar p-6 parsing-md-scroll">
                        {previewMode === 'rendered' ? (
                          <div className="flex gap-8">
                            <div className="prose prose-slate min-w-0 max-w-none flex-1 prose-headings:text-foreground prose-p:text-foreground/80 prose-a:text-sky-700 prose-code:rounded prose-code:bg-sky-500/10 prose-code:px-1 prose-code:py-0.5 prose-code:text-sky-700 prose-pre:bg-slate-900 prose-table:border-collapse prose-td:border prose-td:border-sky-200 prose-td:p-2 prose-th:border prose-th:border-sky-200 prose-th:bg-sky-500/10 prose-th:p-2 dark:prose-invert dark:prose-headings:text-foreground dark:prose-p:text-muted-foreground dark:prose-a:text-sky-300 dark:prose-code:bg-muted dark:prose-code:text-sky-300 dark:prose-th:border-sky-500/30 dark:prose-th:bg-sky-500/20 dark:prose-td:border-sky-500/30">
                              <MarkdownRenderer markdown={activeMarkdown} autoScrollToHash />
                            </div>
                            {tocEnabled ? (
                              <aside className="hidden w-64 shrink-0 xl:block self-start sticky top-0">
                                <div className="max-h-[calc(100%-2rem)] overflow-y-auto overscroll-contain no-scrollbar rounded-xl border border-border/70 bg-muted/40 p-3 dark:border-border/60 dark:bg-background/40">
                                  <MarkdownToc markdown={activeMarkdown} scrollContainerSelector=".parsing-md-scroll" />
                                </div>
                              </aside>
                            ) : null}
                          </div>
                        ) : (
                          <pre className="whitespace-pre-wrap rounded-xl border border-border bg-muted/70 p-6 font-mono text-sm leading-relaxed text-foreground/80 dark:border-border dark:bg-background/40 dark:text-muted-foreground">
                            {activeMarkdown}
                          </pre>
                        )}
                      </ParsingRightPanel>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {activeFile.status === 'parsed' && activeMarkdown ? (
          <div className="border-t border-border/60 bg-card/70 px-6 py-3 dark:bg-background/40">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-xs text-muted-foreground dark:text-muted-foreground">
                {isEditing ? '编辑完成后点击"保存修改"，然后提交到数据治理' : '确认解析内容无误后，提交到数据治理工作台'}
              </div>
              <div className="flex items-center gap-3">
                {submitToGovernanceButton}
              </div>
            </div>
          </div>
        ) : null}
      </>
    </>
  )
}
