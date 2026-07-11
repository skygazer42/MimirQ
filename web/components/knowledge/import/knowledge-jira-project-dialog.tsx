'use client'

import type { ConnectorRunOut, Dataset, DocumentAccessMode, WebCrawlAuthConfig } from '@/types'
import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GroupChipsInput } from '@/components/groups/group-chips-input'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { buildJiraProjectRunPayload } from './knowledge-jira-project-dialog.payload'
import { detachPromise, trimTrailingSlashes } from '@/lib/utils'


type KnowledgeJiraProjectDialogProps = {
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

const JIRA_SYNC_MODE_VALUES = ['auto', 'full', 'incremental'] as const
const JIRA_AUTH_TYPE_VALUES = ['none', 'cookie', 'bearer', 'basic'] as const
const SOURCE_ACL_FALLBACK_MODE_VALUES = ['only_me', 'partial_members'] as const
const DOCUMENT_ACCESS_MODE_VALUES = ['inherit', 'only_me', 'partial_members', 'all_team_members'] as const

export function KnowledgeJiraProjectDialog({
  open,
  onOpenChange,
  datasets,
  datasetsLoading,
  selectedDatasetId,
  datasetDefaultValue,
  loadDocuments,
  loadConnectorRuns,
  onRunCreated,
}: Readonly<KnowledgeJiraProjectDialogProps>) {
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()

  const [baseUrl, setBaseUrl] = useState('https://example.atlassian.net')
  const [projectKey, setProjectKey] = useState('')
  const [jql, setJql] = useState('')
  const [datasetId, setDatasetId] = useState<string>(datasetDefaultValue)
  const [syncMode, setSyncMode] = useState<'auto' | 'full' | 'incremental'>('auto')
  const [maxIssues, setMaxIssues] = useState(50)
  const [pageSize, setPageSize] = useState(25)
  const [includeComments, setIncludeComments] = useState(true)
  const [maxCommentsPerIssue, setMaxCommentsPerIssue] = useState(20)
  const [userAgent, setUserAgent] = useState('')
  const [authType, setAuthType] = useState<WebCrawlAuthConfig['type']>('none')
  const [authCookie, setAuthCookie] = useState('')
  const [authToken, setAuthToken] = useState('')
  const [authUsername, setAuthUsername] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [accessMode, setAccessMode] = useState<DocumentAccessMode>('inherit')
  const [accessMembers, setAccessMembers] = useState('')
  const [accessGroupIds, setAccessGroupIds] = useState<string[]>([])
  const [sourceAclEnabled, setSourceAclEnabled] = useState(false)
  const [sourceAclFallbackMode, setSourceAclFallbackMode] = useState<'only_me' | 'partial_members'>('partial_members')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setDatasetId(selectedDatasetId || datasetDefaultValue)
  }, [datasetDefaultValue, open, selectedDatasetId])

  const effectiveChunkStrategy = chunkStrategy === 'langchain_recursive' ? 'jira_ticket' : chunkStrategy
  const hasManualAccessOverride = accessMode !== 'inherit'

  const handleSubmit = useCallback(async () => {
    const trimmedBaseUrl = trimTrailingSlashes(baseUrl)
    const trimmedProjectKey = projectKey.trim().toUpperCase()

    if (!/^https?:\/\//i.test(trimmedBaseUrl)) {
      toast.error('请输入有效的 Jira Base URL（http/https）')
      return
    }
    if (!trimmedProjectKey) {
      toast.error('请输入 Project Key')
      return
    }

    let auth: WebCrawlAuthConfig | null = null
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
        toast.error('请输入 Jira Basic 用户名/密码')
        return
      }
      auth = { type: 'basic', username, password }
    }

    setSubmitting(true)
    try {
      const run = await connectorApi.createRun(
        buildJiraProjectRunPayload({
          datasetId: datasetId,
          datasetDefaultValue,
          baseUrl: trimmedBaseUrl,
          projectKey: trimmedProjectKey,
          jql,
          auth,
          syncMode,
          maxIssues,
          pageSize,
          includeComments,
          maxCommentsPerIssue,
          userAgent,
          parserBackend,
          chunkStrategy: effectiveChunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
          accessMode,
          accessMembers,
          accessGroupIds,
          sourceAclEnabled,
          sourceAclFallbackMode,
        })
      )

      toast.success(`已创建 Jira 导入任务：${run.id.slice(0, 8)}`, {
        action: onRunCreated
          ? {
              label: '查看任务',
              onClick: () => onRunCreated(run),
            }
          : undefined,
      })
      onOpenChange(false)
      setProjectKey('')
      setJql('')
      setSyncMode('auto')
      setMaxIssues(50)
      setPageSize(25)
      setIncludeComments(true)
      setMaxCommentsPerIssue(20)
      setUserAgent('')
      setAuthType('none')
      setAuthCookie('')
      setAuthToken('')
      setAuthUsername('')
      setAuthPassword('')
      setAccessMode('inherit')
      setAccessMembers('')
      setAccessGroupIds([])
      setSourceAclEnabled(false)
      setSourceAclFallbackMode('partial_members')
      detachPromise(loadConnectorRuns({ datasetId: selectedDatasetId }))
      detachPromise(loadDocuments())
    } catch (err: unknown) {
      toast.error(formatApiError(err, '创建 Jira 导入任务失败'))
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
    baseUrl,
    datasetDefaultValue,
    datasetId,
    effectiveChunkStrategy,
    includeComments,
    jql,
    loadConnectorRuns,
    loadDocuments,
    maxCommentsPerIssue,
    maxIssues,
    onOpenChange,
    onRunCreated,
    pageSize,
    parserBackend,
    pipelineOptions,
    pipelineOverridesEnabled,
    projectKey,
    selectedDatasetId,
    sourceAclEnabled,
    sourceAclFallbackMode,
    syncMode,
    userAgent,
  ])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Jira Project (Connector)</DialogTitle>
          <DialogDescription>
            从 Jira Cloud 项目拉取 issue 并入库（支持增量更新；需要后端开启 URL_INGEST_ENABLED）。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Jira Base URL</div>
              <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://example.atlassian.net" />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Project Key</div>
              <Input value={projectKey} onChange={(e) => setProjectKey(e.target.value.toUpperCase())} placeholder="PLAT" />
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">JQL Filter（可选）</div>
            <Textarea
              value={jql}
              onChange={(e) => setJql(e.target.value)}
              placeholder={'statusCategory != Done\nassignee = currentUser()'}
              className="font-mono min-h-[90px]"
            />
            <div className="text-xs text-muted-foreground">会自动附加到 `project = &lt;KEY&gt;` 后面，用于进一步收窄同步范围。</div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Sync mode</div>
              <Select
                value={syncMode}
                onValueChange={(value) => setSyncMode(coerceOneOf(JIRA_SYNC_MODE_VALUES, value, 'auto'))}
              >
                <SelectTrigger className="h-10 bg-background">
                  <SelectValue placeholder="选择同步模式" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto</SelectItem>
                  <SelectItem value="full">Full</SelectItem>
                  <SelectItem value="incremental">Incremental</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Max issues</div>
              <Input type="number" value={maxIssues} onChange={(e) => setMaxIssues(Number(e.target.value))} min={1} max={500} />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Page size</div>
              <Input type="number" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))} min={1} max={100} />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Comments per issue</div>
              <Input
                type="number"
                value={maxCommentsPerIssue}
                onChange={(e) => setMaxCommentsPerIssue(Number(e.target.value))}
                min={0}
                max={200}
                disabled={!includeComments}
              />
            </div>
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/10 px-4 py-3 text-xs text-muted-foreground">
            <div className="font-medium text-foreground/80">同步模式说明</div>
            <div className="mt-1">Auto 会在首次运行做全量同步，之后复用 `last_modified` 游标做增量。</div>
            <div className="mt-1">Full 会重新枚举项目 issue，并尽力对账已删除或已不可见的 Jira issue。</div>
            <div className="mt-1">Incremental 更快，但不会回收本次列表中未出现的旧 issue 文档。</div>
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
            <div className="flex items-center gap-3">
              <Checkbox checked={includeComments} onCheckedChange={(v) => setIncludeComments(v === true)} />
              <div>
                <div className="text-sm font-medium text-foreground/90">Include comments</div>
                <div className="text-xs text-muted-foreground">将 issue comment 一并渲染进 Jira ticket 文档，便于问答和审计追踪。</div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">User-Agent（可选）</div>
              <Input value={userAgent} onChange={(e) => setUserAgent(e.target.value)} placeholder="MimirQ/1.0 (+jira_project)" />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Auth</div>
              <Select
                value={authType}
                onValueChange={(value) => setAuthType(coerceOneOf(JIRA_AUTH_TYPE_VALUES, value, 'none'))}
              >
                <SelectTrigger className="h-10 bg-background">
                  <SelectValue placeholder="选择鉴权方式" />
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

          <div className="rounded-xl border border-border/60 bg-muted/20 px-4 py-4 space-y-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/90">Source ACL（高级）</div>
	              <div className="text-xs text-muted-foreground">
	                启用后，Jira connector 会尝试继承 issue 的安全级别、角色和 comment 可见性，并按{' '}
	                <code>tenant_groups.external_id</code> 进行组匹配，例如{' '}
	                <code>jira:policy:security-level/10001</code>、<code>jira:role:developers</code> 或{' '}
	                <code>jira:group:jira-software-users</code>。
	              </div>
              <div className="text-xs text-muted-foreground">
                为避免误开放访问，当前 UI 只暴露可解释的继承模式和回退策略；更危险的手工映射规则仍保持隐藏。
              </div>
            </div>

            <div className="rounded-lg border border-border/60 bg-background/70 px-4 py-3">
              <div className="flex items-start gap-3">
                <Checkbox
                  checked={sourceAclEnabled}
                  onCheckedChange={(v) => setSourceAclEnabled(v === true)}
                  disabled={hasManualAccessOverride}
                />
                <div className="space-y-1">
                  <div className="text-sm font-medium text-foreground/90">继承 Jira 可见性</div>
                  <div className="text-xs text-muted-foreground">
                    仅在“文档访问控制”保持“继承数据集”时生效；这样不会和手工访问控制发生冲突。
                  </div>
                  {hasManualAccessOverride ? (
                    <div className="text-xs text-warning dark:text-amber-300">
                      当前选择了手工文档访问控制，运行时会忽略 Source ACL。
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground/80">未映射 Jira ACL 时</div>
                <Select
                  value={sourceAclFallbackMode}
                  onValueChange={(value) => setSourceAclFallbackMode(coerceOneOf(SOURCE_ACL_FALLBACK_MODE_VALUES, value, 'partial_members'))}
                  disabled={!sourceAclEnabled || hasManualAccessOverride}
                >
                  <SelectTrigger className="h-10 bg-background">
                    <SelectValue placeholder="选择回退策略" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="partial_members">失败关闭（仅映射出的成员/组）</SelectItem>
                    <SelectItem value="only_me">仅同步执行者可见</SelectItem>
                  </SelectContent>
                </Select>
                <div className="text-xs text-muted-foreground">
                  推荐保持“失败关闭”。如果 Jira ACL 无法映射到租户组，文档不会自动向更大范围开放。
                </div>
              </div>
            </div>
          </div>

          {authType === 'cookie' ? (
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Cookie header value</div>
              <Textarea
                value={authCookie}
                onChange={(e) => setAuthCookie(e.target.value)}
                placeholder="atlassian.xsrf.token=...; cloud.session.token=..."
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
                <div className="text-sm font-medium text-foreground/80">Username / Email</div>
                <Input value={authUsername} onChange={(e) => setAuthUsername(e.target.value)} placeholder="bot@example.com" />
              </div>
              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground/80">Password / API Token</div>
                <Input type="password" value={authPassword} onChange={(e) => setAuthPassword(e.target.value)} />
              </div>
            </div>
          ) : null}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">目标数据集</div>
              <Select value={datasetId} onValueChange={setDatasetId}>
                <SelectTrigger className="h-10 bg-background">
                  <SelectValue placeholder="选择数据集" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={datasetDefaultValue}>默认（自动选择可写数据集）</SelectItem>
                  {datasets.map((ds) => (
                    <SelectItem key={ds.id} value={ds.id}>
                      {ds.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {datasetsLoading ? <div className="text-xs text-muted-foreground">正在加载数据集...</div> : null}
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">文档访问控制（可选）</div>
              <Select
                value={accessMode}
                onValueChange={(value) => setAccessMode(coerceOneOf(DOCUMENT_ACCESS_MODE_VALUES, value, 'inherit'))}
              >
                <SelectTrigger className="h-10 bg-background">
                  <SelectValue placeholder="选择访问模式" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="inherit">继承数据集</SelectItem>
                  <SelectItem value="only_me">仅我可见</SelectItem>
                  <SelectItem value="partial_members">指定成员/组</SelectItem>
                  <SelectItem value="all_team_members">团队成员</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {accessMode === 'partial_members' ? (
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground/80">允许组（可选）</div>
                <GroupChipsInput
                  value={accessGroupIds}
                  onChange={setAccessGroupIds}
                  placeholder="选择组（组内成员将自动获得访问权限）"
                />
              </div>

              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground/80">允许成员（每行一个 user_id）</div>
                <Textarea
                  value={accessMembers}
                  onChange={(e) => setAccessMembers(e.target.value)}
                  placeholder={'alice\nbob\ncharlie'}
                  className="font-mono min-h-[110px]"
                />
              </div>
            </div>
          ) : null}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Parser</div>
              <ParserDropdown value={parserBackend} onChange={setParserBackend} />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Chunk strategy</div>
              <ChunkStrategyDropdown value={effectiveChunkStrategy} onChange={setChunkStrategy} />
            </div>
          </div>

          <PipelineOptionsPanel />

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={submitting} className="gap-2">
              {submitting ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : null}
              Start Jira Sync
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
