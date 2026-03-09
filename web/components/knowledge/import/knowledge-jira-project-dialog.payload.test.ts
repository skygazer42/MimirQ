import { describe, expect, it } from 'vitest'

import { buildJiraProjectRunPayload } from './knowledge-jira-project-dialog.payload'

describe('buildJiraProjectRunPayload', () => {
  it('includes source_acl when enabled without manual access override', () => {
    const payload = buildJiraProjectRunPayload({
      datasetId: 'dataset-1',
      datasetDefaultValue: 'default-dataset',
      baseUrl: 'https://example.atlassian.net',
      projectKey: 'PLAT',
      jql: 'statusCategory != Done',
      auth: { type: 'bearer', token: 'secret' },
      syncMode: 'full',
      maxIssues: 25,
      pageSize: 10,
      includeComments: true,
      maxCommentsPerIssue: 5,
      userAgent: 'MimirQ/1.0 (+jira_project)',
      parserBackend: 'auto',
      chunkStrategy: 'jira_ticket',
      pipeline: undefined,
      accessMode: 'inherit',
      accessMembers: '',
      accessGroupIds: [],
      sourceAclEnabled: true,
      sourceAclFallbackMode: 'partial_members',
    })

    expect(payload).toEqual({
      connector_id: 'jira_project',
      dataset_id: 'dataset-1',
      config: expect.objectContaining({
        base_url: 'https://example.atlassian.net',
        project_key: 'PLAT',
        jql: 'statusCategory != Done',
        auth: { type: 'bearer', token: 'secret' },
        sync_mode: 'full',
        max_issues: 25,
        page_size: 10,
        include_comments: true,
        max_comments_per_issue: 5,
        user_agent: 'MimirQ/1.0 (+jira_project)',
        parser_backend: 'auto',
        chunk_strategy: 'jira_ticket',
        source_acl: {
          mode: 'inherit',
          fallback_mode: 'partial_members',
        },
      }),
    })
  })

  it('omits source_acl when manual access override is selected', () => {
    const payload = buildJiraProjectRunPayload({
      datasetId: 'default-dataset',
      datasetDefaultValue: 'default-dataset',
      baseUrl: 'https://example.atlassian.net',
      projectKey: 'PLAT',
      jql: '',
      auth: null,
      syncMode: 'auto',
      maxIssues: 50,
      pageSize: 25,
      includeComments: false,
      maxCommentsPerIssue: 0,
      userAgent: '',
      parserBackend: 'marker',
      chunkStrategy: 'jira_ticket',
      pipeline: undefined,
      accessMode: 'only_me',
      accessMembers: '',
      accessGroupIds: [],
      sourceAclEnabled: true,
      sourceAclFallbackMode: 'only_me',
    })

    expect(payload.dataset_id).toBeUndefined()
    expect(payload.config.access).toEqual({ mode: 'only_me', partial_member_list: null, partial_group_list: null })
    expect(payload.config.source_acl).toBeUndefined()
  })
})
