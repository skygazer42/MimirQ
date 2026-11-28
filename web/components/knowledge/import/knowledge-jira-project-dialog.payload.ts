import type { DocumentAccessMode } from '@/types/common'
import type { ConnectorRunCreateRequest, JiraProjectConnectorConfig, WebCrawlAuthConfig } from '@/types/connectors'
import type { DocumentPipelineOptions } from '@/types/processing'
import { parseAccessMembers } from './knowledge-import-parsers'

type JiraProjectRunPayloadInput = {
  datasetId: string
  datasetDefaultValue: string
  baseUrl: string
  projectKey: string
  jql: string
  auth: WebCrawlAuthConfig | null
  syncMode: NonNullable<JiraProjectConnectorConfig['sync_mode']>
  maxIssues: number
  pageSize: number
  includeComments: boolean
  maxCommentsPerIssue?: number
  userAgent: string
  parserBackend: string
  chunkStrategy: string
  pipeline?: DocumentPipelineOptions
  accessMode: DocumentAccessMode
  accessMembers: string
  accessGroupIds: string[]
  sourceAclEnabled: boolean
  sourceAclFallbackMode: 'only_me' | 'partial_members'
}

export function buildJiraProjectRunPayload(
  input: JiraProjectRunPayloadInput,
): Extract<ConnectorRunCreateRequest, { connector_id: 'jira_project' }> {
  const trimmedJql = input.jql.trim()
  const trimmedUserAgent = input.userAgent.trim()

  const access =
    input.accessMode === 'inherit'
      ? null
      : {
          mode: input.accessMode,
          partial_member_list: input.accessMode === 'partial_members' ? parseAccessMembers(input.accessMembers) : null,
          partial_group_list: input.accessMode === 'partial_members' ? input.accessGroupIds : null,
        }

  const config: JiraProjectConnectorConfig = {
    base_url: input.baseUrl,
    project_key: input.projectKey,
    jql: trimmedJql.length === 0 ? undefined : trimmedJql,
    auth: input.auth,
    sync_mode: input.syncMode,
    max_issues: input.maxIssues,
    page_size: input.pageSize,
    include_comments: input.includeComments,
    max_comments_per_issue: input.maxCommentsPerIssue,
    user_agent: trimmedUserAgent.length === 0 ? undefined : trimmedUserAgent,
    parser_backend: input.parserBackend,
    chunk_strategy: input.chunkStrategy,
    pipeline: input.pipeline,
    access,
    source_acl:
      input.sourceAclEnabled && input.accessMode === 'inherit'
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
