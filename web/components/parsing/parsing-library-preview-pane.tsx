'use client'

import { useState, type ReactElement } from 'react'
import { FileText, Paperclip, Play } from '@/components/icons'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import styles from './parsing-compare.module.css'
import { useTranslations } from 'next-intl'

import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { ParsingRightPanel } from '@/components/parsing/parsing-right-panel'
import { ParsingQualityNotice } from './parsing-quality-notice'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import type { ParsedFileData } from '@/store/use-parsed-files-store'

type ParsingLibraryPreviewPaneProps = {
  file: ParsedFileData
  activeMarkdown: string
  contentFeedback: ReactElement | null
  isContentLoading: boolean
  hasContent: boolean
  qualityGate: unknown
  pdfQuality: unknown
  sourceStatus: 'unknown' | 'available' | 'missing'
  sourceFeedback: ReactElement | null
  isSourceChecking: boolean
  defaultParserBackend: string
  onUpdateParser: (backend: string) => void
  onReprocessKnowledgeFile: (backend: string) => void
  onRestoreSource: (autoParse: boolean) => void
  onRequestRebind: (autoParse: boolean) => void
}

type PreviewAction = {
  label: string
  title: string
  onClick: () => void
}

export function ParsingLibraryPreviewPane({
  file,
  activeMarkdown,
  contentFeedback,
  isContentLoading,
  hasContent,
  qualityGate,
  pdfQuality,
  sourceStatus,
  sourceFeedback,
  isSourceChecking,
  defaultParserBackend,
  onUpdateParser,
  onReprocessKnowledgeFile,
  onRestoreSource,
  onRequestRebind,
}: Readonly<ParsingLibraryPreviewPaneProps>) {
  const t = useTranslations('ParsingWorkbench')
  const [narrowView, setNarrowView] = useState<'source' | 'result'>('result')
  const parserValue = resolveParserBackendForFilename(file.filename, file.parserBackend ?? defaultParserBackend).backend
  const isKnowledgeBaseFile = file.source === 'knowledge_base'
  const canOpenSource =
    sourceStatus === 'available' ||
    (sourceStatus === 'unknown' && file.source !== undefined && sourceFeedback === null && !isSourceChecking)
  const canRunLibraryParse = file.status === 'pending' || file.status === 'error'
  const hasPreview = hasContent || activeMarkdown.length > 0
  let resultStatusLabel: string
  if (hasPreview) {
    resultStatusLabel = `${activeMarkdown.length.toLocaleString()} 字符`
    if (isContentLoading) resultStatusLabel += ' · 正在刷新正文'
  } else if (isContentLoading) {
    resultStatusLabel = '正在读取正文'
  } else if (contentFeedback !== null) {
    resultStatusLabel = '正文读取失败'
  } else if (file.status === 'error') {
    resultStatusLabel = '解析失败'
  } else if (file.status === 'parsing') {
    resultStatusLabel = '正在解析'
  } else {
    resultStatusLabel = '等待解析结果'
  }
  let pendingParseAction: PreviewAction | null = null
  if (canRunLibraryParse) {
    if (isKnowledgeBaseFile) {
      pendingParseAction = {
        label: t('libraryPreview.startParsing'),
        title: t('libraryPreview.startParsingTitle'),
        onClick: () => onReprocessKnowledgeFile(parserValue),
      }
    } else if (canOpenSource) {
      pendingParseAction = {
        label: t('libraryPreview.continueParsing'),
        title: t('libraryPreview.continueParsingTitle'),
        onClick: () => onRestoreSource(true),
      }
    } else if (sourceStatus === 'missing' || sourceFeedback !== null) {
      pendingParseAction = {
        label: t('libraryPreview.associateAndParse'),
        title: t('libraryPreview.associateAndParseTitle'),
        onClick: () => onRequestRebind(true),
      }
    }
  }

  let sourceAction: PreviewAction | null = null
  if (canOpenSource) {
    sourceAction = {
      label: t('libraryPreview.restoreSource'),
      title: t('libraryPreview.restoreSourceTitle'),
      onClick: () => onRestoreSource(false),
    }
  } else if (sourceStatus === 'missing' || sourceFeedback !== null) {
    sourceAction = {
      label: t('libraryPreview.associateSource'),
      title: t('libraryPreview.associateSourceTitle'),
      onClick: () => onRequestRebind(false),
    }
  }

  let sourceTitle: string
  let sourceDescription: string
  if (sourceFeedback !== null) {
    sourceTitle = '原文件检查失败'
    sourceDescription = '可重试检查，或重新关联原文件后对照查看。'
  } else if (sourceStatus === 'missing') {
    sourceTitle = '原文件暂不可用'
    sourceDescription = '重新关联原文件后，可以并排核对解析结果。'
  } else if (canOpenSource) {
    sourceTitle = '打开原文件'
    sourceDescription = '打开原文件后，可以并排核对解析结果。'
  } else {
    sourceTitle = '原文件状态尚未读取'
    sourceDescription = '读取原文件状态后，可以对照查看。'
  }

  return (
    <>
      <div className={styles.mobileTabs} role="group" aria-label="核对视图">
        <span
          className={styles.mobileIndicator}
          style={{ transform: narrowView === 'source' ? 'translateX(0)' : 'translateX(100%)' }}
        />
        <button type="button" aria-pressed={narrowView === 'source'} onClick={() => setNarrowView('source')}>
          原文
        </button>
        <button type="button" aria-pressed={narrowView === 'result'} onClick={() => setNarrowView('result')}>
          解析结果
        </button>
      </div>
      <div className={styles.workspace} data-narrow-view={narrowView}>
        <section className={styles.source} aria-label="原文">
          <div className={styles.resultToolbar}>
            <FileText className="size-3.5 text-muted-foreground" />
            <span className="text-[13px]">原始文件</span>
          </div>
          {sourceStatus === 'unknown' && isSourceChecking && sourceFeedback === null ? (
            <div className={styles.resourceBody} aria-busy="true">
              <p role="status" className="p-4 text-sm text-muted-foreground">
                正在检查原文件
              </p>
            </div>
          ) : (
            <div className={styles.empty}>
              <FileTypeIcon filename={file.filename} className="size-10" />
              <h2>{sourceTitle}</h2>
              <p>{sourceDescription}</p>
              {sourceFeedback}
              {sourceAction !== null ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={sourceAction.onClick}
                  title={sourceAction.title}
                  className="gap-2"
                >
                  <Paperclip className="size-4" />
                  {sourceAction.label}
                </Button>
              ) : null}
              {canOpenSource ? (
                <Button
                  size="sm"
                  variant="ghost"
                  title={t('libraryPreview.associateSourceTitle')}
                  onClick={() => onRequestRebind(false)}
                >
                  {t('libraryPreview.associateSource')}
                </Button>
              ) : null}
            </div>
          )}
        </section>
        <section className={styles.result} aria-label="解析结果">
          <div className={styles.resultToolbar}>
            <span className="text-[13px]">Markdown</span>
            <span className="ml-auto text-xs text-muted-foreground">{file.parser}</span>
          </div>
          {file.status === 'parsing' && hasPreview ? (
            <p role="status" className="shrink-0 border-b border-border px-4 py-2 text-xs text-muted-foreground">
              正在解析，当前显示上次保存的正文。
            </p>
          ) : null}
          {file.status === 'error' && hasPreview ? (
            <div
              role="alert"
              className="shrink-0 break-words border-b border-border px-4 py-2 text-xs text-destructive"
            >
              <p>{file.error ?? '解析失败，请重试。'}</p>
              {pendingParseAction ? (
                <Button size="sm" variant="ghost" onClick={pendingParseAction.onClick}>
                  {pendingParseAction.label}
                </Button>
              ) : null}
            </div>
          ) : null}
          {contentFeedback}
          {file.status === 'parsed' && hasPreview ? (
            <ParsingQualityNotice qualityGate={qualityGate} pdfQuality={pdfQuality} />
          ) : null}
          {activeMarkdown.length > 0 ? (
            <ParsingRightPanel className={styles.markdownBody} aria-busy={isContentLoading}>
              <article className={styles.markdown}>
                <MarkdownRenderer markdown={activeMarkdown} />
              </article>
            </ParsingRightPanel>
          ) : hasPreview ? (
            <div className={styles.resultState} aria-busy={isContentLoading}>
              <FileText className="size-7 text-muted-foreground" />
              <h2>正文为空</h2>
            </div>
          ) : isContentLoading ? (
            <ParsingRightPanel className={styles.markdownBody} aria-busy="true">
              <p role="status" className="sr-only">
                正在读取解析正文
              </p>
              <div className="space-y-3 p-4">
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-4/5" />
              </div>
            </ParsingRightPanel>
          ) : contentFeedback !== null ? null : (
            <div className={styles.resultState}>
              {file.status === 'parsing' ? (
                <>
                  <FileText className="size-7 text-info" />
                  <h2>正在解析</h2>
                </>
              ) : (
                <>
                  <FileText className="size-7 text-muted-foreground" />
                  <h2>{file.status === 'error' ? '解析失败' : '文档待解析'}</h2>
                  {file.status === 'error' && file.error ? <p>{file.error}</p> : null}
                  {canRunLibraryParse ? (
                    <div className={styles.startParser}>
                      <ParserDropdown value={parserValue} filename={file.filename} onChange={onUpdateParser} />
                    </div>
                  ) : null}
                  {pendingParseAction ? (
                    <Button
                      size="sm"
                      className="gap-2"
                      onClick={pendingParseAction.onClick}
                      title={pendingParseAction.title}
                    >
                      <Play className="size-4" />
                      {pendingParseAction.label}
                    </Button>
                  ) : null}
                </>
              )}
            </div>
          )}
        </section>
      </div>
      <footer className={styles.footer}>
        <span>{resultStatusLabel}</span>
        {sourceAction !== null ? (
          <Button
            size="sm"
            variant="outline"
            className="gap-2"
            onClick={sourceAction.onClick}
            title={sourceAction.title}
          >
            <Paperclip className="size-4" />
            {sourceAction.label}
          </Button>
        ) : null}
      </footer>
    </>
  )
}
