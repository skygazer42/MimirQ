'use client'

import type { DocumentAccessMode } from '@/types/common'
import type { ConnectorRunOut, WebCrawlAuthConfig } from '@/types/connectors'
import type { Dataset } from '@/types/datasets'
import { useId, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Loader2 } from '@/components/icons'
import { toast } from 'sonner'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GroupChipsInput } from '@/components/groups/group-chips-input'
import { Button } from '@/components/ui/button'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionRevision } from '@/lib/auth-storage'
import { connectorApi } from '@/lib/api/connectors'
import { BRAND_NAME } from '@/lib/brand'
import { reportClientError } from '@/lib/client-logging'
import { documentAccessModeSchema } from '@/lib/document-access-schema'
import { isOneOf } from '@/lib/one-of'
import type { LoadConnectorRuns } from '@/hooks/use-connector-runs'
import { parseAccessMembers, parseHttpUrls } from './knowledge-import-parsers'

function parsePatterns(raw: string, max: number): string[] {
  const patterns = new Set<string>()
  for (const line of raw.split('\n')) {
    const pattern = line.trim()
    if (pattern === '') continue
    patterns.add(pattern)
    if (patterns.size >= max) break
  }
  return Array.from(patterns)
}

type KnowledgeWebCrawlDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCloseAutoFocus?: (event: Event) => void

  datasets: Dataset[]
  datasetsLoading: boolean
  selectedDatasetId?: string
  datasetDefaultValue: string

  loadDocuments: () => void | Promise<void>
  loadConnectorRuns: LoadConnectorRuns
  onRunCreated?: (run: ConnectorRunOut) => void
}

const WEB_CRAWL_AUTH_TYPES = ['none', 'cookie', 'bearer', 'basic'] as const
const START_URL_LIMIT = 5
const SITEMAP_URL_LIMIT = 10
const MAX_PAGES = 500
const MAX_DEPTH = 10

export function KnowledgeWebCrawlDialog({
  open,
  onOpenChange,
  onCloseAutoFocus,
  datasets,
  datasetsLoading,
  selectedDatasetId,
  datasetDefaultValue,
  loadDocuments,
  loadConnectorRuns,
  onRunCreated,
}: Readonly<KnowledgeWebCrawlDialogProps>) {
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()

  const [startUrls, setStartUrls] = useState('')
  const [filename, setFilename] = useState('')
  const [datasetId, setDatasetId] = useState<string>(datasetDefaultValue)
  const [maxPages, setMaxPages] = useState('50')
  const [maxDepth, setMaxDepth] = useState('3')
  const [sameHostOnly, setSameHostOnly] = useState(true)
  const [includePatterns, setIncludePatterns] = useState('')
  const [excludePatterns, setExcludePatterns] = useState('')
  const [useSitemaps, setUseSitemaps] = useState(false)
  const [sitemapUrls, setSitemapUrls] = useState('')
  const [respectRobots, setRespectRobots] = useState(false)
  const [dedupCanonical, setDedupCanonical] = useState(true)
  const [userAgent, setUserAgent] = useState('')
  const [authType, setAuthType] = useState<WebCrawlAuthConfig['type']>('none')
  const [authCookie, setAuthCookie] = useState('')
  const [authToken, setAuthToken] = useState('')
  const [authUsername, setAuthUsername] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [accessMode, setAccessMode] = useState<DocumentAccessMode>('inherit')
  const [accessMembers, setAccessMembers] = useState('')
  const [accessGroupIds, setAccessGroupIds] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const submissionRef = useRef<{ authRevision: number } | null>(null)
  const formId = useId()
  const startUrlCountId = `${formId}-start-url-count`
  const sitemapUrlCountId = `${formId}-sitemap-url-count`

  useLayoutEffect(() => {
    setSubmitting(false)
    if (open) setDatasetId(selectedDatasetId ?? datasetDefaultValue)
    return () => {
      submissionRef.current = null
    }
  }, [open, selectedDatasetId, datasetDefaultValue])

  const parsedStartUrls = useMemo(() => parseHttpUrls(startUrls, START_URL_LIMIT + 1), [startUrls])
  const parsedSitemapUrls = useMemo(
    () => (useSitemaps ? parseHttpUrls(sitemapUrls, SITEMAP_URL_LIMIT + 1) : []),
    [useSitemaps, sitemapUrls],
  )
  const startUrlsOverLimit = parsedStartUrls.length > START_URL_LIMIT
  const sitemapUrlsOverLimit = parsedSitemapUrls.length > SITEMAP_URL_LIMIT

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!open || submissionRef.current || startUrlsOverLimit || sitemapUrlsOverLimit) return
    if (parsedStartUrls.length === 0) {
      toast.error('请输入至少 1 个 http(s) 种子 URL（每行一个）')
      return
    }

    let auth:
      | { type: 'cookie'; cookie: string }
      | { type: 'bearer'; token: string }
      | { type: 'basic'; username: string; password: string }
      | null = null
    if (authType === 'cookie') {
      const cookie = authCookie.trim()
      if (!cookie) {
        toast.error('请输入 Cookie')
        return
      }
      auth = { type: 'cookie', cookie }
    } else if (authType === 'bearer') {
      const token = authToken.trim()
      if (!token) {
        toast.error('请输入 Bearer token')
        return
      }
      auth = { type: 'bearer', token }
    } else if (authType === 'basic') {
      const username = authUsername.trim()
      const password = authPassword.trim()
      if (!username || !password) {
        toast.error('请输入 Basic 用户名/密码')
        return
      }
      auth = { type: 'basic', username, password }
    }

    const submission = { authRevision: getAuthSessionRevision() }
    submissionRef.current = submission
    const isSameSession = () => submission.authRevision === getAuthSessionRevision()
    const ownsSubmission = () => submissionRef.current === submission && isSameSession()
    setSubmitting(true)
    try {
      const access =
        accessMode === 'inherit'
          ? null
          : {
              mode: accessMode,
              partial_member_list: accessMode === 'partial_members' ? parseAccessMembers(accessMembers) : null,
              partial_group_list: accessMode === 'partial_members' ? accessGroupIds : null,
            }

      const trimmedFilename = filename.trim()
      const trimmedUserAgent = userAgent.trim()
      const run = await connectorApi.createRun({
        connector_id: 'web_crawl',
        dataset_id: datasetId === datasetDefaultValue ? undefined : datasetId,
        config: {
          start_urls: parsedStartUrls,
          max_pages: Number(maxPages),
          max_depth: Number(maxDepth),
          same_host_only: sameHostOnly,
          include_patterns: parsePatterns(includePatterns, 30),
          exclude_patterns: parsePatterns(excludePatterns, 60),
          use_sitemaps: useSitemaps,
          sitemap_urls: parsedSitemapUrls,
          respect_robots: respectRobots,
          dedup_canonical: dedupCanonical,
          user_agent: trimmedUserAgent.length === 0 ? undefined : trimmedUserAgent,
          auth,
          filename: trimmedFilename.length === 0 ? undefined : trimmedFilename,
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
          access,
        },
      })

      for (const refresh of [
        () => loadConnectorRuns({ datasetId: selectedDatasetId }, { selectScope: false }),
        loadDocuments,
      ]) {
        void Promise.resolve()
          .then(() => {
            if (isSameSession()) return refresh()
          })
          .catch((error) => reportClientError('Refresh after website crawl creation failed', error))
      }
      if (!ownsSubmission()) return
      toast.success(`已创建网页爬取任务：${run.id.slice(0, 8)}`, {
        action: onRunCreated
          ? {
              label: '查看任务',
              onClick: () => {
                if (isSameSession()) onRunCreated(run)
              },
            }
          : undefined,
      })
      onOpenChange(false)
      setStartUrls('')
      setFilename('')
      setMaxPages('50')
      setMaxDepth('3')
      setSameHostOnly(true)
      setIncludePatterns('')
      setExcludePatterns('')
      setUseSitemaps(false)
      setSitemapUrls('')
      setRespectRobots(false)
      setDedupCanonical(true)
      setUserAgent('')
      setAuthType('none')
      setAuthCookie('')
      setAuthToken('')
      setAuthUsername('')
      setAuthPassword('')
      setAccessMode('inherit')
      setAccessMembers('')
      setAccessGroupIds([])
    } catch (err: unknown) {
      if (!ownsSubmission()) return
      toast.error(formatApiError(err, '创建网页爬取任务失败'))
    } finally {
      if (submissionRef.current === submission) {
        submissionRef.current = null
        setSubmitting(false)
      }
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen || submissionRef.current === null) onOpenChange(nextOpen)
      }}
    >
      <DialogContent
        onCloseAutoFocus={onCloseAutoFocus}
        showCloseButton={!submitting}
        className="max-h-[calc(100dvh-2rem)] max-w-3xl overflow-y-auto overscroll-contain"
      >
        <DialogHeader>
          <DialogTitle>Website Crawl (Connector)</DialogTitle>
          <DialogDescription>
            Crawl a website and ingest the discovered pages into your dataset (requires URL_INGEST_ENABLED).
          </DialogDescription>
        </DialogHeader>

        <fieldset className="min-w-0 space-y-5" disabled={submitting} aria-busy={submitting}>
          <form id={formId} onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor={`${formId}-start-urls`} className="text-foreground/80">
                Start URLs (one per line, max {START_URL_LIMIT})
              </Label>
              <Textarea
                id={`${formId}-start-urls`}
                value={startUrls}
                onChange={(e) => setStartUrls(e.target.value)}
                placeholder={'https://example.com\nhttps://docs.example.com'}
                className="font-mono min-h-[110px]"
                aria-describedby={startUrlCountId}
                aria-invalid={startUrlsOverLimit}
              />
              {startUrlsOverLimit ? (
                <p id={startUrlCountId} role="alert" className="text-xs text-destructive">
                  Up to {START_URL_LIMIT} start URLs are allowed.
                </p>
              ) : (
                <p id={startUrlCountId} className="text-xs text-muted-foreground">
                  Parsed: {parsedStartUrls.length} URLs
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor={`${formId}-max-pages`} className="text-foreground/80">
                  Max pages
                </Label>
                <Input
                  id={`${formId}-max-pages`}
                  type="number"
                  value={maxPages}
                  onChange={(e) => setMaxPages(e.target.value)}
                  min={1}
                  max={MAX_PAGES}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={`${formId}-max-depth`} className="text-foreground/80">
                  Max depth
                </Label>
                <Input
                  id={`${formId}-max-depth`}
                  type="number"
                  value={maxDepth}
                  onChange={(e) => setMaxDepth(e.target.value)}
                  min={0}
                  max={MAX_DEPTH}
                  required
                />
              </div>
              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground/80">Constraints</div>
                <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={sameHostOnly}
                    onChange={(e) => setSameHostOnly(e.target.checked)}
                    className="accent-primary h-4 w-4"
                  />
                  <span>Same host only</span>
                </label>
              </div>
            </div>
          </form>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor={`${formId}-include-patterns`} className="text-sm font-medium text-foreground/80">
                Include patterns (optional)
              </Label>
              <Textarea
                id={`${formId}-include-patterns`}
                value={includePatterns}
                onChange={(e) => setIncludePatterns(e.target.value)}
                placeholder={'^/docs/.*\n^/help/.*'}
                className="font-mono min-h-[90px]"
              />
              <div className="text-xs text-muted-foreground">One per line, max 30.</div>
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${formId}-exclude-patterns`} className="text-sm font-medium text-foreground/80">
                Exclude patterns (optional)
              </Label>
              <Textarea
                id={`${formId}-exclude-patterns`}
                value={excludePatterns}
                onChange={(e) => setExcludePatterns(e.target.value)}
                placeholder={'^/blog/.*\n.*\\.(png|jpg|svg)$'}
                className="font-mono min-h-[90px]"
              />
              <div className="text-xs text-muted-foreground">One per line, max 60.</div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Discovery options</div>
              <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={useSitemaps}
                    onChange={(e) => setUseSitemaps(e.target.checked)}
                    className="accent-primary h-4 w-4"
                  />
                  <span>Use sitemap.xml / robots Sitemap hints (faster)</span>
                </label>
                <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={respectRobots}
                    onChange={(e) => setRespectRobots(e.target.checked)}
                    className="accent-primary h-4 w-4"
                  />
                  <span>Respect robots.txt (best-effort)</span>
                </label>
                <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={dedupCanonical}
                    onChange={(e) => setDedupCanonical(e.target.checked)}
                    className="accent-primary h-4 w-4"
                  />
                  <span>Dedup by canonical link (best-effort)</span>
                </label>
              </div>
              <div className="text-xs text-muted-foreground">
                Tip: sitemap mode avoids fetching every page just to discover links; the connector still ingests each
                URL.
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor={`${formId}-sitemap-urls`} className="text-foreground/80">
                Sitemap URLs (optional, max {SITEMAP_URL_LIMIT})
              </Label>
              <Textarea
                id={`${formId}-sitemap-urls`}
                value={sitemapUrls}
                onChange={(e) => setSitemapUrls(e.target.value)}
                placeholder={'https://example.com/sitemap.xml\nhttps://example.com/sitemap_index.xml'}
                className="font-mono min-h-[110px]"
                disabled={!useSitemaps}
                aria-describedby={sitemapUrlCountId}
                aria-invalid={sitemapUrlsOverLimit}
              />
              {sitemapUrlsOverLimit ? (
                <p id={sitemapUrlCountId} role="alert" className="text-xs text-destructive">
                  Up to {SITEMAP_URL_LIMIT} sitemap URLs are allowed.
                </p>
              ) : (
                <p id={sitemapUrlCountId} className="text-xs text-muted-foreground">
                  {useSitemaps
                    ? `Parsed: ${parsedSitemapUrls.length} URLs`
                    : 'Enable “Use sitemap” to edit; otherwise the crawler will just follow links from seeds.'}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">User-Agent (optional)</div>
              <Input
                value={userAgent}
                onChange={(e) => setUserAgent(e.target.value)}
                placeholder={`${BRAND_NAME}/1.0 (+web-crawl)`}
              />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Auth</div>
              <Select
                value={authType}
                onValueChange={(value) => {
                  if (isOneOf(WEB_CRAWL_AUTH_TYPES, value)) setAuthType(value)
                }}
              >
                <SelectTrigger className="h-10 bg-background">
                  <SelectValue placeholder="Select auth" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="cookie">Cookie</SelectItem>
                  <SelectItem value="bearer">Bearer</SelectItem>
                  <SelectItem value="basic">Basic</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {authType === 'cookie' ? (
            <div className="space-y-2">
              <Label htmlFor={`${formId}-cookie`} className="text-sm font-medium text-foreground/80">
                Cookie header value
              </Label>
              <Textarea
                id={`${formId}-cookie`}
                value={authCookie}
                onChange={(e) => setAuthCookie(e.target.value)}
                placeholder="session=...; other=..."
                className="font-mono min-h-[90px]"
              />
            </div>
          ) : null}
          {authType === 'bearer' ? (
            <div className="space-y-2">
              <Label htmlFor={`${formId}-token`} className="text-sm font-medium text-foreground/80">
                Bearer token
              </Label>
              <Textarea
                id={`${formId}-token`}
                value={authToken}
                onChange={(e) => setAuthToken(e.target.value)}
                placeholder="eyJhbGciOi..."
                className="font-mono min-h-[90px]"
              />
            </div>
          ) : null}
          {authType === 'basic' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor={`${formId}-username`} className="text-sm font-medium text-foreground/80">
                  Username
                </Label>
                <Input
                  id={`${formId}-username`}
                  value={authUsername}
                  onChange={(e) => setAuthUsername(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={`${formId}-password`} className="text-sm font-medium text-foreground/80">
                  Password
                </Label>
                <Input
                  id={`${formId}-password`}
                  type="password"
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                />
              </div>
            </div>
          ) : null}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Filename override (optional)</div>
              <Input value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="e.g. website.html" />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${formId}-dataset`} className="text-sm font-medium text-foreground/80">
                Target dataset
              </Label>
              <Select value={datasetId} onValueChange={setDatasetId}>
                <SelectTrigger id={`${formId}-dataset`} className="h-10 bg-background">
                  <SelectValue placeholder="Select dataset" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={datasetDefaultValue}>Default (auto)</SelectItem>
                  {datasets.map((ds) => (
                    <SelectItem key={ds.id} value={ds.id}>
                      {ds.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {datasetsLoading ? <div className="text-xs text-muted-foreground">Loading datasets...</div> : null}
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">Document access (optional)</div>
            <Select
              value={accessMode}
              onValueChange={(value) => {
                const result = documentAccessModeSchema.safeParse(value)
                if (result.success) setAccessMode(result.data)
              }}
            >
              <SelectTrigger className="h-10 bg-background">
                <SelectValue placeholder="Select access mode" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="inherit">Inherit dataset</SelectItem>
                <SelectItem value="only_me">Only me</SelectItem>
                <SelectItem value="partial_members">Partial members/groups</SelectItem>
                <SelectItem value="all_team_members">All team members</SelectItem>
              </SelectContent>
            </Select>
            {accessMode === 'partial_members' ? (
              <div className="space-y-4 pt-2">
                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground/80">Allowed groups (optional)</div>
                  <GroupChipsInput
                    value={accessGroupIds}
                    onChange={setAccessGroupIds}
                    placeholder="Select groups (members will inherit access)"
                  />
                </div>

                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground/80">Allowed members (one user_id per line)</div>
                  <Textarea
                    value={accessMembers}
                    onChange={(e) => setAccessMembers(e.target.value)}
                    placeholder={'alice\nbob\ncharlie'}
                    className="font-mono min-h-[110px]"
                  />
                </div>
              </div>
            ) : null}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Parser</div>
              <ParserDropdown value={parserBackend} onChange={setParserBackend} />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Chunk strategy</div>
              <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
            </div>
          </div>

          <PipelineOptionsPanel />

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button
              type="submit"
              form={formId}
              disabled={submitting || startUrlsOverLimit || sitemapUrlsOverLimit}
              className="gap-2"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
              Start
            </Button>
          </div>
        </fieldset>
      </DialogContent>
    </Dialog>
  )
}
