'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { skipToken, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { AlertCircle, Check, ChevronDown, FileText, Loader2, Play, RefreshCw } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { FeedbackToast } from '@/components/feedback-toast'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SearchInput } from '@/components/ui/search-input'
import { Textarea } from '@/components/ui/textarea'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { Link } from '@/i18n/navigation'
import { parsingApi, pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getAuthCacheScope, getAuthSessionKey } from '@/lib/auth-storage'
import { buildCleanPreviewRequestFromGovernanceProfile } from '@/lib/governance-profile-utils'
import { useParsedFiles } from '@/store/use-parsed-files-store'
import type { CleanPreviewResponse, GovernanceProfilePayload } from '@/types'
import {
  localPreviewDocument,
  readPreviewDocument,
  remotePreviewDocument,
  type PreviewDocument,
  type PreviewSource,
} from './preview-source'
import styles from './profiles.module.css'

function DocumentPicker({
  source,
  onSelect,
}: Readonly<{ source: PreviewSource; onSelect: (document: PreviewDocument) => void }>) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const searchInput = useRef<HTMLInputElement>(null)
  const localFiles = useParsedFiles((state) => state.files)
  const list = useInfiniteQuery({
    queryKey: ['governance', 'preview-documents', source.scope],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      parsingApi.listDocuments({ status: 'completed', skip: pageParam, limit: 200 }, { signal }),
    getNextPageParam: (lastPage, _pages, offset) => {
      const nextOffset = offset + lastPage.items.length
      return lastPage.items.length > 0 && nextOffset < lastPage.total ? nextOffset : undefined
    },
    enabled: open,
    retry: false,
  })
  const documents = useMemo(() => {
    const byId = new Map<string, PreviewDocument>()
    for (const page of list.data?.pages ?? [])
      for (const file of page.items) {
        if (file.status === 'completed') byId.set(file.id, remotePreviewDocument(file))
      }
    for (const file of localFiles) {
      const document = localPreviewDocument(file)
      if (document && !byId.has(document.id)) byId.set(document.id, document)
    }
    return [...byId.values()]
  }, [list.data, localFiles])
  const searchQuery = search.trim().toLocaleLowerCase()
  const filtered = documents.filter((document) => document.filename.toLocaleLowerCase().includes(searchQuery))
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={styles.documentTrigger}
          aria-label={source.document ? `更换预览文档，当前 ${source.document.filename}` : '选择已解析文档'}
        >
          <FileText className="icon-ink-source" />
          <span>{source.document?.filename ?? '选择已解析文档'}</span>
          <ChevronDown />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className={styles.documentPicker}
        aria-label="选择已解析文档"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          searchInput.current?.focus()
        }}
      >
        <SearchInput
          ref={searchInput}
          value={search}
          onValueChange={setSearch}
          placeholder="搜索文档名称"
          aria-label="搜索已解析文档"
          inputClassName={styles.search}
        />
        <div className={styles.documentList} aria-busy={list.isFetching}>
          {list.isPending && (
            <p className={styles.sourceStatus} role="status">
              <Loader2 className="animate-spin motion-reduce:animate-none" />
              正在读取文档…
            </p>
          )}
          {list.isError && (
            <div className={styles.sourceError} role="alert">
              <p>{formatApiError(list.error, '文档列表读取失败')}</p>
              <Button
                variant="ghost"
                size="sm"
                disabled={list.isFetching}
                onClick={() => {
                  if (list.isFetchNextPageError) void list.fetchNextPage({ cancelRefetch: false })
                  else void list.refetch()
                }}
              >
                重试文档列表
              </Button>
            </div>
          )}
          {filtered.map((document) => (
            <button
              type="button"
              className={styles.documentOption}
              key={document.id}
              onClick={() => {
                onSelect(document)
                setOpen(false)
              }}
              aria-label={`使用文档 ${document.filename}`}
            >
              <FileText className="icon-ink-source" />
              <span>
                <strong>{document.filename}</strong>
                <small>
                  {document.fileType.replace(/^\./, '').toUpperCase() || '文档'} ·{' '}
                  {document.source === 'knowledge_base' ? '知识库' : '文档解析'}
                </small>
              </span>
              {source.document?.id === document.id && <Check />}
            </button>
          ))}
          {!list.isPending && !list.isError && filtered.length === 0 && (
            <div className={styles.sourceEmpty}>
              <p>
                {list.hasNextPage
                  ? '已加载的文档中没有匹配项'
                  : searchQuery === ''
                    ? '还没有已解析文档'
                    : '没有找到匹配的文档'}
              </p>
              {searchQuery === '' && !list.hasNextPage && <Link href="/parsing">前往文档解析</Link>}
            </div>
          )}
          {list.hasNextPage && (
            <Button
              variant="ghost"
              className="w-full"
              disabled={list.isFetching}
              onClick={() => void list.fetchNextPage({ cancelRefetch: false })}
            >
              {list.isFetchingNextPage ? '正在读取…' : '加载更多文档'}
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

type Props = {
  payload: GovernanceProfilePayload
  source: PreviewSource
  onSourceChange: Dispatch<SetStateAction<PreviewSource>>
}

export function CleaningPreview({ payload, source, onSourceChange }: Readonly<Props>) {
  const [result, setResult] = useState<CleanPreviewResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const previewControllerRef = useRef<AbortController | null>(null)
  const document = source.document
  const content = useQuery({
    queryKey: ['governance', 'preview-content', source.scope, document?.source, document?.id],
    queryFn: document === null ? skipToken : ({ signal }) => readPreviewDocument(document, source.scope, { signal }),
    staleTime: 30_000,
    retry: false,
  })
  const loading = document !== null && content.isPending
  const reading = document !== null && content.isFetching
  const input = document === null ? source.manualInput : (content.data?.text ?? '')
  const formats: Array<'markdown' | 'html'> = payload.input_formats.length ? payload.input_formats : ['markdown']
  const format = document ? 'markdown' : formats.includes(source.manualFormat) ? source.manualFormat : formats[0]
  const disabled = payload.pipeline_patch.governance_enabled === false
  const cancelPreview = useCallback(() => {
    previewControllerRef.current?.abort()
    previewControllerRef.current = null
  }, [])
  const clearResult = useCallback(() => {
    cancelPreview()
    setResult(null)
    setError(null)
    setRunning(false)
  }, [cancelPreview])
  const run = useCallback(async () => {
    if (disabled || input.trim() === '' || getAuthCacheScope() !== source.scope) return
    if (previewControllerRef.current !== null) return

    const controller = new AbortController()
    previewControllerRef.current = controller
    const sessionKey = getAuthSessionKey()
    const isCurrent = () => !controller.signal.aborted && getAuthSessionKey() === sessionKey
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      const response = await pipelineApi.cleanPreview(
        buildCleanPreviewRequestFromGovernanceProfile(payload, input, { inputFormat: format, includeDiff: true }),
        { signal: controller.signal },
      )
      if (isCurrent()) setResult(response)
    } catch (cause) {
      if (isCurrent()) setError(formatApiError(cause, '清洗预览失败，请重试'))
    } finally {
      if (previewControllerRef.current === controller) {
        previewControllerRef.current = null
        setRunning(false)
      }
    }
  }, [disabled, format, input, payload, source.scope])

  useEffect(() => {
    clearResult()
    if (document !== null && content.data !== undefined) void run()
    return cancelPreview
  }, [document, content.data, content.dataUpdatedAt, run, clearResult, cancelPreview])

  return (
    <section
      className={styles.preview}
      aria-labelledby="profile-preview-heading"
      data-document-source={Boolean(document)}
    >
      <div className={styles.sectionHeading}>
        <h3 id="profile-preview-heading">清洗前后对照</h3>
        <div className={styles.previewActions}>
          {document ? (
            <span className={styles.note}>Markdown</span>
          ) : (
            <select
              aria-label="预览输入格式"
              value={format}
              onChange={(event) => {
                clearResult()
                onSourceChange((previous) => ({
                  ...previous,
                  manualFormat: event.target.value === 'html' ? 'html' : 'markdown',
                }))
              }}
            >
              {formats.map((value) => (
                <option key={value} value={value}>
                  {value === 'html' ? 'HTML' : 'Markdown'}
                </option>
              ))}
            </select>
          )}
          <Button
            variant="outline"
            onClick={() => void run()}
            disabled={running || input.trim() === '' || disabled || reading || loading}
          >
            {running ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Play />}
            {running ? '正在预览…' : document ? '重新预览' : '运行预览'}
          </Button>
        </div>
      </div>
      <div className={styles.previewSource}>
        <DocumentPicker
          source={source}
          onSelect={(document) => {
            clearResult()
            onSourceChange((previous) => ({ ...previous, document }))
          }}
        />
        {document && (
          <>
            <Button
              variant="ghost"
              size="icon"
              aria-label="重新读取文档"
              disabled={reading}
              onClick={() => void content.refetch()}
            >
              <RefreshCw className={reading ? 'animate-spin motion-reduce:animate-none' : undefined} />
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                clearResult()
                onSourceChange((previous) => ({ ...previous, document: null }))
              }}
            >
              手动输入
            </Button>
          </>
        )}
        <p className={styles.sourceHint}>
          {document ? '按当前配置预览，不修改已保存文档' : '使用解析结果，或在下方粘贴文本'}
        </p>
      </div>
      {document && (
        <p className={styles.sourceProvenance} data-preview-source>
          {loading
            ? '正在载入解析内容…'
            : content.data
              ? `${content.data.origin} · ${input.length.toLocaleString()} 字符`
              : ''}
        </p>
      )}
      {document && content.isError && (
        <div className={styles.sourceError} role="alert">
          <AlertCircle />
          <p>
            {formatApiError(content.error, '文档内容读取失败')}
            {content.data !== undefined && '。仍显示上次取得的文档内容。'}
          </p>
          <Button variant="outline" onClick={() => void content.refetch()}>
            重试读取文档
          </Button>
        </div>
      )}
      {document && content.data && !loading && !input.trim() && (
        <p className={styles.note} role="status">
          此文档没有可预览的正文，请返回文档解析检查结果。
        </p>
      )}
      {document && !formats.includes('markdown') && (
        <p className={styles.note}>解析结果以 Markdown 预览，HTML 正文提取规则仅用于原始 HTML。</p>
      )}
      {disabled && <p className={styles.note}>此配置已关闭治理清洗，文档将保留原文。</p>}
      <FeedbackToast type="error" message={error} id="profile-cleaning-preview-feedback" />
      {result?.dropped && (
        <p className={styles.warning} role="status">
          文档被当前规则过滤：{result.drop_reason ?? '未达到内容质量要求'}
        </p>
      )}
      <div className={styles.previewPair}>
        <div className={styles.previewColumn}>
          <label htmlFor="profile-preview-input">
            清洗前{document && <span>{content.data?.origin ?? '文档内容'}</span>}
          </label>
          <Textarea
            id="profile-preview-input"
            aria-label="清洗前"
            value={input}
            readOnly={Boolean(document)}
            aria-busy={loading}
            placeholder={
              document ? (loading ? '正在读取文档…' : '文档内容将显示在这里') : '粘贴一段文档，检查当前规则的清洗效果'
            }
            onChange={(event) => {
              clearResult()
              onSourceChange((previous) => ({ ...previous, manualInput: event.target.value }))
            }}
          />
        </div>
        <div className={styles.previewColumn}>
          <div className={styles.outputLabel}>
            清洗后
            <span>
              {result ? (result.changed ? '内容已调整 · 预览' : '内容无变化 · 预览') : document ? '当前配置预览' : ''}
            </span>
          </div>
          <div
            className={styles.previewOutput}
            aria-live="polite"
            aria-busy={running || loading}
            data-profile-preview-output
          >
            {loading ? (
              <p className={styles.sourceStatus}>
                <Loader2 className="animate-spin motion-reduce:animate-none" />
                正在读取文档…
              </p>
            ) : running ? (
              <p className={styles.sourceStatus}>
                <Loader2 className="animate-spin motion-reduce:animate-none" />
                正在生成清洗结果…
              </p>
            ) : result ? (
              result.markdown ? (
                <MarkdownRenderer markdown={result.markdown} enableTocAnchors={false} autoScrollToHash={false} />
              ) : (
                <p className={styles.note}>清洗后的内容为空。</p>
              )
            ) : (
              <p className={styles.note}>
                {document && content.isError ? '重新读取文档后可查看清洗结果。' : '运行预览后，这里显示清洗结果。'}
              </p>
            )}
          </div>
        </div>
      </div>
      {result?.issues?.length ? (
        <details className={styles.previewIssues}>
          <summary>查看 {result.issues.length} 项检查结果</summary>
          <ul>
            {result.issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}>{issue.message}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  )
}
