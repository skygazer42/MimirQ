import type {
  ConnectorRunCreateRequest,
  DocumentAccessMode,
  DocumentPipelineOptions,
  JiraProjectConnectorConfig,
  WebCrawlAuthConfig,
} from '@/types'
import { trimTrailingSlashes } from '@/lib/utils'

type JiraSyncMode = 'auto' | 'full' | 'incremental'
type JiraSourceAclFallbackMode = 'only_me' | 'partial_members'

export type JiraProjectRunPayloadInput = {
  datasetId: string
  datasetDefaultValue: string
  baseUrl: string
  projectKey: string
  jql: string
  auth: WebCrawlAuthConfig | null
  syncMode: JiraSyncMode
  maxIssues: number
  pageSize: number
  includeComments: boolean
  maxCommentsPerIssue: number
  userAgent: string
  parserBackend: string
  chunkStrategy: string
  pipeline?: DocumentPipelineOptions
  accessMode: DocumentAccessMode
  accessMembers: string
  accessGroupIds: string[]
  sourceAclEnabled: boolean
  sourceAclFallbackMode: JiraSourceAclFallbackMode
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

export function buildJiraProjectRunPayload(
  input: JiraProjectRunPayloadInput
): Extract<ConnectorRunCreateRequest, { connector_id: 'jira_project' }> {
  const trimmedBaseUrl = trimTrailingSlashes(input.baseUrl)
  const trimmedProjectKey = input.projectKey.trim().toUpperCase()
  const trimmedJql = input.jql.trim()
  const trimmedUserAgent = input.userAgent.trim()
  const hasManualAccessOverride = input.accessMode !== 'inherit'

  const access =
    input.accessMode === 'inherit'
      ? null
      : {
          mode: input.accessMode,
          partial_member_list: input.accessMode === 'partial_members' ? parseAccessMembers(input.accessMembers) : null,
          partial_group_list: input.accessMode === 'partial_members' ? input.accessGroupIds : null,
        }

  const config: JiraProjectConnectorConfig = {
    base_url: trimmedBaseUrl,
    project_key: trimmedProjectKey,
    jql: trimmedJql || undefined,
    auth: input.auth,
    sync_mode: input.syncMode,
    max_issues: Number.isFinite(input.maxIssues) ? Math.trunc(input.maxIssues) : 50,
    page_size: Number.isFinite(input.pageSize) ? Math.trunc(input.pageSize) : 25,
    include_comments: Boolean(input.includeComments),
    max_comments_per_issue: Number.isFinite(input.maxCommentsPerIssue) ? Math.trunc(input.maxCommentsPerIssue) : 20,
    user_agent: trimmedUserAgent || undefined,
    parser_backend: input.parserBackend,
    chunk_strategy: input.chunkStrategy,
    pipeline: input.pipeline,
    access,
    source_acl:
      input.sourceAclEnabled && !hasManualAccessOverride
        ? {
            mode: 'inherit',
            fallback_mode: input.sourceAclFallbackMode,
          }
        : undefined,
  }

  return {
    connector_id: 'jira_project',
    dataset_id: input.datasetId === input.datasetDefaultValue ? undefined : input.datasetId,
    config,
  }
}
