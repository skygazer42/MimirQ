'use client'

import type { ConnectorRunOut, Dataset, DocumentAccessMode } from '@/types'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GroupChipsInput } from '@/components/groups/group-chips-input'
import { Button } from '@/components/ui/button'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { formatApiError } from '@/lib/api-errors'
import { connectorApi } from '@/lib/api'
import { coerceOneOf } from '@/lib/one-of'
import { detachPromise } from '@/lib/utils'


function parseStartUrls(raw: string): string[] {
  const parts = (raw || '')
    .split(/[\n,;]+/g)
    .map((s) => s.trim())
    .filter(Boolean)
  const out: string[] = []
  const seen = new Set<string>()

  for (const p of parts) {
    if (!/^https?:\/\//i.test(p)) continue
    if (seen.has(p)) continue
    seen.add(p)
    out.push(p)
    if (out.length >= 5) break
  }

  return out
}

function parseSitemapUrls(raw: string): string[] {
  const parts = (raw || '')
    .split(/[\n,;]+/g)
    .map((s) => s.trim())
    .filter(Boolean)
  const out: string[] = []
  const seen = new Set<string>()

  for (const p of parts) {
    if (!/^https?:\/\//i.test(p)) continue
    if (seen.has(p)) continue
    seen.add(p)
    out.push(p)
    if (out.length >= 10) break
  }

  return out
}

function parsePatterns(raw: string, max: number): string[] {
  const parts = (raw || '')
    .split(/\n+/g)
    .map((s) => s.trim())
    .filter(Boolean)
  const out: string[] = []
  const seen = new Set<string>()

  for (const p of parts) {
    if (seen.has(p)) continue
    seen.add(p)
    out.push(p)
    if (out.length >= max) break
  }

  return out
}

function parseAccessMembers(raw: string): string[] {
  const parts = (raw || '')
    .split(/[\n,;]+/g)
    .map((s) => s.trim())
    .filter(Boolean)
  const out: string[] = []
  const seen = new Set<string>()

  for (const p of parts) {
    if (seen.has(p)) continue
    seen.add(p)
    out.push(p)
    if (out.length >= 200) break
  }

  return out
}

type KnowledgeWebCrawlDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void

  datasets: Dataset[]
  datasetsLoading: boolean
  selectedDatasetId?: string
  datasetDefaultValue: string

  loadDocuments: () => void | Promise<void>
  loadConnectorRuns: (params?: { datasetId?: string }) => void | Promise<void>
  onRunCreated?: (run: ConnectorRunOut) => void
}

const WEB_CRAWL_AUTH_TYPES = ['none', 'cookie', 'bearer', 'basic'] as const
const DOCUMENT_ACCESS_MODE_VALUES = ['inherit', 'only_me', 'partial_members', 'all_team_members'] as const

export function KnowledgeWebCrawlDialog({
  open,
  onOpenChange,
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
  const [maxPages, setMaxPages] = useState(50)
  const [maxDepth, setMaxDepth] = useState(3)
  const [sameHostOnly, setSameHostOnly] = useState(true)
  const [includePatterns, setIncludePatterns] = useState('')
  const [excludePatterns, setExcludePatterns] = useState('')
  const [useSitemaps, setUseSitemaps] = useState(false)
  const [sitemapUrls, setSitemapUrls] = useState('')
  const [respectRobots, setRespectRobots] = useState(false)
  const [dedupCanonical, setDedupCanonical] = useState(true)
  const [userAgent, setUserAgent] = useState('')
  const [authType, setAuthType] = useState<'none' | 'cookie' | 'bearer' | 'basic'>('none')
  const [authCookie, setAuthCookie] = useState('')
  const [authToken, setAuthToken] = useState('')
  const [authUsername, setAuthUsername] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [accessMode, setAccessMode] = useState<DocumentAccessMode>('inherit')
  const [accessMembers, setAccessMembers] = useState('')
  const [accessGroupIds, setAccessGroupIds] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setDatasetId(selectedDatasetId || datasetDefaultValue)
  }, [datasetDefaultValue, open, selectedDatasetId])

  const parsedStartUrls = useMemo(() => parseStartUrls(startUrls), [startUrls])
  const parsedSitemapUrls = useMemo(() => parseSitemapUrls(sitemapUrls), [sitemapUrls])

  const handleSubmit = useCallback(async () => {
    if (!parsedStartUrls.length) {
      toast.error('请输入至少 1 个 http(s) 种子 URL（每行一个）')
      return
    }

    let auth: any = null
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

    const nextMaxPages = Number.isFinite(maxPages) ? Math.trunc(maxPages) : 50
    const nextMaxDepth = Number.isFinite(maxDepth) ? Math.trunc(maxDepth) : 3

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

      const run = await connectorApi.createRun({
        connector_id: 'web_crawl',
        dataset_id: datasetId === datasetDefaultValue ? undefined : datasetId,
        config: {
          start_urls: parsedStartUrls,
          max_pages: nextMaxPages,
          max_depth: nextMaxDepth,
          same_host_only: Boolean(sameHostOnly),
          include_patterns: parsePatterns(includePatterns, 30),
          exclude_patterns: parsePatterns(excludePatterns, 60),
          use_sitemaps: Boolean(useSitemaps),
          sitemap_urls: parsedSitemapUrls,
          respect_robots: Boolean(respectRobots),
          dedup_canonical: Boolean(dedupCanonical),
          user_agent: userAgent.trim() ? userAgent.trim() : undefined,
          auth,
          filename: filename.trim() ? filename.trim() : undefined,
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
          access,
        },
      })

      toast.success(`已创建网页爬取任务：${run.id.slice(0, 8)}`, {
        action: onRunCreated
          ? {
              label: '查看任务',
              onClick: () => onRunCreated(run),
            }
          : undefined,
      })
      onOpenChange(false)
      setStartUrls('')
      setFilename('')
      setMaxPages(50)
      setMaxDepth(3)
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
      detachPromise(loadConnectorRuns({ datasetId: selectedDatasetId }))
      detachPromise(loadDocuments())
    } catch (err: any) {
      toast.error(formatApiError(err, '创建网页爬取任务失败'))
    } finally {
      setSubmitting(false)
    }
  }, [
    accessMembers,
    accessGroupIds,
    accessMode,
    authCookie,
    authPassword,
    authToken,
    authType,
    authUsername,
    chunkStrategy,
    datasetDefaultValue,
    datasetId,
    dedupCanonical,
    excludePatterns,
    filename,
    includePatterns,
    loadConnectorRuns,
    loadDocuments,
    maxDepth,
    maxPages,
    onOpenChange,
    parsedSitemapUrls,
    parsedStartUrls,
    parserBackend,
    pipelineOptions,
    pipelineOverridesEnabled,
    respectRobots,
    sameHostOnly,
    selectedDatasetId,
    useSitemaps,
    userAgent,
    onRunCreated,
  ])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Website Crawl (Connector)</DialogTitle>
          <DialogDescription>
            Crawl a website and ingest the discovered pages into your dataset (requires URL_INGEST_ENABLED).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">Start URLs (one per line, max 5)</div>
            <Textarea
              value={startUrls}
              onChange={(e) => setStartUrls(e.target.value)}
              placeholder={'https://example.com\nhttps://docs.example.com'}
              className="font-mono min-h-[110px]"
            />
            <div className="text-xs text-muted-foreground">Parsed: {parsedStartUrls.length} urls</div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Max pages</div>
              <Input
                type="number"
                value={maxPages}
                onChange={(e) => setMaxPages(Number(e.target.value))}
                min={1}
                max={5000}
              />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Max depth</div>
              <Input
                type="number"
                value={maxDepth}
                onChange={(e) => setMaxDepth(Number(e.target.value))}
                min={0}
                max={50}
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
	                /><span>Same host only</span>
	              </label>
	            </div>
	          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Include patterns (optional)</div>
              <Textarea
                value={includePatterns}
                onChange={(e) => setIncludePatterns(e.target.value)}
                placeholder={'^/docs/.*\n^/help/.*'}
                className="font-mono min-h-[90px]"
              />
              <div className="text-xs text-muted-foreground">One per line, max 30.</div>
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Exclude patterns (optional)</div>
              <Textarea
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
	                  /><span>Use sitemap.xml / robots Sitemap hints (faster)</span>
	                </label>
	                <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
	                  <input
	                    type="checkbox"
	                    checked={respectRobots}
	                    onChange={(e) => setRespectRobots(e.target.checked)}
	                    className="accent-primary h-4 w-4"
	                  /><span>Respect robots.txt (best-effort)</span>
	                </label>
	                <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
	                  <input
	                    type="checkbox"
	                    checked={dedupCanonical}
	                    onChange={(e) => setDedupCanonical(e.target.checked)}
	                    className="accent-primary h-4 w-4"
	                  /><span>Dedup by canonical link (best-effort)</span>
	                </label>
	              </div>
              <div className="text-xs text-muted-foreground">
                Tip: sitemap mode avoids fetching every page just to discover links; the connector still ingests each URL.
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Sitemap URLs (optional, max 10)</div>
              <Textarea
                value={sitemapUrls}
                onChange={(e) => setSitemapUrls(e.target.value)}
                placeholder={'https://example.com/sitemap.xml\nhttps://example.com/sitemap_index.xml'}
                className="font-mono min-h-[110px]"
                disabled={!useSitemaps}
              />
              <div className="text-xs text-muted-foreground">
                {useSitemaps
                  ? `Parsed: ${parsedSitemapUrls.length} urls`
                  : 'Enable “Use sitemap” to edit; otherwise the crawler will just follow links from seeds.'}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">User-Agent (optional)</div>
              <Input value={userAgent} onChange={(e) => setUserAgent(e.target.value)} placeholder="MimirQ/1.0 (+web-crawl)" />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Auth</div>
              <Select
                value={authType}
                onValueChange={(value) => setAuthType(coerceOneOf(WEB_CRAWL_AUTH_TYPES, value, 'none'))}
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
              <div className="text-sm font-medium text-foreground/80">Cookie header value</div>
              <Textarea
                value={authCookie}
                onChange={(e) => setAuthCookie(e.target.value)}
                placeholder="session=...; other=..."
                className="font-mono min-h-[90px]"
              />
            </div>
          ) : null}
          {authType === 'bearer' ? (
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Bearer token</div>
              <Textarea
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
                <div className="text-sm font-medium text-foreground/80">Username</div>
                <Input value={authUsername} onChange={(e) => setAuthUsername(e.target.value)} />
              </div>
              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground/80">Password</div>
                <Input type="password" value={authPassword} onChange={(e) => setAuthPassword(e.target.value)} />
              </div>
            </div>
          ) : null}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Filename override (optional)</div>
              <Input value={filename} onChange={(e) => setFilename(e.target.value)} placeholder="e.g. website.html" />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Target dataset</div>
              <Select value={datasetId} onValueChange={setDatasetId}>
                <SelectTrigger className="h-10 bg-background">
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
              onValueChange={(value) => setAccessMode(coerceOneOf(DOCUMENT_ACCESS_MODE_VALUES, value, 'inherit'))}
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
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={submitting} className="gap-2">
              {submitting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
              Start
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
